"""Shared view layer: templates, page context, and the derived views every vertical renders."""

from __future__ import annotations

import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from ..engine.materializer import Materializer
from ..engine.status import ABSENT, ERROR, PRESENT, UNSUPPORTED, Statuses
from ..engine.status import TONES as STATUS_TONES
from ..model.catalog import Catalog, Node
from ..model.text import plural
from ..model.typespec import TypeSpec
from ..run.runner import FAILED, PASSED, SKIPPED, StepResult, TestResult
from ..run.verdict import FAILING, NEVER_RUN, PASSING, SKIPPED_STATE, fold, state_of
from ..session import Session
from ..suite.discovery import Spec, Step, Test
from .deps import get_session
from .glossary import TERMS, Term, docs_url

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Lineage graph layout: columns by dependency depth, one box per node.
NODE_W = 168
NODE_H = 48
COL_GAP = 240
ROW_GAP = 60
PAD = 48

ENV_COOKIE = "atf-env"

# Set for the duration of a render so `u()` can reach it from anywhere, including imported macros.
_rendering_env: ContextVar[str] = ContextVar("atf_rendering_env", default="")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def cockpit() -> Session:
    """The session this request is being served from."""
    return get_session()


# ---- environment -----------------------------------------------------------


def current_env(request: Request) -> str:
    """The environment this request is about.

    An explicitly named environment that does not exist is an error, not a fallback: silently
    showing dev to someone who asked for staging would let them act on the wrong place.
    """
    app = cockpit()
    for requested in (request.query_params.get("env"), request.headers.get("HX-Env")):
        if requested:
            if requested in app.manifest.environments:
                return requested
            known = ", ".join(sorted(app.manifest.environments))
            raise HTTPException(status_code=404, detail=f"unknown environment {requested!r} — this suite has {known}")

    remembered = request.cookies.get(ENV_COOKIE)
    if remembered and remembered in app.manifest.environments:
        return remembered
    return app.default_env


def require_mutable(env: str) -> None:
    """Every mutating route calls this first: only `mutable_envs` may be changed."""
    if not cockpit().is_mutable(env):
        raise HTTPException(
            status_code=409,
            detail=f"{env} is read-only — add it to `mutable_envs` in atf.yaml to let the cockpit change it",
        )


def require_confirmation(token: str | None) -> None:
    if not token or not secrets.compare_digest(token, cockpit().confirm_token):
        raise HTTPException(status_code=409, detail="this action must be confirmed — reload the page and try again")


# ---- rendering -------------------------------------------------------------


def is_htmx(request: Request) -> bool:
    """Whether htmx asked for this, and so whether a fragment answers it."""
    return request.headers.get("HX-Request") == "true"


def page(request: Request, template: str, **context: Any) -> Any:
    app = cockpit()
    env = context.pop("env", None) or current_env(request)
    base = {
        "request": request,
        "env": env,
        "environments": app.environments.names,
        "mutable": app.is_mutable(env),
        "confirm_token": app.confirm_token,
        "counts": nav_counts(env),
        "manifest": app.manifest,
        "display": app.manifest.display,
        "activity": app.jobs.active(env),
        "checked_at": _checked_at(app.status.age(env)),
        "partial": is_htmx(request),
    }
    _rendering_env.set(env)
    response = templates.TemplateResponse(request, template, {**base, **context})
    response.set_cookie(ENV_COOKIE, env, samesite="strict", httponly=True)
    return response


def partial(request: Request, template: str, **context: Any) -> Any:
    app = cockpit()
    env = context.pop("env", None) or current_env(request)
    base = {
        "request": request,
        "env": env,
        "mutable": app.is_mutable(env),
        "confirm_token": app.confirm_token,
        "display": app.manifest.display,
    }
    _rendering_env.set(env)
    return templates.TemplateResponse(request, template, {**base, **context})


def _checked_at(age: float | None) -> float | None:
    """Status freshness as an absolute time, which is what `ago()` reads."""
    return None if age is None else time.time() - age


def nav_counts(env: str) -> dict[str, int]:
    app = cockpit()
    return {
        "catalog": len(app.state(env).materializer.nodes),
        "scenarios": len(app.discovery.of(env).specs),
    }


# ---- readiness: what would happen if you ran this now -----------------------

# A scenario the cockpit can see something the CLI cannot: that running it will not help.
BLOCKED = "blocked"

# An absent resource blocks nothing: naming it in a scenario is precisely what makes ATF create it.
# These are the states that running cannot fix on its own.
_BLOCKING = {
    UNSUPPORTED: "no adapter for this system in this environment",
    ERROR: "the adapter raised while looking it up",
}


@dataclass
class Readiness:
    """The gap between a set of resources and a run that reaches its first `When`."""

    blockers: list[tuple[str, str]] = field(default_factory=list)
    will_create: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)


def readiness(node_ids: list[str], engine: Materializer, status: Statuses) -> Readiness:
    """What stands between these resources and a run that reaches its first `When`.

    Why a resource cannot be created is the engine's answer, not this module's: the banner here and
    the button on the catalog page are the same question asked by two surfaces.
    """
    out = Readiness()
    seen: set[str] = set()
    for node_id in node_ids:
        for member in engine.catalog.closure(node_id, seen):
            entry = status.of(member)
            reason = _BLOCKING.get(entry.state)
            if reason:
                out.blockers.append((member, reason))
            elif entry.state == ABSENT:
                refusal = engine.provisionable(member)
                if refusal.blocks:
                    out.blockers.append((member, refusal.why))
                elif refusal.creatable:
                    out.will_create.append(member)
    return out



@dataclass
class ScenarioView:
    """One scenario, fused with everything the cockpit knows about running it."""

    spec: Spec
    tests: list[Test]
    state: str
    ready: Readiness
    outcome: str = "not run"
    last_run_at: float | None = None
    duration: float = 0.0
    flaky: bool = False
    failed_step: StepResult | None = None
    steps: list[StepResult] = field(default_factory=list)
    detail: str = ""

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def nodeids(self) -> list[str]:
        return [test.nodeid for test in self.tests]

    @property
    def tone(self) -> str:
        return {PASSING: "ok", FAILING: "bad", BLOCKED: "warn", SKIPPED_STATE: "warn"}.get(self.state, "idle")

    def step_state(self, step: Step) -> str:
        """How far the last run got: the steps before a failure are worth seeing as passed.

        Matched on text, never on keyword: pytest-bdd resolves a repeated `And` to the concrete
        keyword it continues, so the two spellings do not agree.
        """
        return next((observed.state for observed in self.steps if observed.text == step.text), "")


_NO_RESULT = TestResult(nodeid="", outcome="not run")


def scenario_views(env: str) -> list[ScenarioView]:
    app = cockpit()
    found = app.discovery.of(env)
    engine = app.state(env).materializer
    status = app.status.of(env)
    results = app.results.of(env)
    flaky = app.results.flaky(env)

    views: list[ScenarioView] = []
    for spec in found.specs:
        tests = found.tests_for_spec(spec.id)
        mine = [results[test.nodeid] for test in tests if test.nodeid in results]
        outcomes = [result.outcome for result in mine]
        failed = next((result for result in mine if result.outcome in {FAILED, ERROR}), None)
        ready = readiness(spec.resources, engine, status)

        views.append(
            ScenarioView(
                spec=spec,
                tests=tests,
                state=_scenario_state(spec, outcomes, ready),
                ready=ready,
                outcome=fold(outcomes),
                last_run_at=max((result.finished_at for result in mine), default=None),
                duration=sum(result.duration for result in mine),
                flaky=any(flaky.get(test.nodeid) for test in tests),
                failed_step=failed.failed_step if failed else None,
                steps=list((failed or next(iter(mine), None) or _NO_RESULT).steps),
                detail=failed.detail if failed else "",
            )
        )
    return views


def _scenario_state(spec: Spec, outcomes: list[str], ready: Readiness) -> str:
    """How it stands, plus the one thing only the cockpit knows: whether running it would help."""
    state = state_of(spec.skipped, outcomes)
    if state in {FAILING, SKIPPED_STATE}:
        return state
    return BLOCKED if ready.blocked else state


# ---- resource types: the axis the catalog is navigated by -------------------


@dataclass
class TypeView:
    """A resource type, with everything a spec author needs in order to use one."""

    spec: TypeSpec
    nodes: list[Node] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    specs: list[Spec] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def system(self) -> str:
        return self.spec.system

    @property
    def mode(self) -> str:
        return self.spec.mode

    @property
    def lifecycle(self) -> str:
        return self.spec.lifecycle

    @property
    def id_field(self) -> str:
        return self.spec.id_field

    @property
    def config(self) -> dict[str, Any]:
        return self.spec.config

    @property
    def example(self) -> str:
        """The Gherkin line that uses one. The type page is where a spec author learns this."""
        name = self.nodes[0].name if self.nodes else "name"
        return f'Given the {self.name} "{name}"'

    @property
    def total(self) -> int:
        return len(self.nodes)

    @property
    def present(self) -> int:
        return self.counts.get(PRESENT, 0)

    @property
    def tone(self) -> str:
        if self.counts.get(ERROR) or self.counts.get(UNSUPPORTED):
            return "bad"
        if self.spec.ephemeral:
            return "accent"
        return "ok" if self.total and self.present == self.total else "idle"


def type_views(env: str) -> dict[str, TypeView]:
    app = cockpit()
    engine = app.state(env).materializer
    status = app.status.of(env)
    found = app.discovery.of(env)

    views = {name: TypeView(spec=spec) for name, spec in sorted(engine.types.items())}

    for node in sorted(engine.nodes.values(), key=lambda item: item.name):
        view = views.get(node.resource)
        if view is None:
            continue
        view.nodes.append(node)
        state = status.state(node.id)
        view.counts[state] = view.counts.get(state, 0) + 1

    for spec in found.specs:
        for node_id in spec.resources:
            node = engine.nodes.get(node_id)
            view = views.get(node.resource) if node else None
            if view is not None and spec not in view.specs:
                view.specs.append(spec)

    return views


# ---- the overview verdict ---------------------------------------------------


@dataclass
class Verdict:
    tone: str
    headline: str
    detail: str
    at: float | None = None


def verdict(env: str, scenarios: list[ScenarioView]) -> Verdict:
    """The answer to the question this app exists to ask, in one sentence."""
    last = cockpit().results.last_run(env)
    failing = [view for view in scenarios if view.state == FAILING]
    blocked = [view for view in scenarios if view.state == BLOCKED]
    passing = [view for view in scenarios if view.state == PASSING]
    never = [view for view in scenarios if view.state == NEVER_RUN]

    if last is None:
        return Verdict("idle", "Not yet", f"Nothing has ever run against {env}.", None)
    if failing:
        return Verdict(
            "bad",
            f"No — {plural(len(failing), 'scenario')} failing",
            f"{len(passing)} passing, {len(never)} never run.",
            last.finished_at,
        )
    if never or blocked:
        detail = f"{len(passing)} passing, {plural(len(never), 'scenario')} never run"
        detail += f", {len(blocked)} blocked." if blocked else "."
        return Verdict("warn", "Not fully", detail, last.finished_at)
    return Verdict("ok", "Yes", f"All {plural(len(passing), 'scenario')} passing.", last.finished_at)


# ---- lineage graph ----------------------------------------------------------


@dataclass
class GraphBox:
    id: str
    label: str
    sub: str
    x: int
    y: int
    focus: bool
    status: str
    system: str
    represents: str


@dataclass
class GraphEdge:
    path: str
    frm: str
    to: str


@dataclass
class Graph:
    boxes: list[GraphBox]
    edges: list[GraphEdge]
    width: int
    height: int
    focus: str


def neighbourhood(catalog: Catalog, focus: str) -> dict[str, int]:
    """Every node in the focus node's lineage, mapped to its column (0 = focus)."""
    layers: dict[str, int] = {focus: 0}

    def walk(current: str, depth: int, upstream: bool) -> None:
        node = catalog.nodes[current]
        neighbours = node.depends_on if upstream else node.dependents
        for neighbour in neighbours:
            if neighbour not in catalog.nodes:
                continue
            column = depth + (-1 if upstream else 1)
            if neighbour not in layers or abs(column) < abs(layers[neighbour]):
                layers[neighbour] = column
                walk(neighbour, column, upstream)

    walk(focus, 0, upstream=True)
    walk(focus, 0, upstream=False)
    return layers


def build_graph(catalog: Catalog, focus: str, status: Statuses) -> Graph:
    layers = neighbourhood(catalog, focus)
    columns: dict[int, list[str]] = {}
    for node_id, column in sorted(layers.items()):
        columns.setdefault(column, []).append(node_id)

    order = sorted(columns)
    tallest = max((len(members) for members in columns.values()), default=1)
    height = PAD * 2 + tallest * NODE_H + (tallest - 1) * ROW_GAP
    width = PAD * 2 + len(order) * NODE_W + max(len(order) - 1, 0) * (COL_GAP - NODE_W)

    positions: dict[str, tuple[int, int]] = {}
    boxes: list[GraphBox] = []
    for index, column in enumerate(order):
        members = columns[column]
        span = len(members) * NODE_H + (len(members) - 1) * ROW_GAP
        top = (height - span) // 2
        for row, node_id in enumerate(members):
            x = PAD + index * COL_GAP
            y = top + row * (NODE_H + ROW_GAP)
            positions[node_id] = (x, y)
            node = catalog.nodes[node_id]
            boxes.append(
                GraphBox(
                    id=node_id,
                    label=node.name,
                    sub=node.resource,
                    x=x,
                    y=y,
                    focus=node_id == focus,
                    status=status.state(node_id),
                    system=node.system,
                    represents=node.represents,
                )
            )

    edges: list[GraphEdge] = []
    for node_id in layers:
        for dependency in catalog.nodes[node_id].depends_on:
            if dependency not in positions or node_id not in positions:
                continue
            start = positions[dependency]
            end = positions[node_id]
            x1, y1 = start[0] + NODE_W, start[1] + NODE_H // 2
            x2, y2 = end[0], end[1] + NODE_H // 2
            mid = (x1 + x2) // 2
            edges.append(
                GraphEdge(path=f"M {x1} {y1} C {mid} {y1}, {mid} {y2}, {x2} {y2}", frm=dependency, to=node_id)
            )

    return Graph(boxes=boxes, edges=edges, width=width, height=height, focus=focus)


def lineage_sentence(node: Node, catalog: Catalog) -> str:
    """The graph in words, which is what someone new to the suite actually reads."""
    chain = [member for member in catalog.closure(node.id) if member != node.id]
    if not chain:
        return f"Nothing has to exist first — provisioning {node.name} is a single create."
    names = ", ".join(catalog.nodes[member].name for member in chain)
    return (
        f"{node.name} needs {names}. Provisioning it provisions "
        f"{plural(len(chain) + 1, 'resource')} in all, dependencies first."
    )


# ---- status vocabulary ------------------------------------------------------

TONES = {
    **STATUS_TONES,
    PASSED: "ok",
    PASSING: "ok",
    "pending": "idle",
    "not run": "idle",
    NEVER_RUN: "idle",
    "running": "running",
    FAILED: "bad",
    FAILING: "bad",
    SKIPPED: "warn",
    "flaky": "warn",
    "mixed": "warn",
}


def tone(status: str) -> str:
    return TONES.get(status, "idle")


def ago(when: float | None) -> str:
    """A timestamp as a reader thinks of it. Freshness is the whole point of this app."""
    if not when:
        return "never"
    seconds = max(0.0, time.time() - when)
    if seconds < 45:
        return "just now"
    for limit, size, unit in ((3600, 60, "min"), (86400, 3600, "hour"), (604800, 86400, "day")):
        if seconds < limit:
            # Rounded, not truncated: 50 seconds is "1 min ago", never "0 mins ago".
            count = max(1, round(seconds / size))
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return f"{max(1, round(seconds / 604800))} weeks ago"


def duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"


def u(path: str, **params: Any) -> str:
    """A link that cannot lose the environment — the one thing every URL here must carry.

    The environment comes from a context variable, not the template context, so a macro imported
    without `with context` still produces correct links.

    Values are percent-encoded here, once: catalog names, feature names and scenario states all reach
    these URLs, and a space or an ampersand in one must not truncate it.
    """
    query = {"env": _rendering_env.get(""), **params}
    encoded = urlencode({key: value for key, value in query.items() if value not in (None, "")})
    return f"{path}?{encoded}" if encoded else path


def glossary(key: str) -> Term | None:
    return TERMS.get(key)


def relative(path: str) -> str:
    """A path as the person who wrote it types it: from the suite root, not from `/`.

    Every path the cockpit holds is absolute, pytest reporting them that way, and the leading half of
    one is the same on every line of every page.
    """
    if not path:
        return ""
    root = cockpit().manifest.root
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path


_GLOBALS: dict[str, Any] = {
    "tone": tone,
    "ago": ago,
    "dur": duration,
    "u": u,
    "docs": docs_url,
    "rel": relative,
    "glossary": glossary,
    "NODE_W": NODE_W,
    "NODE_H": NODE_H,
}
templates.env.globals.update(_GLOBALS)
