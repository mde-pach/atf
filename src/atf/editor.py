"""`atf edit` — a local server that reads and drives the suite you already have.

**Every view here is a call into [core](core.py), and nothing else.** The editor holds no logic of
its own: no query, no state, no second opinion about what a resource is. That is the rule the old
cockpit broke — seven of its eight routers reached into `session` and `materializer` directly — and
one module to read from is what keeps it from re-rotting.

**It knows about no specific type, system, claim or marker.** It renders whatever the registries
contain, so a suite that registers `@redis` gets a catalogue entry, a graph node and a composer
sentence without a line here changing. A concept needing a special case to be rendered is not
finished: fix the model, not the editor.

The pages are deliberately plain HTML. Everything a person reads is a role and a name, because that
is what a scenario claims on — `Then the heading "Catalogue" is showing`.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from . import core, record
from .commands import make as make_resources
from .environment import build_ground
from .loader import load_suite
from .manifest import load

VIEWS = ("overview", "catalogue", "graph", "tests", "composer", "activity", "environments")


class Editor:
    """One suite, one environment, and the six views over it."""

    def __init__(self, manifest: Path | None = None, env: str = "") -> None:
        self.manifest_path = manifest
        self.env = env
        self.reload()

    def reload(self) -> None:
        """Re-read everything. Refreshing re-asks, so what you see is what it said a moment ago."""
        from .plugin import Loaded  # noqa: PLC0415 - the specs are only needed by the editor here

        self.suite = load_suite(load(self.manifest_path) if self.manifest_path else None)
        self.ground = build_ground(self.suite, self.env)
        self.root = self.suite.manifest.root
        try:
            loaded = Loaded(self.root)
            self.features, self.phrases = loaded.features, loaded.phrases
        except Exception:  # noqa: BLE001 - a suite whose specs will not read still has a catalogue
            self.features, self.phrases = [], {}

    # --- The views, each one a call into core ---------------------------------------------------

    def overview(self) -> dict[str, Any]:
        summary = core.overview(self.ground, self.root)
        return {
            "sentence": summary.sentence,
            "ready": summary.ready,
            "resources": summary.resources,
            "tests": summary.tests,
            "last_run": summary.last_run.as_json() if summary.last_run else None,
            "well_formed": summary.well_formed,
        }

    def catalogue(self) -> list[dict[str, Any]]:
        return [
            {"kind": one.kind, "system": one.system, "scope": one.scope, "declared": one.declared, "states": one.states}
            for one in core.catalogue(self.ground)
        ]

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

    def graph(self) -> list[dict[str, Any]]:
        return [
            {"id": node.id, "label": node.label, "kind": node.kind, "needs": node.needs}
            for node in core.spine(self.suite, self.features, self.phrases)
        ]

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
            }
            for one in core.tests(self.suite, self.features, self.root, self.ground.config.name)
        ]

    def composer(self) -> dict[str, Any]:
        """The one view with no command behind it: it writes Gherkin, and performs nothing."""
        return {"sentences": core.sayable(self.suite), "subjects": core.subjects(self.suite)}

    def activity(self) -> list[dict[str, Any]]:
        return [run.as_json() for run in core.activity(self.root, self.ground.config.name)]

    def environments(self) -> list[dict[str, Any]]:
        return core.environments(self.suite)

    # --- The one button ---------------------------------------------------------------------

    def make(self, name: str) -> dict[str, Any]:
        """Make one resource. **The same call the command makes**, with the same answer."""
        report = make_resources(self.ground.config.name, [name], manifest=self.suite.manifest)
        self.reload()
        return {
            "code": report.code,
            "error": report.error,
            "resources": [
                {"name": o.name, "state": str(o.state), "did": str(o.did), "why": o.why}
                for o in report.outcomes
            ],
        }


# --- The pages ------------------------------------------------------------------------------------


def page(title: str, body: str, current: str) -> str:
    """One plain page. A heading and a name are what a scenario claims on, so they are the markup."""
    nav = " ".join(
        f'<a href="/{view}"{" aria-current=page" if view == current else ""}>{view.title()}</a>'
        for view in VIEWS
    )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{html.escape(title)} · atf</title>"
        "<style>body{font:16px/1.5 system-ui;margin:2rem;max-width:60rem}"
        "nav a{margin-right:1rem}table{border-collapse:collapse}td,th{padding:.2rem .8rem .2rem 0;text-align:left}"
        "code{background:#f4f4f4;padding:.1rem .3rem}</style></head><body>"
        f"<nav aria-label=Views>{nav}</nav><h1>{html.escape(title)}</h1>{body}</body></html>"
    )


def render_overview(editor: Editor) -> str:
    summary = editor.overview()
    rows = "".join(
        f"<tr><th>{key}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in (
            ("resources", " · ".join(f"{n} {word}" for word, n in summary["resources"].items())),
            ("tests", " · ".join(f"{n} {word}" for word, n in summary["tests"].items()) or "never run"),
            ("last run", (summary["last_run"] or {}).get("started", "none")),
            ("suite", "well formed" if summary["well_formed"] else "has faults"),
        )
    )
    return page("Overview", f"<p>{html.escape(summary['sentence'])}</p><table>{rows}</table>", "overview")


def render_catalogue(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td><a href='/catalogue/{one['kind']}'>{html.escape(one['kind'])}</a></td>"
        f"<td>{one['declared']} declared</td>"
        f"<td>{html.escape(' · '.join(f'{n} {w}' for w, n in one['states'].items()))}</td>"
        f"<td><code>{html.escape(one['system'])}</code></td></tr>"
        for one in editor.catalogue()
    )
    return page("Catalogue", f"<table>{rows}</table>", "catalogue")


def render_graph(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(node['label'])}</td><td>{html.escape(node['kind'])}</td>"
        f"<td>{html.escape(', '.join(node['needs']) or '-')}</td></tr>"
        for node in editor.graph()
    )
    return page("The graph", f"<table><tr><th>node<th>kind<th>needs</tr>{rows}</table>", "graph")


def render_tests(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(one['label'])}</td><td>{html.escape(one['verdict'])}</td>"
        f"<td>{html.escape(' '.join(one['tags']))}</td>"
        f"<td>{html.escape(', '.join(one['arranges']) or '-')}</td></tr>"
        for one in editor.tests()
    )
    return page("Tests", f"<table><tr><th>test<th>verdict<th>tags<th>arranges</tr>{rows}</table>", "tests")


def render_composer(editor: Editor) -> str:
    offered = editor.composer()
    blocks = "".join(
        f"<h2>{keyword.title()}</h2><ul>"
        + "".join(f"<li><code>{html.escape(pattern)}</code></li>" for pattern in patterns)
        + "</ul>"
        for keyword, patterns in offered["sentences"].items()
        if patterns
    )
    return page("The composer", blocks, "composer")


def render_activity(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(run['id'])}</td><td>{html.escape(run['started'])}</td>"
        f"<td>{html.escape(run['source'])}</td>"
        f"<td>{sum(1 for o in run['outcomes'] if o['outcome'] == 'failed')} failed</td></tr>"
        for run in editor.activity()
    )
    return page("Activity", f"<table>{rows}</table>" if rows else "<p>no runs recorded</p>", "activity")


def render_environments(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(one['name'])}</td>"
        f"<td>{'may be changed' if one['mutable'] else 'read only'}</td>"
        f"<td>{html.escape(', '.join(one['systems']))}</td></tr>"
        for one in editor.environments()
    )
    return page("Environments", f"<table>{rows}</table>", "environments")


RENDERERS = {
    "overview": render_overview,
    "catalogue": render_catalogue,
    "graph": render_graph,
    "tests": render_tests,
    "composer": render_composer,
    "activity": render_activity,
    "environments": render_environments,
}


def build_app(editor: Editor) -> Any:
    """A FastAPI app over the editor. Every route is one call into `core`, through `Editor`."""
    from fastapi import FastAPI  # noqa: PLC0415 - only the editor needs a web framework
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="atf edit", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def _root() -> Any:
        editor.reload()
        return HTMLResponse(render_overview(editor))

    for view, render in RENDERERS.items():

        def _view(render: Any = render) -> Any:
            editor.reload()
            return HTMLResponse(render(editor))

        app.get(f"/{view}", response_class=HTMLResponse)(_view)

    @app.get("/api/{view}")
    def _api(view: str) -> Any:
        """The same answers as data. `atf edit --mcp` serves these to an agent."""
        editor.reload()
        reader = getattr(editor, view, None)
        if reader is None or view not in VIEWS:
            return JSONResponse({"error": f"no view called {view!r}"}, status_code=404)
        return JSONResponse(reader())

    @app.get("/api/resource/{name}")
    def _resource(name: str) -> Any:
        editor.reload()
        return JSONResponse(editor.resource(name))

    @app.post("/api/make/{name}")
    def _make(name: str) -> Any:
        answer = editor.make(name)
        return JSONResponse(answer, status_code=200 if answer["code"] == 0 else 409)

    return app


def serve(manifest: Path | None, env: str, host: str, port: int) -> None:
    """Start the server. Blocks until interrupted."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run(build_app(Editor(manifest, env)), host=host, port=port, log_level="warning")


def last_run(root: Path, environment: str) -> record.Run | None:
    runs = record.runs_for(root, environment)
    return runs[-1] if runs else None
