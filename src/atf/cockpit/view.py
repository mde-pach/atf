"""Shared view layer: templates, page context, and the derived views every vertical renders.

The routers stay thin because the interesting work is here — turning the raw model (catalog nodes,
environment status, discovery, run history) into the conclusions the interface shows: is this
scenario runnable, what would provisioning it actually do, can I ship.
"""

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

from ..catalog import Node
from ..discovery import Spec, Step, Test
from ..engine.status import ABSENT, ERROR, PRESENT, UNSUPPORTED, Statuses
from ..engine.status import TONES as STATUS_TONES
from ..runner import FAILED, PASSED, SKIPPED, StepResult, TestResult
from ..typespec import DATA, REFERENCE, TypeSpec
from .deps import Cockpit, get_cockpit
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


def cockpit() -> Cockpit:
    return get_cockpit()


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


def page(request: Request, template: str, **context: Any) -> Any:
    app = cockpit()
    env = context.pop("env", None) or current_env(request)
    base = {
        "request": request,
        "env": env,
        "environments": app.environments,
        "mutable": app.is_mutable(env),
        "confirm_token": app.confirm_token,
        "counts": nav_counts(env),
        "manifest": app.manifest,
        "display": app.manifest.display,
        "activity": app.active_job(env),
        "checked_at": _checked_at(app.status_age(env)),
        "partial": request.headers.get("HX-Request") == "true",
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
    """Status freshness as an absolute time, because that is what `ago()` reads."""
    return None if age is None else time.time() - age


def nav_counts(env: str) -> dict[str, int]:
    app = cockpit()
    return {
        "catalog": len(app.state(env).materializer.nodes),
        "scenarios": len(app.discovery(env).specs),
    }


# ---- readiness: what would happen if you ran this now -----------------------

PASSING = "passing"
FAILING = "failing"
BLOCKED = "blocked"
NEVER_RUN = "never run"
SKIPPED_STATE = "skipped"

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


def readiness(node_ids: list[str], nodes: dict[str, Node], status: Statuses) -> Readiness:
    out = Readiness()
    seen: set[str] = set()
    for node_id in node_ids:
        for member in closure_of(node_id, nodes, seen):
            entry = status.of(member)
            reason = _BLOCKING.get(entry.state)
            if reason:
                out.blockers.append((member, reason))
            elif entry.state == ABSENT and nodes[member].mode == REFERENCE:
                out.blockers.append((member, "must already exist here — ATF never creates a reference resource"))
            elif nodes[member].mode == DATA:
                # An observation is not a precondition. Absent means only "not there yet", which is
                # frequently the very thing the scenario is about to claim.
                continue
            elif entry.state == ABSENT:
                out.will_create.append(member)
    return out


def closure_of(node_id: str, nodes: dict[str, Node], seen: set[str] | None = None) -> list[str]:
    """A node and everything it depends on, transitively, each listed once."""
    seen = seen if seen is not None else set()
    if node_id in seen or node_id not in nodes:
        return []
    seen.add(node_id)
    members = [node_id]
    for dependency in nodes[node_id].depends_on:
        members.extend(closure_of(dependency, nodes, seen))
    return members


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

        Matched on text rather than keyword, because pytest-bdd resolves a repeated `And` to the
        concrete keyword it continues, so the two spellings will not agree.
        """
        return next((observed.state for observed in self.steps if observed.text == step.text), "")


_NO_RESULT = TestResult(nodeid="", outcome="not run")


def scenario_views(env: str) -> list[ScenarioView]:
    app = cockpit()
    found = app.discovery(env)
    nodes = app.state(env).materializer.nodes
    status = app.status(env)
    results = app.results(env)
    flaky = app.flaky(env)

    views: list[ScenarioView] = []
    for spec in found.specs:
        tests = found.tests_for_spec(spec.id)
        mine = [results[test.nodeid] for test in tests if test.nodeid in results]
        outcomes = [result.outcome for result in mine]
        failed = next((result for result in mine if result.outcome in {FAILED, ERROR}), None)
        ready = readiness(spec.resources, nodes, status)

        views.append(
            ScenarioView(
                spec=spec,
                tests=tests,
                state=_scenario_state(spec, outcomes, ready),
                ready=ready,
                outcome=_fold_outcomes(outcomes),
                last_run_at=max((result.finished_at for result in mine), default=None),
                duration=sum(result.duration for result in mine),
                flaky=any(flaky.get(test.nodeid) for test in tests),
                failed_step=failed.failed_step if failed else None,
                steps=list((failed or next(iter(mine), None) or _NO_RESULT).steps),
                detail=failed.detail if failed else "",
            )
        )
    return views


def _fold_outcomes(outcomes: list[str]) -> str:
    if not outcomes:
        return "not run"
    unique = set(outcomes)
    if len(unique) == 1:
        return outcomes[0]
    return FAILED if unique & {FAILED, ERROR} else "mixed"


def _scenario_state(spec: Spec, outcomes: list[str], ready: Readiness) -> str:
    if spec.skipped:
        return SKIPPED_STATE
    if any(outcome in {FAILED, ERROR} for outcome in outcomes):
        return FAILING
    if ready.blocked:
        return BLOCKED
    if outcomes and all(outcome == PASSED for outcome in outcomes):
        return PASSING
    return NEVER_RUN


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
    status = app.status(env)
    found = app.discovery(env)

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
    last = cockpit().last_run(env)
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


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


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


def neighbourhood(nodes: dict[str, Node], focus: str) -> dict[str, int]:
    """Every node in the focus node's lineage, mapped to its column (0 = focus)."""
    layers: dict[str, int] = {focus: 0}

    def walk(current: str, depth: int, upstream: bool) -> None:
        node = nodes[current]
        neighbours = node.depends_on if upstream else node.dependents
        for neighbour in neighbours:
            if neighbour not in nodes:
                continue
            column = depth + (-1 if upstream else 1)
            if neighbour not in layers or abs(column) < abs(layers[neighbour]):
                layers[neighbour] = column
                walk(neighbour, column, upstream)

    walk(focus, 0, upstream=True)
    walk(focus, 0, upstream=False)
    return layers


def build_graph(nodes: dict[str, Node], focus: str, status: Statuses) -> Graph:
    layers = neighbourhood(nodes, focus)
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
            node = nodes[node_id]
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
        for dependency in nodes[node_id].depends_on:
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


def lineage_sentence(node: Node, nodes: dict[str, Node]) -> str:
    """The graph in words, which is what someone new to the suite actually reads."""
    chain = [member for member in closure_of(node.id, nodes) if member != node.id]
    if not chain:
        return f"Nothing has to exist first — provisioning {node.name} is a single create."
    names = ", ".join(nodes[member].name for member in chain)
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


def outcome_of(nodeid: str, results: dict[str, Any]) -> str:
    result = results.get(nodeid)
    return result.outcome if result else "not run"


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

    The environment comes from a context variable rather than the template context, so a macro
    imported without `with context` still produces correct links. Losing the environment silently
    is the one failure this helper exists to prevent, so it must not depend on how it was reached.

    Values are percent-encoded here rather than at each call site: catalog names, feature names and
    scenario states all reach these URLs, and a space or an ampersand in one must not truncate it.
    """
    query = {"env": _rendering_env.get(""), **params}
    encoded = urlencode({key: value for key, value in query.items() if value not in (None, "")})
    return f"{path}?{encoded}" if encoded else path


def glossary(key: str) -> Term | None:
    return TERMS.get(key)


def relative(path: str) -> str:
    """A path as the person who wrote it types it: from the suite root, not from `/`.

    Every path the cockpit holds is absolute, because that is what pytest reports. Nobody reads a
    file that way, and the leading half of it is the same on every line of every page.
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
