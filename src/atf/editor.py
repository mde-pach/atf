"""`atf edit` — a local server over the suite, reading only `core`."""

from __future__ import annotations

import html
import json
import re
import signal
import subprocess
import sys
import time
import urllib.parse
from datetime import UTC
from pathlib import Path
from typing import Any

from . import core, kinds, runs
from .environment import build_ground
from .feature import FeatureError
from .loader import load_suite
from .manifest import load

#: Cache-busts `/static/*` on every process start — a browser that has this page open across a
#: restart (editing the dashboard *while* it's the thing being tested) would otherwise keep
#: serving its old cached CSS/JS against the new HTML until a hard refresh, silently.
_ASSET_VERSION = str(int(time.time()))

VIEWS = ("overview", "resources", "graph", "tests", "sentences", "composer", "activity", "environments")

#: The five screens in the fixed chrome, in order. `sentences` and `environments` are real pages —
#: reachable from Overview and Faults — but they carry no dashboard of their own, so they stay out
#: of the nav that is otherwise byte-identical on every screen. `composer` is reachable too, but as
#: the Tests page's own "Create test" button — writing one test is that page's business, not a
#: standing destination next to Overview and Graph.
NAV_VIEWS = ("overview", "resources", "graph", "tests", "activity")


def _as_node(node: core.Node) -> dict[str, Any]:
    return {"id": node.id, "label": node.label, "kind": node.kind, "needs": node.needs}


def _wrap_as_feature(text: str, named: str) -> str:
    """A typed draft, given the headers it needs to be a whole, readable `.feature` file.

    Shared by every scratch write in this module — trying a draft, and linting one — so a draft
    that already has its own `Scenario:`/`Example:`/`Phrase:`/`Feature:` line is never double-wrapped.
    """
    stripped = text.lstrip()
    if not stripped.startswith(("Scenario:", "Example:", "Phrase:")):
        text = f"Scenario: {named}\n" + "\n".join(f"    {line}" for line in text.splitlines())
    if not stripped.startswith("Feature:"):
        text = f"Feature: {named}\n\n{text}"
    return text.rstrip("\n") + "\n"


class RunTracker:
    """The one suite run this editor may have going, if any.

    A real subprocess — the same `sys.executable -m atf run` invocation `--jobs` sharding already
    uses — never in-process. `do_run` leans on module-level state in `plugin.py` and a "one ground
    per process" contextvar; a background thread inside this same server would race both.
    """

    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, manifest: Path | None, env: str, tests: tuple[str, ...] = ()) -> bool:
        """Start a run, unless one is already going. `True` where this call is the one that started it."""
        if self.running:
            return False
        args = [sys.executable, "-m", "atf", "run", "--quiet"]
        if manifest:
            args += ["--config", str(manifest)]
        if env:
            args += ["--env", env]
        args += list(tests)
        self.process = subprocess.Popen(args)  # noqa: S603 - a fixed argv, not user input
        self.started_at = time.monotonic()
        return True

    def cancel(self) -> bool:
        """Ask the run to stop where it is — the same interrupt Ctrl-C sends `atf run`.

        Whatever teardown a normal end triggers still runs; escalates only if it does not stop.
        """
        if self.process is None or not self.running:
            return False
        self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
        return True

    def elapsed(self) -> float:
        return 0.0 if self.started_at is None else time.monotonic() - self.started_at


class Editor:
    """One suite, one environment, and the six views over it."""

    def __init__(self, manifest: Path | None = None, env: str = "") -> None:
        self.manifest_path = manifest
        self.default_env = env
        self.env = env
        self.run_tracker = RunTracker()
        self.reload()

    def reload(self, env: str | None = None) -> None:
        """Re-read everything for one environment. Refreshing re-asks, never remembers.

        The environment is an argument to every question the core answers, so it is an argument
        here: a request naming one is answered against that one, and `?env=` is how a link carries
        it.
        """
        from .plugin import (
            Loaded,
        )

        self.env = env or self.default_env
        self.suite = load_suite(load(self.manifest_path) if self.manifest_path else None)
        self.ground = build_ground(self.suite, self.env)
        self.root = self.suite.manifest.root
        try:
            loaded = Loaded(self.root)
            self.features, self.phrases = loaded.features, loaded.phrases
        except Exception:  # noqa: BLE001 - a suite whose specs will not read still has resources
            self.features, self.phrases = [], {}

    # --- The views, each one a call into core ---------------------------------------------------

    def faults(self) -> list[dict[str, str]]:
        """What `atf plan` finds wrong with the suite, through the same call the command makes."""
        from . import (
            plan as planning,
        )

        return [
            {"where": one.where, "why": one.what, "check": "lint"}
            for one in planning.lint(self.suite, self.features, self.phrases)
        ]

    def overview(self) -> dict[str, Any]:
        summary = core.overview(self.ground, self.root, faults=len(self.faults()))
        return {
            "sentence": summary.sentence,
            "faults": summary.faults,
            "ready": summary.ready,
            "resources": summary.resources,
            "tests": summary.tests,
            "last_run": summary.last_run.as_json() if summary.last_run else None,
            "well_formed": summary.well_formed,
        }

    def resources(self) -> list[dict[str, Any]]:
        return [
            {"kind": one.kind, "system": one.system, "owner": one.owner, "declared": one.declared, "states": one.states}
            for one in core.resources(self.ground)
        ]

    def instances(self, kind: str) -> list[dict[str, Any]]:
        return core.instances(self.ground, kind)

    def undeclared(self, kind: str) -> dict[str, Any]:
        """What `browse()` finds for this kind that nothing declared matches — read-only."""
        found = core.undeclared(self.ground, kind)
        return {"browsable": found.browsable, "why": found.why, "records": found.records}

    def resource(self, name: str) -> dict[str, Any]:
        found = core.detail(self.ground, name)
        return {
            "name": found.name,
            "kind": found.kind,
            "system": found.system,
            "state": found.state,
            "declaration": found.declaration,
            "recognised_by": found.recognised_by,
            "found": found.found,
            "would_create": found.would_create,
            "would_change": found.would_change,
            "can_make": found.can_make,
            "why_not": found.why_not,
        }

    def resource_state(self, names: list[str]) -> list[dict[str, Any]]:
        """What `atf enter` would show for each of these resources — the Output tab's own data."""
        return core.state_of(self.ground, names)

    def graph(self) -> list[dict[str, Any]]:
        return [_as_node(node) for node in core.spine(self.suite, self.features, self.phrases)]

    def node(self, id: str) -> dict[str, Any]:
        """One node and every edge touching it. `KeyError` where the spine has no such node."""
        here = core.around(self.suite, self.features, self.phrases, id)
        return {
            "id": here.id,
            "label": here.label,
            "kind": here.kind,
            "sentence": here.sentence,
            "needs": [_as_node(one) for one in here.needs],
            "needed_by": [_as_node(one) for one in here.needed_by],
        }

    def tests(self) -> list[dict[str, Any]]:
        return [
            {
                "id": one.id,
                "label": one.label,
                "form": one.form,
                "tags": one.tags,
                "verdict": one.verdict,
                "flaky": one.flaky,
                "arranges": one.arranges,
                "description": one.description,
            }
            for one in core.tests(self.suite, self.features, self.root, self.ground.config.name, self.phrases)
        ]

    def test(self, id: str) -> dict[str, Any]:
        """One test opened. `KeyError` where the suite describes no such behaviour."""
        found = core.detail_of_test(
            self.suite, self.features, self.root, self.ground.config.name, id, self.phrases
        )
        return {
            "id": found.id,
            "label": found.label,
            "form": found.form,
            "tags": found.tags,
            "verdict": found.verdict,
            "flaky": found.flaky,
            "where": found.where,
            "path": found.path,
            "number": found.number,
            "lines": found.lines,
            "arranges": list(found.arranges),
            "last": found.last.as_json() if found.last else None,
            "before": found.before,
        }

    def test_state(self, id: str) -> dict[str, Any]:
        """One test opened, plus the state `atf enter` would show for what it arranges."""
        found = self.test(id)
        kinds = {name: type(self.suite.instances[name]).__name__ for name in found["arranges"]}
        return {**found, "state": self.resource_state(found["arranges"]), "kinds": kinds}

    def run(self, tests: tuple[str, ...] = ()) -> bool:
        """Start a run in the background — **the same command** `atf run` makes, named or not.

        Returns whether this call is the one that started it; a run already going is left alone,
        not queued or restarted, so a second click can't stack a second process behind the first.
        """
        return self.run_tracker.start(self.manifest_path, self.ground.config.name, tests)

    def run_status(self) -> dict[str, Any]:
        """Whether a run is going, how long it has been, and how long the last one here took."""
        running = self.run_tracker.running
        estimate = None
        if not running:
            past = runs.runs_for(self.root, self.ground.config.name)
            if past and past[-1].finished:
                from datetime import datetime

                fmt = "%Y-%m-%dT%H:%M:%SZ"
                started = datetime.strptime(past[-1].started, fmt).replace(tzinfo=UTC)
                finished = datetime.strptime(past[-1].finished, fmt).replace(tzinfo=UTC)
                estimate = (finished - started).total_seconds()
        return {"running": running, "elapsed": self.run_tracker.elapsed(), "estimate": estimate}

    def cancel_run(self) -> bool:
        """Interrupt the run in progress — the same signal Ctrl-C sends `atf run` at a terminal."""
        return self.run_tracker.cancel()

    def composer(self, so_far: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        """The one view with no command behind it: it writes Gherkin, and performs nothing.

        What it offers depends on what is already written, so ordering the steps differently
        re-answers the offer. That is not decoration: a claim about a result nothing has produced
        cannot be offered, and the composer is what knows it.
        """
        offered = core.offers(self.ground, self.phrases, so_far or [])
        return {
            "offers": [
                {"keyword": one.keyword, "sentence": one.sentence, "why": one.why} for one in offered
            ],
            "kinds": kinds.offered(),
            "quiet": core.why_no_when(self.ground, self.suite),
            "subjects": core.subjects(self.suite),
        }

    def compose(self, name: str, scenario: str, lines: list[tuple[str, str]]) -> Path:
        """Write a feature file under the specs directory, and perform nothing.

        There is no editor-only syntax, no generated header, and nothing in the file saying it was
        composed. What comes out is Gherkin somebody could have typed.
        """
        specs = self.suite.manifest.specs
        specs.mkdir(parents=True, exist_ok=True)
        path = specs / (name if name.endswith(".feature") else f"{name}.feature")
        body = [f"Feature: {name.removesuffix('.feature')}", "", f"  Scenario: {scenario}"]
        body += [f"    {keyword.title()} {sentence}" for keyword, sentence in lines]
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        self.reload()
        return path

    def compose_text(self, name: str, text: str) -> str:
        """Write a new scenario typed as free text — appended, or the file created if it's new.

        Written, then re-read through the real parser, then checked by the same lint a save from
        the existing-test editor runs: a suite that no longer reads, or that reads but says
        something nothing here understands, is not kept — the original bytes come back, or a file
        created just now is removed. Returns the new test's id, so the caller can open straight
        back into it.
        """
        from . import feature as feature_module
        from .feature import FeatureError

        specs = self.suite.manifest.specs
        specs.mkdir(parents=True, exist_ok=True)
        path = specs / (name if name.endswith(".feature") else f"{name}.feature")
        block = text.rstrip("\n") + "\n"
        existed = path.exists()
        original = path.read_text(encoding="utf-8") if existed else ""
        trimmed = original.rstrip("\n")
        candidate = f"{trimmed}\n\n{block}" if existed else f"Feature: {path.stem}\n\n{block}"
        path.write_text(candidate, encoding="utf-8")

        def revert() -> None:
            if existed:
                path.write_text(original, encoding="utf-8")
            else:
                path.unlink(missing_ok=True)

        try:
            parsed = feature_module.read(path)
        except FeatureError:
            revert()
            raise
        self.reload()
        newest = parsed.scenarios[-1]
        problems = core.lint_file(self.suite, self.features, self.phrases, path, newest.number)
        if problems:
            revert()
            self.reload()
            raise core.LintError("; ".join(problems))
        return runs.identity(path, newest.name, self.root)

    def test_source(self, id: str) -> dict[str, Any]:
        """The whole file this test lives in, exactly as written — for opening in the editor.

        Opening a test opens its file: a `.feature` file is usually more than one scenario, and
        editing one in isolation would hide the rest of what it stands beside. `number` still says
        which scenario this open was *about*, for the pane to scroll to and mark as current.
        """
        found = self.test(id)
        if not found["path"]:
            raise ValueError("this test is written in Python — there is no Gherkin source to open")
        path = Path(found["path"])
        text = path.read_text(encoding="utf-8")
        later = sorted(
            scenario.number
            for feature in self.features
            if feature.path == path
            for scenario in feature.scenarios
            if scenario.number > found["number"]
        )
        end = later[0] - 1 if later else len(text.splitlines())
        return {"id": found["id"], "path": found["path"], "number": found["number"], "end": end, "text": text}

    def save_test_source(self, id: str, text: str) -> None:
        """Save a test's whole file back in place — every scenario in it, not just the one opened.

        Written, then re-read through the real parser, then checked by the same lint `atf plan`
        runs over the whole file: a suite that no longer reads, or reads but says something
        nothing here understands, is not kept — the original bytes come back first.
        """
        found = self.test(id)
        if not found["path"]:
            raise ValueError("this test is written in Python — there is no Gherkin source to save")
        path = Path(found["path"])
        original = path.read_text(encoding="utf-8")
        core.save_file(path, text)
        self.reload()
        problems = core.lint_file(self.suite, self.features, self.phrases, path)
        if problems:
            path.write_text(original, encoding="utf-8")
            self.reload()
            raise core.LintError("; ".join(problems))

    def try_scenario(self, text: str) -> dict[str, Any]:
        """Run this draft against `local`, without saving it. A scratch file, run, then gone.

        **The same call the command makes** — `atf run` on one scenario — against a file nothing
        else will ever see, torn down whether it passed or the write itself failed.
        """
        import uuid

        from .entry import Options, do_run

        specs = self.suite.manifest.specs
        specs.mkdir(parents=True, exist_ok=True)
        path = specs / f".try-{uuid.uuid4().hex[:8]}.feature"
        path.write_text(_wrap_as_feature(text, "a try"), encoding="utf-8")
        try:
            answer = do_run(
                Options(config=str(self.manifest_path) if self.manifest_path else None, quiet=True),
                env=self.ground.config.name,
                tag=(),
                select=str(path),
                failed=False,
                keyword="",
                tests=(),
                report=(),
                no_make=False,
                dry_run=False,
            )
            return {"code": answer.code, "lines": answer.lines}
        finally:
            path.unlink(missing_ok=True)
            self.reload(self.env)

    def lint_draft(self, text: str) -> list[str]:
        """What `atf plan` would say about this draft, without writing or running it.

        The same scratch-file-then-gone shape as `try_scenario`, but a parse and a lint pass in
        this process, not a subprocess run. The draft is parsed alone first, narrowly, exactly as a
        save does, before anything calls `reload()` on the whole suite.
        """
        import uuid

        from . import feature as feature_module
        from .feature import FeatureError

        specs = self.suite.manifest.specs
        specs.mkdir(parents=True, exist_ok=True)
        path = specs / f".lint-{uuid.uuid4().hex[:8]}.feature"
        path.write_text(_wrap_as_feature(text, "a draft"), encoding="utf-8")
        try:
            parsed = feature_module.read(path)
        except FeatureError as exc:
            path.unlink(missing_ok=True)
            return [str(exc)]
        try:
            self.reload(self.env)
            number = parsed.scenarios[-1].number
            return core.lint_file(self.suite, self.features, self.phrases, path, number)
        finally:
            path.unlink(missing_ok=True)
            self.reload(self.env)

    def unused(self) -> dict[str, list[str]]:
        """What nothing asks for. **The same call `atf explain` makes**, with the same answer."""
        from . import (
            explain as explaining,
        )

        return explaining.loose(self.suite, self.features, self.phrases)

    def activity(self) -> list[dict[str, Any]]:
        return [
            {**run.as_json(), "verdict": str(run.verdict)}
            for run in core.activity(self.root, self.ground.config.name)
        ]

    def formats(self) -> list[str]:
        """Every registered report format, which is what a completed run can be exported as."""
        from .reports import formats

        return formats()

    def export(self, id: str, format_: str) -> tuple[str, str]:
        """One run written out in a registered format, as text. The same writer `--report` uses."""
        import tempfile

        from .reports import REGISTRY, ReportError, write

        if format_ not in REGISTRY:
            raise ReportError(f"no report format called {format_!r}")
        for one in core.activity(self.root, self.ground.config.name):
            if one.id == id:
                with tempfile.TemporaryDirectory() as where:
                    destination = write(f"{format_}:{Path(where) / 'report'}", one)
                    return destination.read_text(encoding="utf-8"), format_
        raise KeyError(id)

    def environments(self) -> list[dict[str, Any]]:
        return core.environments(self.suite)

    # --- The one button ---------------------------------------------------------------------

    def make(self, name: str) -> dict[str, Any]:
        """Make one thing, and everything it stands on.

        **The same call `atf plan --apply` makes**, with the same answer.
        """
        return self.make_many([name])

    def provisionable(self, kind: str) -> list[str]:
        """Every instance of this kind that is missing and nothing stops ATF making.

        The bulk Provision button's own targets, computed fresh on every call.
        """
        return [one["name"] for one in self.instances(kind) if one["can_provision"]]

    def make_many(self, names: list[str]) -> dict[str, Any]:
        """Make everything named, and everything each of them stands on.

        **The same call `atf plan --apply` makes** — one closure-expanding pass, not one request
        per resource.
        """
        from . import (
            plan as planning,
        )

        outcomes = planning.apply(self.ground, self.suite, names)
        self.reload()
        return {
            "code": 0,
            "resources": [
                {"name": o.name, "state": str(o.state), "did": str(o.did), "why": o.why}
                for o in outcomes
            ],
        }


# --- The pages ------------------------------------------------------------------------------------


#: The environment the page being rendered is about. Every link `link()` writes carries it.
HERE: list[str] = [""]


def link(href: str, label: str, **attributes: str) -> str:
    """One link, carrying the environment. There is no link in this editor that does not."""
    extra = "".join(f" {name}={value}" for name, value in attributes.items())
    return f'<a href="{_with_env(href)}"{extra}>{html.escape(label)}</a>'


def _with_env(href: str) -> str:
    if not HERE[0]:
        return href
    return f"{href}{'&' if '?' in href else '?'}env={urllib.parse.quote(HERE[0])}"


def _json_script(id_: str, data: Any) -> str:
    """One JSON island a page's own script reads — never trusted as markup, only ever parsed."""
    dumped = json.dumps(data).replace("</", "<\\/")
    return f'<script type="application/json" id="{id_}">{dumped}</script>'


def _navlink(view: str, current: str) -> str:
    active = view == current
    extra = ' aria-current="page"' if active else ""
    classes = "navlink active" if active else "navlink"
    label = view.title()
    return f'<a class="{classes}" href="{_with_env("/" + view)}"{extra}>{html.escape(label)}</a>'


def _envpill(name: str, current: str) -> str:
    classes = "envpill active" if name == HERE[0] else "envpill"
    base = f"/{current}" if current else "/overview"
    lock = (
        f'<span class="envlock" title="{html.escape(name)} is read-only — ATF only looks, it never '
        'makes anything here">🔒</span>'
        if not ENV_MUTABLE.get(name, True)
        else ""
    )
    return (
        f'<a class="{classes}" href="{base}?env={urllib.parse.quote(name)}">{html.escape(name)}{lock}</a>'
    )


def page(title: str, body: str, current: str) -> str:
    """One page inside the fixed chrome — identical markup everywhere, a heading and a name inside.

    A page's own heading is visible where its design shows one (Overview's own `<h1>`); everywhere
    else the title is still a real, findable `<h1>` — just off-screen, since the wireframes carry no
    visible page title of their own and the chrome should not invent one they didn't ask for.
    """
    nav = "".join(_navlink(view, current) for view in NAV_VIEWS)
    envs = "".join(_envpill(one, current) for one in ENVIRONMENTS)
    heading = "" if title == "Overview" else f'<h1 class="sr-only">{html.escape(title)}</h1>'
    running = RUNNING[0]
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{html.escape(title)} · atf</title>"
        f'<link rel="stylesheet" href="/static/app.css?v={_ASSET_VERSION}">'
        "</head><body>"
        '<div class="shell">'
        '<header class="nav">'
        '<span class="word">atf</span>'
        f'<nav class="navlinks" aria-label="Views">{nav}</nav>'
        '<span class="spacer"></span>'
        '<span class="envs" aria-label="Environments">'
        f'<span class="sr-only">environment: </span>{envs}</span>'
        f'<span class="run-elapsed" id="run-elapsed"{"" if running else " hidden"}></span>'
        f'<button type="button" class="cancel-btn" id="cancel-btn" aria-label="Cancel the run"'
        f'{"" if running else " hidden"}>✕</button>'
        f'<button type="button" class="run-btn{" running" if running else ""}" id="run-btn">'
        f'<span class="spin"{"" if running else " hidden"}></span>'
        '<span class="run-btn-label">Run</span></button>'
        "</header>"
        f'<main class="page">{heading}{body}</main>'
        "</div>"
        f'<script src="/static/app.js?v={_ASSET_VERSION}" defer></script>'
        "</body></html>"
    )


#: Every environment the manifest declares, so the switcher can offer them. Set on each request.
ENVIRONMENTS: list[str] = []
#: Whether ATF may make things in each environment — `owner == "atf"` — read by `_envpill` for the
#: read-only lock icon. Populated the same way and at the same time as `ENVIRONMENTS`.
ENV_MUTABLE: dict[str, bool] = {}

#: Whether a run is going right now, so a page opened or refreshed mid-run paints that at once —
#: never the idle button inviting a second one.
RUNNING: list[bool] = [False]


#: The run vocabulary folded into the verdict words the overview speaks.
_FOLDED = {"passed": "passing", "failed": "failing", "skipped": "skipped"}


def _state_var(word: str) -> str:
    """The colour token a resource state bar segment or dot uses."""
    return "present" if word == "present" else "unreachable" if word == "unreachable" else "absent"


def _outcome_var(word: str) -> str:
    """The colour token a test outcome bar segment or dot uses."""
    return "present" if word == "passed" else "unreachable" if word == "failed" else "absent"


def _persistent_resource_counts(editor: Editor) -> dict[str, int]:
    """States, counted only over resources meant to persist (`lives="forever"`).

    A resource scoped to `lives="the test"`/`"the run"` is *absent* between runs by design — that
    is what the span means. Folding it into a headline count would report a permanent, unfixable
    "problem" that was never one; only what's supposed to still be there belongs in this number.
    """
    from . import lives as lives_module
    from . import reconcile
    from .declare import FOREVER

    instances = [node for node in editor.suite.instances.values() if lives_module.of(node) == FOREVER]
    counts: dict[str, int] = {}
    for outcome in reconcile.status(editor.ground, instances):
        counts[str(outcome.state)] = counts.get(str(outcome.state), 0) + 1
    return counts


def render_overview(editor: Editor) -> str:
    """The four things that could contradict the verdict, each one a card or a jump."""
    summary = editor.overview()
    last = summary["last_run"] or {}
    resources = _persistent_resource_counts(editor)
    total_r = sum(resources.values())
    present_r = resources.get("present", 0)
    tests = summary["tests"]
    total_t = sum(tests.values())
    passing_t = tests.get("passed", 0)
    failing_t = tests.get("failed", 0)

    banner_class = "banner ok" if summary["ready"] else "banner"
    banner = f'<div class="{banner_class}"><span class="dot"></span>{html.escape(summary["sentence"])}</div>'

    resource_seg = (
        "".join(
            f'<div class="seg" style="width:{n / total_r * 100:.0f}%;'
            f'background:var(--{_state_var(word)})"></div>'
            for word, n in resources.items()
            if n
        )
        if total_r
        else ""
    )
    resource_bits = "".join(
        f'<span class="k"><span class="sw" style="background:var(--{_state_var(word)})"></span>{n} {word}</span>'
        for word, n in resources.items()
        if word != "present" and n
    ) or '<span class="k">0 absent</span>'
    resource_card = (
        '<div class="card"><div class="label">Resources</div>'
        f'<div class="stat"><b>{present_r}</b><span>present</span></div>'
        f'<div class="segbar">{resource_seg}</div>'
        f'<div class="breakdown">{resource_bits}</div>'
        f'{link("/resources", "→ open resources", **{"class": "cardlink"})}</div>'
        if total_r
        else (
            '<div class="card"><div class="label">Resources</div>'
            '<div class="note" style="border:none;padding:0">nothing here is meant to persist — '
            "every declared resource lives for a run or a test, so absent between runs is correct</div>"
            f'{link("/resources", "→ open resources", **{"class": "cardlink"})}</div>'
        )
    )

    test_seg = (
        "".join(
            f'<div class="seg" style="width:{n / total_t * 100:.0f}%;'
            f'background:var(--{_outcome_var(word)})"></div>'
            for word, n in tests.items()
            if n
        )
        if total_t
        else ""
    )
    test_bits = "".join(
        f'<span class="k"><span class="sw" style="background:var(--{_outcome_var(word)})"></span>'
        f'{n} {_FOLDED.get(word, word)}</span>'
        for word, n in tests.items()
        if word != "passed" and n
    ) or '<span class="k">0 failing</span>'

    last_line = (
        f'{html.escape(_ago(last.get("started", "")))} · {html.escape(last.get("source", ""))}'
        if last
        else "none"
    )
    faultline = (
        '<div class="faultline">● well formed — no faults</div>'
        if summary["well_formed"]
        else f'<div class="faultline bad">● {summary["faults"]} faults</div>'
    )

    jumps = []
    if failing_t:
        word = "test" if failing_t == 1 else "tests"
        jumps.append((f"{failing_t} failing {word}", "/tests?verdict=failed", "tests"))
    jumps.append(("full lineage graph", "/graph", "graph"))
    jumps.append(("write a new test", "/composer", "new test"))
    jumps_html = "".join(
        f'<a class="jump" href="{_with_env(href)}"><span>{html.escape(text)}</span>'
        f'<span>→ {html.escape(target)}</span></a>'
        for text, href, target in jumps
    )

    body = (
        '<div class="ov-body">'
        f'<div class="eyebrow">{html.escape(editor.root.name or "atf")} · '
        f'{html.escape(editor.ground.config.name)}</div>'
        "<h1>Overview</h1>"
        f"{banner}"
        '<div class="cards">'
        f"{resource_card}"
        '<div class="card"><div class="label">Tests</div>'
        f'<div class="stat"><b>{passing_t}</b><span>passing</span></div>'
        f'<div class="segbar">{test_seg}</div>'
        f'<div class="breakdown">{test_bits}</div>'
        f'{link("/tests", "→ open tests", **{"class": "cardlink"})}</div>'
        '<div class="card"><div class="label">Last run</div>'
        f'<div class="stat"><b style="font-size:16px">{html.escape(last.get("id") or "none")}</b></div>'
        f'<div style="font-family:var(--mono);font-size:12px;color:var(--ink-soft)">{last_line}</div>'
        f'{link("/activity", "→ open activity", **{"class": "cardlink"})}</div>'
        "</div>"
        '<div class="ov-row">'
        f'<div class="panel"><h2>Suite</h2>{faultline}'
        '<div class="note">lint findings, undeclared resources and unreachable sentences '
        "show here when there are any</div></div>"
        f'<div class="panel"><h2>Jump in</h2><div class="jumps">{jumps_html}</div></div>'
        "</div></div>"
    )
    return page("Overview", body, "overview")


def _ago(stamp: str) -> str:
    """`6 minutes ago`, which is what a person reads a timestamp as."""
    from datetime import datetime

    try:
        when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return stamp or "never"
    seconds = int((datetime.now(tz=UTC) - when).total_seconds())
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            many = seconds // size
            return f"{many} {word}{'s' if many > 1 else ''} ago"
    return "just now"


def render_faults(editor: Editor) -> str:
    """What `atf check` says, which is the overview's `suite` line opened."""
    found = editor.faults()
    body = f'<div class="simple"><p>{link("/overview", "← Overview")}</p>'
    if not found:
        body += "<p>no faults</p></div>"
    else:
        rows = "".join(
            f"<tr><td>{html.escape(one['where'])}</td><td>{html.escape(one['why'])}</td>"
            f"<td>{html.escape(one['check'])}</td></tr>"
            for one in found
        )
        body += f"<table><tr><th>where<th>why<th>check</tr>{rows}</table></div>"
    return page("Faults", body, "overview")


#: Who is responsible for one of these existing. `atf` is the common case and says nothing.
_OWNERS = {"atf": "", "them": "the environment owns it — ATF only looks"}


def _owner(owner: str) -> str:
    return _OWNERS.get(owner, owner)


def render_resources(editor: Editor, kind: str = "") -> str:
    """One left rail of kinds; the chosen kind's instances, each one expanding in place."""
    summary = editor.resources()
    if not summary:
        return page("Resources", '<div class="main"><p class="simple">nothing declared</p></div>', "resources")
    if kind and not any(one["kind"] == kind for one in summary):
        raise KeyError(kind)
    chosen = kind or summary[0]["kind"]
    found = next(one for one in summary if one["kind"] == chosen)

    rail = "".join(
        f'<a class="railitem{" active" if one["kind"] == chosen else ""}" '
        f'href="{_with_env("/resources/" + one["kind"])}">'
        f'<span>{html.escape(one["kind"])}</span><span>{one["declared"]}</span></a>'
        for one in summary
    )
    owner_bit = _owner(found["owner"])
    listhead = (
        f'<div class="listhead">{html.escape(chosen)} · {html.escape(found["system"])}'
        f'{" · " + html.escape(owner_bit) if owner_bit else ""}</div>'
    )
    rows = editor.instances(chosen)
    provisionable = [one["name"] for one in rows if one["can_provision"]]
    bulk_provision = (
        f'<form method="post" action="{_with_env("/resources/" + chosen + "/provision")}">'
        f'<button type="submit" class="btn">Provision {len(provisionable)}</button></form>'
        if provisionable
        else ""
    )
    listhead_row = f'<div class="listhead-row">{listhead}{bulk_provision}</div>'
    items = "".join(_resource_row(editor, one) for one in rows)
    undeclared = (
        '<div class="undeclared" id="undeclared-panel">'
        f'<button type="button" class="linklike" id="check-undeclared" data-kind="{html.escape(chosen, quote=True)}">'
        "↺ Check what's out there but not declared</button>"
        '<div id="undeclared-result"></div>'
        "</div>"
    )
    body = (
        '<div class="main">'
        f'<nav class="rail" aria-label="Kinds">{rail}</nav>'
        f'<div class="list">{listhead_row}{items or "<p>nothing declared</p>"}{undeclared}</div>'
        "</div>"
    )
    return page("Resources", body, "resources")


def _none_chip() -> str:
    return '<span class="v" style="color:var(--ink-dim)">none</span>'


def _resource_row(editor: Editor, one: dict[str, Any]) -> str:
    drifted = one["state"] == "present" and bool(one["changes"])
    pillclass = "drifted" if drifted else one["state"]
    keytext = ", ".join(f"{k}={v}" for k, v in one["recognised_by"].items()) or "—"
    scoped = ""
    if one["can_provision"]:
        size = one["closure_size"]
        noun = "dependency" if size == 1 else "dependencies"
        label = f"Provision + {size} {noun}" if size else "Provision"
        # A plain <button>, not a <form> — a <summary>'s content model is phrasing content, and a
        # <form> here is not; the click is handled in JS (`initProvision`), with the no-JS fallback
        # already sitting in the detail panel below (`_resource_detail`'s own "▶ make" form).
        scoped = (
            f'<button type="button" class="provision-btn" '
            f'data-make="{html.escape(one["name"], quote=True)}">{html.escape(label)}</button>'
        )
    return (
        f'<details class="item"><summary class="itemrow" role="button">'
        f'<span class="itemname">{html.escape(one["name"])}</span>'
        f'<span class="pill {pillclass}">{html.escape(pillclass)}</span>'
        f'<span class="itemkey">{html.escape(keytext)}</span>'
        f"{scoped}"
        '<span class="chev">▾</span></summary>'
        f'<div class="rdetail">{_resource_detail(editor, one["name"])}</div></details>'
    )


#: A value shown at a glance, not a wall of text. Past this, only its size is worth saying —
#: `files` on a `Tree`, say, can carry a whole suite's source as one field's value.
_VALUE_LIMIT = 140


def _display_value(value: Any) -> str:
    if isinstance(value, dict):
        return f"{{…}} ({len(value)} key{'s' if len(value) != 1 else ''})"
    if isinstance(value, list):
        return f"[…] ({len(value)} item{'s' if len(value) != 1 else ''})"
    text = str(value)
    return text if len(text) <= _VALUE_LIMIT else f"{text[:_VALUE_LIMIT]}… ({len(text)} chars)"


def _resource_detail(editor: Editor, name: str) -> str:
    one = editor.resource(name)
    field_chips = "".join(
        f'<span class="chip">{html.escape(k)} → {html.escape(v)}</span>'
        for k, v in one["declaration"]["fields"].items()
    ) or _none_chip()
    need_chips = "".join(
        f'<span class="chip">{html.escape(k)} ← {html.escape(v)}</span>'
        for k, v in one["declaration"]["needs"].items()
    ) or _none_chip()
    key = ", ".join(one["recognised_by"]) or "—"
    parts = [
        f'<div class="field"><div class="k">key</div><div class="v">{html.escape(key)}</div></div>',
        f'<div class="field"><div class="k">fields</div><div class="chips">{field_chips}</div></div>',
        f'<div class="field"><div class="k">needs</div><div class="chips">{need_chips}</div></div>',
    ]
    if one["would_change"]:
        rows = "".join(
            f"<tr><td>{html.escape(field)}</td>"
            f"<td>{html.escape(_display_value(sides['found']))} → "
            f"{html.escape(_display_value(sides['declared']))}</td></tr>"
            for field, sides in one["would_change"].items()
        )
        parts.append(f'<div class="field"><div class="k">would change</div><table>{rows}</table></div>')
    parts.append(_lineage_html(editor, name))
    parts.append('<div class="detailspacer"></div>')
    if one["state"] == "present":
        action = (
            f'<a class="runfor" href="{_with_env("/tests?resource=" + urllib.parse.quote(name, safe=""))}">'
            f"▶ run tests using {html.escape(name)}</a>"
        )
    elif one["can_make"]:
        action = (
            f'<form method="post" action="{_with_env("/make/" + urllib.parse.quote(name, safe=""))}">'
            '<button type="submit" class="runfor" style="border:none;cursor:pointer">'
            f"▶ make {html.escape(name)}</button></form>"
        )
    else:
        action = f'<span class="v" style="color:var(--ink-dim)">cannot make — {html.escape(one["why_not"])}</span>'
    parts.append(f'<div class="detailactions">{action}</div>')
    return "".join(parts)


def _lineage_html(editor: Editor, name: str) -> str:
    """A compact dependency diagram for one resource, scoped to its immediate neighbours.

    The sentence always comes first — `core.in_words`' own docstring calls it "what the view
    prefers before it draws" — and the diagram, when there is a shape to see, is a small, honest
    one: not the whole spine (that is the Graph page's job), and resources only, since a live
    status dot on a test or a phrase would be a fact this view does not have.
    """
    here = editor.node(name)
    needs = [n for n in here["needs"] if n["kind"] == "resource"]
    needed_by = [n for n in here["needed_by"] if n["kind"] == "resource"]
    sentence = f'<p class="lineage-sentence">{html.escape(here["sentence"])}</p>' if here["sentence"] else ""
    if not needs and not needed_by:
        return f'<div class="lineage">{sentence}</div>'

    def status_of(node_id: str) -> str:
        state, _ = editor.ground.find(editor.suite.resource(node_id))
        return str(state)

    row_h = 46
    rows = max(len(needs), 1, len(needed_by))
    height = rows * row_h + 16

    def column(items: list[dict[str, Any]], x: int) -> str:
        top = (height - len(items) * row_h) / 2
        boxes = []
        for i, item in enumerate(items):
            flag = "present" if status_of(item["id"]) == "present" else "absent"
            boxes.append(
                f'<a class="gnode" style="left:{x}px;top:{top + i * row_h:.0f}px" '
                f'href="{_with_env("/graph/" + urllib.parse.quote(item["id"], safe=""))}">'
                f'<span class="flag {flag}"></span>{html.escape(item["label"])}</a>'
            )
        return "".join(boxes)

    focus_top = (height - row_h) / 2
    focus = (
        f'<div class="gnode focus" style="left:255px;top:{focus_top:.0f}px">'
        f'<span class="flag {"present" if status_of(name) == "present" else "absent"}"></span>'
        f"{html.escape(name)}</div>"
    )
    return (
        f'<div class="lineage">{sentence}'
        f'<div class="lineage-canvas" style="height:{height}px">'
        f"{column(needs, 10)}{focus}{column(needed_by, 500)}"
        "</div></div>"
    )


def _graph_nodes(editor: Editor) -> list[dict[str, Any]]:
    """Every declared resource, for the canvas: its lineage edges, current state, kind and lives."""
    from . import lives as lives_module
    from .declare import declaration_of

    spine_by_id = {one["id"]: one for one in editor.graph() if one["kind"] == "resource"}
    out: list[dict[str, Any]] = []
    for name, spine_node in spine_by_id.items():
        resource = editor.suite.resource(name)
        state, _ = editor.ground.find(resource)
        out.append(
            {
                "id": name,
                "label": name,
                "kind": declaration_of(resource).kind,
                "needs": [n for n in spine_node["needs"] if n in spine_by_id],
                "state": str(state),
                "lives": lives_module.of(resource),
            }
        )
    return out


def _graph_legend() -> str:
    states = (("present", "present"), ("absent", "absent"), ("drifted", "drifted"), ("unreachable", "unreachable"))
    spans = (("forever", "forever"), ("run", "the run"), ("test", "the test"))
    state_rows = "".join(
        f'<div class="legrow"><span class="legdot" style="background:var(--{var})"></span>{html.escape(label)}</div>'
        for var, label in states
    )
    span_rows = "".join(
        f'<div class="legrow"><span class="legdot" style="background:var(--{var})"></span>{html.escape(label)}</div>'
        for var, label in spans
    )
    return (
        '<div class="legend"><h3>State</h3><div class="legrows">'
        f"{state_rows}</div>"
        '<h3 style="margin-top:4px">Lives</h3><div class="legrows">'
        f"{span_rows}</div></div>"
    )


def _graph_nodelist_html(nodes: list[dict[str, Any]]) -> str:
    foot = f'<p style="padding:10px 4px 0"><small>{link("/unused", "what nothing asks for")}</small></p>'
    if not nodes:
        return '<p style="padding:0 20px;color:var(--ink-soft)">nothing declared</p>' + foot
    items = "".join(
        f'<li>{link("/graph/" + urllib.parse.quote(one["id"], safe=""), one["label"])}</li>' for one in nodes
    )
    return f'<ul class="nodelist">{items}</ul>{foot}'


def _graph_detail_html(here: dict[str, Any]) -> str:
    def chips(nodes: list[dict[str, Any]]) -> str:
        if not nodes:
            return _none_chip()
        return "".join(
            f'<a class="chip" href="{_with_env("/graph/" + urllib.parse.quote(n["id"], safe=""))}">'
            f'{html.escape(n["label"])}</a>'
            for n in nodes
        )

    action = ""
    if here["kind"] == "resource":
        action = (
            f'<a class="runfor" href="{_with_env("/tests?resource=" + urllib.parse.quote(here["id"], safe=""))}">'
            f"▶ run tests using {html.escape(here['id'])}</a>"
        )
    return (
        f'<div class="drawerhead"><div class="drawertitle">{html.escape(here["label"])}</div></div>'
        f'<div class="drawersub">{html.escape(here["kind"])}'
        f'{" · " + html.escape(here["sentence"]) if here["sentence"] else ""}</div>'
        f'<div class="field"><div class="k">needs</div><div class="chips">{chips(here["needs"])}</div></div>'
        '<div class="field"><div class="k">what breaks if this does</div>'
        f'<div class="chips">{chips(here["needed_by"])}</div></div>'
        f"{action}"
    )


def render_graph(editor: Editor, selected: str = "") -> str:
    """Every declared resource on one canvas; a node's own lineage in the sidebar once picked.

    `KeyError` where `selected` names no such node — that reaches the route, not this function.
    """
    canvas_nodes = _graph_nodes(editor)
    if selected:
        here = editor.node(selected)
        sidebody = _graph_detail_html(here)
    else:
        sidebody = _graph_nodelist_html(canvas_nodes)
    body = (
        '<div class="main">'
        f'<aside class="left">{_graph_legend()}<div class="gdetail" id="graph-sidebody">{sidebody}</div></aside>'
        '<div class="canvas">'
        f'<div id="cy" data-selected="{html.escape(selected, quote=True)}"></div>'
        '<div class="hint">scroll to pan · pinch to zoom · click a node to inspect</div>'
        '<div class="zoomctl">'
        '<button id="zoom-out" type="button" aria-label="Zoom out">−</button>'
        '<button id="zoom-fit" type="button" aria-label="Fit to screen">⛶</button>'
        '<button id="zoom-in" type="button" aria-label="Zoom in">+</button>'
        "</div></div></div>"
        f'{_json_script("graph-data", canvas_nodes)}'
        f'<script src="/static/vendor/cytoscape.min.js?v={_ASSET_VERSION}"></script>'
        f'<script src="/static/graph.js?v={_ASSET_VERSION}" defer></script>'
    )
    return page("The graph", body, "graph")


def render_unused(editor: Editor) -> str:
    """The graph's second entry point: what nothing asks for."""
    found = editor.unused()
    blocks = ""
    for what in ("resources", "phrases", "steps"):
        loose = found.get(what, [])
        items = "".join(f"<li>{html.escape(one)}</li>" for one in loose)
        blocks += f"<h2>{what}</h2>" + (f"<ul>{items}</ul>" if loose else "<p>nothing</p>")
    body = f'<div class="simple"><p>{link("/graph", "The graph")}</p>{blocks}</div>'
    return page("What nothing asks for", body, "graph")


def _grouped_rows(shown: list[dict[str, Any]], selected: str) -> str:
    """The sidebar list, one group per file — a test is listed under what opening it opens."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for one in shown:
        groups.setdefault(one["id"].rsplit("::", 1)[0], []).append(one)
    parts = []
    for file_key in sorted(groups, key=lambda k: Path(k).name):
        rows = groups[file_key]
        label = Path(file_key).name if file_key else "—"
        parts.append(
            '<div class="filegroup">'
            f'<a class="filegroup-label" href="{_with_env("/tests/" + urllib.parse.quote(rows[0]["id"], safe=""))}">'
            f"{html.escape(label)}</a>"
            f'{"".join(_test_row(one, selected) for one in rows)}'
            "</div>"
        )
    return "".join(parts)


def _test_row(one: dict[str, Any], selected: str) -> str:
    """One row in the sidebar list: a state dot, the title, its tags — one line, like every list here."""
    dotclass = "ok" if one["verdict"] == "passed" else "fail" if one["verdict"] == "failed" else "skip"
    needle = (one["label"] + " " + one["description"] + " " + one["form"] + " " + " ".join(one["tags"])).lower()
    tag_chips = f'<span class="rtag form">{html.escape(one["form"])}</span>' + "".join(
        f'<span class="rtag">{html.escape(t)}</span>' for t in one["tags"]
    )
    return (
        f'<a class="trow{" selected" if one["id"] == selected else ""}" '
        f'href="{_with_env("/tests/" + urllib.parse.quote(one["id"], safe=""))}" '
        f'data-id="{html.escape(one["id"], quote=True)}" data-search="{html.escape(needle, quote=True)}">'
        f'<span class="tdot {dotclass}"></span>'
        '<span class="trow-body">'
        f'<span class="trow-title">{html.escape(one["label"])}</span>'
        + (f'<span class="rtags">{tag_chips}</span>' if tag_chips else "")
        + "</span></a>"
    )


_STRING_RE = re.compile(r'"[^"]*"')
_KEYWORDS = ("given", "when", "then", "and", "but")


def _highlight_words(chunk: str, kind_words: set[str]) -> str:
    return "".join(
        f'<span class="tok-kind">{html.escape(word)}</span>' if word.strip() in kind_words else html.escape(word)
        for word in re.split(r"(\s+)", chunk)
    )


def _highlight_line(text: str, kind_words: set[str]) -> str:
    """Colour one sentence: known kinds, and quoted values."""
    parts, last = [], 0
    for m in _STRING_RE.finditer(text):
        parts.append(_highlight_words(text[last : m.start()], kind_words))
        parts.append(f'<span class="tok-str">{html.escape(m.group(0))}</span>')
        last = m.end()
    parts.append(_highlight_words(text[last:], kind_words))
    return "".join(parts)


def _render_backdrop(text: str, kind_words: set[str]) -> str:
    """The editor's coloured layer, line for line.

    Leading space kept exact, or it drifts off the real (invisible) text sitting on top of it.
    """
    rendered = []
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent = line[: len(line) - len(stripped)]
        word, sep, rest = stripped.partition(" ")
        if sep and word.lower() in _KEYWORDS:
            body = f'<span class="tok-kw">{html.escape(word)}</span> {_highlight_line(rest, kind_words)}'
        else:
            body = _highlight_line(stripped, kind_words)
        rendered.append(indent + body)
    return "\n".join(rendered)


def _phrase_candidates(editor: Editor) -> list[dict[str, str]]:
    """Every sentence ATF might offer — for completion while typing, not narrowed to what's above.

    A suite's own scaffolding (`core.offers`) only answers *after* something is arranged; typing in
    a free-text editor has no such context to read, so this is the flat, suite-wide vocabulary
    instead — every declared resource, every kind resolution can build, every registered step.
    """
    from .declare import declaration_of
    from .loader import fixture_name

    out = []
    for name, node in editor.suite.instances.items():
        kind = fixture_name(declaration_of(node).kind)
        out.append({"keyword": "Given", "text": f'the {kind} "{name}"', "why": "declared by this suite"})
    for kind in kinds.offered():
        out.append({"keyword": "Given", "text": f"a {kind}", "why": "resolution can build one"})
    for keyword, patterns in core.sayable().items():
        for pattern in patterns:
            out.append({"keyword": keyword.title(), "text": pattern, "why": "a sentence ATF knows"})
    return out


def _editor_empty() -> str:
    return (
        '<div class="editorpane"><div class="editor-empty">'
        f'<p>Pick a test on the left, or {link("/tests?new=1", "create one")}.</p></div></div>'
    )


def _editor_python(found: dict[str, Any]) -> str:
    body = (
        '<div class="editor-empty">'
        f"{html.escape(found['label'])} is written in Python — there is no Gherkin source to open here. "
        f"{link('/tests/' + urllib.parse.quote(found['id'], safe=''), 'Run it')} still works."
        "</div>"
    )
    return f'<div class="editorpane">{body}</div>'


def _editor_existing(found: dict[str, Any], source: dict[str, Any]) -> str:
    """The real editor, opened on this test's whole file, scrolled to the scenario clicked."""
    name = Path(source["path"]).name
    text = source["text"]
    kind_words = set(kinds.offered())
    lines = text.split("\n")
    selected_number = source["number"]
    selected_end = source["end"]

    # The failing step is searched for only within the selected scenario's own lines — the same
    # step text can appear in more than one scenario in a file this size.
    failed_at = (found["last"] or {}).get("failed_at") if found["last"] else None
    failed_line = 0
    if failed_at and failed_at.get("step"):
        for i in range(selected_number, selected_end + 1):
            if i <= len(lines) and lines[i - 1].strip().endswith(failed_at["step"]):
                failed_line = i
                break
    highlight = (
        f'<div class="line-highlight" style="top:calc(14px + {failed_line - 1} * 1.9em)"></div>'
        if failed_line
        else ""
    )  # nested inside .editor-backdrop below (not as its sibling), so it scrolls with the text it marks
    fail_note = (
        f'<div class="fail-note">line {failed_line}: {html.escape(failed_at.get("message", ""))}</div>'
        if failed_line and failed_at and failed_at.get("message")
        else ""
    )
    arranges = ""
    if found["arranges"]:
        links = ", ".join(
            f'<a href="{_with_env("/resources/" + found["kinds"].get(one, ""))}">{html.escape(one)}</a>'
            for one in found["arranges"]
        )
        arranges = f'<span class="filebar-sep">·</span><span>arranges: {links}</span>'

    gutter = "\n".join(str(i) for i in range(1, len(lines) + 1))
    backdrop = _render_backdrop(text, kind_words)
    status = html.escape(found["last"]["outcome"] if found["last"] else "never run")

    body = (
        '<div class="editorpane">'
        f'<div class="filebar"><b>{html.escape(name)}</b> · editing {html.escape(found["id"])}{arranges}</div>'
        f"{fail_note}"
        '<div class="editor-surface">'
        f'<div class="editor-gutter" id="editor-gutter">{gutter}</div>'
        '<div class="editor-stack">'
        f'<div class="editor-backdrop" id="editor-backdrop" aria-hidden="true">{highlight}{backdrop}</div>'
        '<textarea class="editor-input" id="editor-input" spellcheck="false" autocapitalize="off" '
        f'aria-label="scenario text" data-mode="edit" data-test-id="{html.escape(found["id"], quote=True)}" '
        f'data-scroll-to-line="{selected_number}">{html.escape(text)}</textarea>'
        '<div class="suggest" id="suggest" role="listbox" hidden></div>'
        "</div></div>"
        '<div class="actionbar">'
        f'<span class="status" id="editor-status">{status}</span>'
        '<button type="button" class="btn ghost" id="run-scenario-btn" '
        f'data-test-id="{html.escape(found["id"], quote=True)}">▶ Run this scenario</button>'
        '<button type="button" class="btn ghost" id="try-btn">▶ Try it</button>'
        '<button type="button" class="btn" id="save-btn">Save</button>'
        "</div></div>"
    )
    return body


def _editor_new(editor: Editor) -> str:
    """The same editor, blank — writing a new test is the same surface as opening one."""
    specs = editor.suite.manifest.specs
    existing = sorted(p.name for p in specs.glob("*.feature")) if specs.is_dir() else []
    datalist = "".join(f"<option value={html.escape(name, quote=True)}>" for name in existing)
    text = "Scenario: a scenario\n    Given \n"
    kind_words = set(kinds.offered())
    lines = text.split("\n")
    gutter = "\n".join(str(i) for i in range(1, len(lines) + 1))
    backdrop = _render_backdrop(text, kind_words)
    body = (
        '<div class="editorpane">'
        '<div class="filebar"><input class="filename-input" id="filename-input" list="composer-files" '
        'value="composed.feature" aria-label="Feature file"> · new test'
        f'<datalist id="composer-files">{datalist}</datalist></div>'
        '<div class="editor-surface">'
        f'<div class="editor-gutter" id="editor-gutter">{gutter}</div>'
        '<div class="editor-stack">'
        f'<div class="editor-backdrop" id="editor-backdrop" aria-hidden="true">{backdrop}</div>'
        '<textarea class="editor-input" id="editor-input" spellcheck="false" autocapitalize="off" '
        f'aria-label="scenario text" data-mode="new">{html.escape(text)}</textarea>'
        '<div class="suggest" id="suggest" role="listbox" hidden></div>'
        "</div></div>"
        '<div class="actionbar">'
        '<span class="status" id="editor-status"></span>'
        '<button type="button" class="btn ghost" id="try-btn">▶ Try it</button>'
        '<button type="button" class="btn" id="save-btn">Save</button>'
        "</div></div>"
    )
    return body


def render_tests(
    editor: Editor,
    verdict: str = "",
    tag: str = "",
    resource: str = "",
    q: str = "",
    selected: str = "",
    new: bool = False,
) -> str:
    """A filterable list on the left; the real editor for whatever's selected, on the right.

    Opening a test and writing one are the same pane — a picker never stood between somebody and
    the Gherkin, and now neither does a form.
    """
    listed = editor.tests()
    shown = [
        one
        for one in listed
        if (not verdict or one["verdict"] == verdict)
        and (not tag or tag in one["tags"])
        and (not resource or resource in one["arranges"])
        and (not q or q.lower() in (one["label"] + " " + one["description"] + " " + one["id"]).lower())
    ]
    rows = _grouped_rows(shown, selected)

    if new:
        pane = _editor_new(editor)
    elif not selected:
        pane = _editor_empty()
    else:
        found = editor.test_state(selected)
        pane = _editor_python(found) if not found["path"] else _editor_existing(found, editor.test_source(selected))

    resource_field = (
        f'<input type="hidden" name="resource" value="{html.escape(resource, quote=True)}">' if resource else ""
    )
    scope = (
        f'<p class="rowdesc" style="padding:8px 10px 0">scoped to resource "{html.escape(resource)}" · '
        f'{link("/tests", "clear")}</p>'
        if resource
        else ""
    )
    empty_note = '<p class="rowdesc" style="padding:8px">no tests match</p>'
    body = (
        '<div class="main">'
        '<nav class="sidebar" aria-label="Tests">'
        f'<div class="searchrow"><form class="searchform" method="get" action="{_with_env("/tests")}">'
        f'{resource_field}<input class="search" id="test-search" type="search" name="q" '
        f'value="{html.escape(q, quote=True)}" placeholder="search tests…" aria-label="Search tests"></form>'
        f'{link("/tests?new=1", "+ Create test", **{"class": "btn"})}'
        "</div>"
        f"{scope}"
        f'<div class="testlist">{rows or empty_note}</div>'
        "</nav>"
        f"{pane}"
        "</div>"
        f'{_json_script("kind-words", sorted(kinds.offered()))}'
        f'{_json_script("phrase-list", _phrase_candidates(editor))}'
    )
    return page("Tests", body, "tests")


_RUN_DOT = {"passing": "present", "failing": "unreachable"}


def _run_row(run: dict[str, Any], selected: bool) -> str:
    dotvar = _RUN_DOT.get(str(run["verdict"]), "absent")
    outcomes = run["outcomes"]
    ok = sum(1 for one in outcomes if one["outcome"] == "passed")
    return (
        f'<a class="run{" selected" if selected else ""}" href="{_with_env("/activity/" + run["id"])}">'
        f'<span class="rundot" style="background:var(--{dotvar})"></span>'
        '<span class="runmeta">'
        f'<span class="runid">{html.escape(run["id"])}</span>'
        f'<span class="runwhen">{html.escape(_ago(run["started"]))} · {html.escape(run["source"])} · '
        f"{ok}/{len(outcomes)}</span></span></a>"
    )


def _run_detail(editor: Editor, run: dict[str, Any]) -> str:
    outcomes = run["outcomes"]
    failed = sum(1 for one in outcomes if one["outcome"] == "failed")
    passed = sum(1 for one in outcomes if one["outcome"] == "passed")
    skipped = len(outcomes) - failed - passed
    rows = ""
    for one in outcomes:
        icon = {"passed": ("ic-ok", "✓"), "failed": ("ic-fail", "✗")}.get(one["outcome"], ("", "·"))
        rows += (
            f'<tr><td class="{icon[0]}">{icon[1]}</td><td>{html.escape(one["test"])}</td>'
            f'<td>{one["duration_ms"] / 1000:.1f}s</td></tr>'
        )
        if one.get("failed_at"):
            rows += (
                '<tr><td></td><td colspan="2"><pre style="white-space:pre-wrap">'
                f'{html.escape(one["failed_at"].get("message", ""))}</pre></td></tr>'
            )
    reports = " ".join(link(f"/activity/{run['id']}/report/{one}", one) for one in sorted(editor.formats()))
    sub_class = "dsub failing" if failed else "dsub"
    return (
        '<div class="detail">'
        f'<div class="dhead"><span class="id">{html.escape(run["id"])}</span>'
        f'<span class="env">{html.escape(run["environment"])}</span></div>'
        f'<div class="{sub_class}">{passed} passed · {failed} failed · {skipped} skipped</div>'
        f"<table>{rows}</table>"
        f"<h2>export</h2><p>{reports or 'none registered'}</p>"
        "</div>"
    )


def render_activity(editor: Editor, selected: str = "") -> str:
    """Every run of this environment, newest first; opening one shows its outcomes item by item."""
    listed = editor.activity()
    if not listed:
        return page("Activity", '<div class="main"><p class="simple">no runs recorded</p></div>', "activity")
    if selected and not any(one["id"] == selected for one in listed):
        raise KeyError(selected)
    chosen = selected or listed[0]["id"]
    rows = "".join(_run_row(one, one["id"] == chosen) for one in listed)
    found = next(one for one in listed if one["id"] == chosen)
    body = f'<div class="main"><nav class="timeline" aria-label="Runs">{rows}</nav>{_run_detail(editor, found)}</div>'
    return page("Activity", body, "activity")


def render_sentences(editor: Editor) -> str:
    """Every sentence this suite can say, grouped by what brought it.

    Generated from the registrations and from the suite's own phrases, so the page a team reads is
    their vocabulary and not ATF's plus a note about extending.
    """
    from . import kinds as kind_registry
    from . import steps as registry

    blocks = f'<p>{link("/overview", "← Overview")}</p>'
    for module in sorted({one.module for one in registry.REGISTRY}):
        rows = "".join(
            f"<tr><td><code>{html.escape(one.keyword.title())} {html.escape(one.pattern)}</code></td>"
            f"<td>{html.escape(_summary(one))}</td></tr>"
            for one in sorted(
                (one for one in registry.REGISTRY if one.module == module),
                key=lambda one: (one.keyword, one.pattern),
            )
        )
        blocks += f"<h2>{html.escape(_brought_by(module))}</h2><table>{rows}</table>"

    if editor.phrases:
        rows = "".join(
            f"<tr><td><code>{html.escape(pattern)}</code></td>"
            f"<td><small>{html.escape(str(one.where))}</small></td></tr>"
            for pattern, one in sorted(editor.phrases.items())
        )
        blocks += f"<h2>This suite's phrases</h2><table>{rows}</table>"

    blocks += (
        "<h2>Kinds</h2><p>"
        + " ".join(f"<code>{html.escape(one)}</code>" for one in kind_registry.offered())
        + "</p>"
    )
    return page("Sentences", f'<div class="simple">{blocks}</div>', "")


def _summary(step: Any) -> str:
    """The first line of a step's docstring, which is what it does."""
    said = (step.function.__doc__ or "").strip().splitlines()
    return said[0] if said else ""


def _brought_by(module: str) -> str:
    """Which system a word came from, said the way somebody looking for it would say it."""
    if module == "atf.vocabulary":
        return "Things"
    if module.startswith("atf.systems."):
        return f"The {module.rsplit('.', 1)[1]} system"
    if module.startswith("atf."):
        return module.rsplit(".", 1)[1].replace("_", " ").title()
    return f"{module} — this suite's own"


def render_environments(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(one['name'])}</td>"
        f"<td>{'may be changed' if one['mutable'] else 'read only'}</td>"
        f"<td>{html.escape(', '.join(one['systems']))}</td></tr>"
        for one in editor.environments()
    )
    body = f'<div class="simple"><p>{link("/overview", "← Overview")}</p><table>{rows}</table></div>'
    return page("Environments", body, "")


RENDERERS = {
    "overview": render_overview,
    "resources": render_resources,
    "graph": render_graph,
    "sentences": render_sentences,
    "activity": render_activity,
    "environments": render_environments,
}


def answering(editor: Editor, env: str = "") -> Editor:
    """Re-read for the environment this request names, and tell the page which one that is."""
    editor.reload(env)
    HERE[0] = editor.ground.config.name
    ENVIRONMENTS[:] = sorted(editor.suite.manifest.environments)
    ENV_MUTABLE.clear()
    ENV_MUTABLE.update({name: env.mutable for name, env in editor.suite.manifest.environments.items()})
    RUNNING[0] = editor.run_tracker.running
    return editor


def _query_default() -> Any:
    """A repeatable query param's empty default, built once: a call in a default argument is a lint error."""
    from fastapi import Query

    return Query(default=[])


_TESTS = _query_default()


def build_app(editor: Editor) -> Any:
    """A FastAPI app over the editor. Every route is one call into `core`, through `Editor`."""
    from fastapi import FastAPI
    from fastapi.responses import (
        HTMLResponse,
        JSONResponse,
        PlainTextResponse,
        RedirectResponse,
    )
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="atf edit", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def _root(env: str = "") -> Any:
        return HTMLResponse(render_overview(answering(editor, env)))

    @app.get("/tests", response_class=HTMLResponse)
    def _tests(
        env: str = "", verdict: str = "", tag: str = "", resource: str = "", q: str = "", new: bool = False
    ) -> Any:
        return HTMLResponse(render_tests(answering(editor, env), verdict, tag, resource, q, new=new))

    @app.get("/tests/{id:path}", response_class=HTMLResponse)
    def _test(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            editor.test(id)
        except KeyError:
            return HTMLResponse(page("Not found", f"<p>no test {html.escape(id)}</p>", "tests"), status_code=404)
        return HTMLResponse(render_tests(editor, selected=id))

    @app.get("/resources", response_class=HTMLResponse)
    def _resources(env: str = "") -> Any:
        return HTMLResponse(render_resources(answering(editor, env)))

    @app.get("/resources/{kind}", response_class=HTMLResponse)
    def _resources_kind(kind: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_resources(editor, kind))
        except KeyError as exc:
            return HTMLResponse(page("Not found", f"<p>{html.escape(str(exc))}</p>", "resources"), status_code=404)

    for view, render in RENDERERS.items():
        if view in ("resources", "graph", "activity"):
            continue

        def _view(env: str = "", render: Any = render) -> Any:
            return HTMLResponse(render(answering(editor, env)))

        app.get(f"/{view}", response_class=HTMLResponse)(_view)

    @app.get("/graph", response_class=HTMLResponse)
    def _graph(env: str = "") -> Any:
        return HTMLResponse(render_graph(answering(editor, env)))

    @app.get("/activity", response_class=HTMLResponse)
    def _activity(env: str = "") -> Any:
        return HTMLResponse(render_activity(answering(editor, env)))

    @app.get("/activity/{id}", response_class=HTMLResponse)
    def _run(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_activity(editor, selected=id))
        except KeyError:
            return HTMLResponse(page("Not found", f"<p>no run {html.escape(id)}</p>", "activity"), status_code=404)

    @app.get("/activity/{id}/report/{format_}")
    def _export(id: str, format_: str, env: str = "") -> Any:
        """A completed run in a registered format, written by `--report`'s own writer."""
        answering(editor, env)
        try:
            body, name = editor.export(id, format_)
        except Exception as exc:  # noqa: BLE001 - an unknown format or run is an answer, not a crash
            return JSONResponse({"error": str(exc)}, status_code=404)
        return PlainTextResponse(body, headers={"content-disposition": f'attachment; filename="{id}.{name}"'})

    @app.get("/faults", response_class=HTMLResponse)
    def _faults(env: str = "") -> Any:
        return HTMLResponse(render_faults(answering(editor, env)))

    @app.get("/unused", response_class=HTMLResponse)
    def _unused(env: str = "") -> Any:
        answering(editor, env)
        return HTMLResponse(render_unused(editor))

    @app.get("/graph/{id:path}", response_class=HTMLResponse)
    def _node(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_graph(editor, selected=id))
        except KeyError:
            return HTMLResponse(page("Not found", f"<p>no node {html.escape(id)}</p>", "graph"), status_code=404)

    @app.get("/api/graph/{id:path}")
    def _node_json(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return JSONResponse(editor.node(id))
        except KeyError:
            return JSONResponse({"error": f"no node {id}"}, status_code=404)

    @app.get("/api/unused")
    def _unused_json(env: str = "") -> Any:
        answering(editor, env)
        return JSONResponse(editor.unused())

    @app.post("/make/{name}")
    def _make_button(name: str, env: str = "") -> Any:
        """The Make button. **The same call the command makes** — there is no privileged path."""
        answering(editor, env)
        editor.make(name)
        where = f"/resources/{editor.resource(name)['kind']}"
        return RedirectResponse(_with_env(where), status_code=303)

    @app.post("/resources/{kind}/provision")
    def _provision_kind(kind: str, env: str = "") -> Any:
        """The bulk Provision button: every missing, makeable instance of one kind, closure and all.

        Targets are recomputed here, never trusted from the form.
        """
        answering(editor, env)
        try:
            targets = editor.provisionable(kind)
        except KeyError:
            body = f"<p>no resource kind {html.escape(kind)}</p>"
            return HTMLResponse(page("Not found", body, "resources"), status_code=404)
        if targets:
            editor.make_many(targets)
        return RedirectResponse(_with_env(f"/resources/{kind}"), status_code=303)

    @app.post("/run/{id:path}")
    def _run_button(id: str, env: str = "") -> Any:
        """The no-JS fallback for one test's Run button.

        Starts the same background run, then returns to the test with it already going — **the
        same call the command makes**.
        """
        answering(editor, env)
        editor.run((editor.test(id)["id"],))
        return RedirectResponse(_with_env(f"/tests/{urllib.parse.quote(id, safe='')}"), status_code=303)

    @app.post("/api/run")
    def _run_start(env: str = "", test: list[str] = _TESTS) -> Any:
        """The fixed chrome's Run button, and one test's — **the same call the command makes**.

        Starts in the background and answers at once. `/api/run/status` is where its progress goes.
        """
        answering(editor, env)
        started = editor.run(tuple(test))
        return JSONResponse({"started": started, "running": True})

    @app.get("/api/run/status")
    def _run_status(env: str = "") -> Any:
        answering(editor, env)
        return JSONResponse(editor.run_status())

    @app.post("/api/run/cancel")
    def _run_cancel(env: str = "") -> Any:
        """Interrupt the run in progress — the same signal Ctrl-C sends it at a terminal."""
        answering(editor, env)
        return JSONResponse({"cancelled": editor.cancel_run()})

    @app.get("/api/tests/{id:path}")
    def _test_json(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return JSONResponse(editor.test_state(id))
        except KeyError:
            return JSONResponse({"error": f"no test {id}"}, status_code=404)

    @app.post("/api/compose")
    def _compose(body: dict[str, Any]) -> Any:
        """Write a feature file. **This performs nothing** — it is text, and only text."""
        answering(editor, str(body.get("env", "")))
        path = editor.compose(
            str(body.get("name", "composed")),
            str(body.get("scenario", "a scenario")),
            [(str(k), str(v)) for k, v in body.get("lines", [])],
        )
        return JSONResponse({"wrote": str(path)})

    @app.post("/api/composer")
    def _offers(body: dict[str, Any]) -> Any:
        """What can be said next, given what is written above it."""
        answering(editor, str(body.get("env", "")))
        so_far = [(str(k).lower(), str(v)) for k, v in body.get("lines", [])]
        return JSONResponse(editor.composer(so_far))

    @app.post("/api/composer/try")
    def _try(body: dict[str, Any]) -> Any:
        """Run a draft against `local`, without saving it — the composer's own dry run."""
        answering(editor, str(body.get("env", "")))
        try:
            return JSONResponse(editor.try_scenario(str(body.get("text", ""))))
        except Exception as exc:  # noqa: BLE001 - a draft that will not even parse is an answer, not a crash
            return JSONResponse({"code": 2, "lines": [str(exc)]})

    @app.post("/api/tests/lint")
    def _lint_draft(body: dict[str, Any]) -> Any:
        """What `atf plan` would say about this draft — the editor's own inline linting, live."""
        answering(editor, str(body.get("env", "")))
        try:
            problems = editor.lint_draft(str(body.get("text", "")))
        except Exception as exc:  # noqa: BLE001 - unparseable is an answer here too, not a crash
            problems = [str(exc)]
        return JSONResponse({"problems": problems})

    @app.post("/api/tests/{id:path}/save")
    def _save_test(id: str, body: dict[str, Any]) -> Any:
        """Save an existing test's edited text back to its file — validated, rolled back if not."""
        answering(editor, str(body.get("env", "")))
        try:
            editor.save_test_source(id, str(body.get("text", "")))
        except KeyError:
            return JSONResponse({"error": f"no test {id}"}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FeatureError as exc:
            return JSONResponse({"error": f"does not parse: {exc}"}, status_code=422)
        except core.LintError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse({"saved": True})

    @app.post("/api/tests/save-new")
    def _save_new_test(body: dict[str, Any]) -> Any:
        """Save a freshly typed scenario — appended to an existing file, or a new one created."""
        answering(editor, str(body.get("env", "")))
        name = str(body.get("name", "")).strip()
        text = str(body.get("text", ""))
        if not name:
            return JSONResponse({"error": "name the file this test belongs in"}, status_code=400)
        try:
            new_id = editor.compose_text(name, text)
        except FeatureError as exc:
            return JSONResponse({"error": f"does not parse: {exc}"}, status_code=422)
        except core.LintError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        except IndexError:
            return JSONResponse({"error": "write at least one Scenario: to save"}, status_code=400)
        return JSONResponse({"saved": True, "id": new_id})

    @app.get("/api/tools")
    def _tools() -> Any:
        """What `atf edit --mcp` offers, as data, readable without the SDK installed."""
        from .agent import TOOLS

        return JSONResponse(TOOLS)

    @app.get("/api/resource/{name}")
    def _resource(name: str, env: str = "") -> Any:
        answering(editor, env)
        return JSONResponse(editor.resource(name))

    @app.get("/api/resources/{kind}/undeclared")
    def _undeclared(kind: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return JSONResponse(editor.undeclared(kind))
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/api/make/{name}")
    def _make(name: str, env: str = "") -> Any:
        answering(editor, env)
        answer = editor.make(name)
        return JSONResponse(answer, status_code=200 if answer["code"] == 0 else 409)

    # Registered last: `/api/{view}` matches any single segment, and would shadow the routes above.
    @app.get("/api/{view}")
    def _api(view: str, env: str = "") -> Any:
        """The same answers as data. `atf edit --mcp` serves these to an agent."""
        answering(editor, env)
        reader = getattr(editor, view, None)
        if reader is None or view not in VIEWS:
            return JSONResponse({"error": f"no view called {view!r}"}, status_code=404)
        return JSONResponse(reader())

    return app


#: The only interface `atf edit` binds. There is no flag that changes it: with no authentication,
#: the loopback interface is the boundary.
LOOPBACK = "127.0.0.1"


def serve(manifest: Path | None, env: str, port: int) -> None:
    """Start the server on loopback, and print where. Blocks until interrupted."""
    import uvicorn

    print(f"atf edit on http://{LOOPBACK}:{port}")
    uvicorn.run(build_app(Editor(manifest, env)), host=LOOPBACK, port=port, log_level="warning")


def last_run(root: Path, environment: str) -> runs.Run | None:
    past = runs.runs_for(root, environment)
    return past[-1] if past else None
