"""`atf edit` — a local server over the suite, reading only `core`."""

from __future__ import annotations

import html
import json
import urllib.parse
from pathlib import Path
from typing import Any

from . import core, markers, record
from .commands import make as make_resources
from .environment import build_ground
from .loader import SuiteError, load_suite
from .manifest import load

VIEWS = ("overview", "catalogue", "graph", "tests", "composer", "activity", "environments")


def _as_node(node: core.Node) -> dict[str, Any]:
    return {"id": node.id, "label": node.label, "kind": node.kind, "needs": node.needs}


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

    def instances(self, kind: str) -> list[dict[str, Any]]:
        return core.instances(self.ground, kind)

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
            "actions": here.actions,
            "layers": [[_as_node(one) for one in layer] for layer in here.layers],
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
            }
            for one in core.tests(self.suite, self.features, self.root, self.ground.config.name)
        ]

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
            "markers": sorted(f"#{name}" for name in markers.REGISTRY),
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
        body += [f"    {keyword} {sentence}" for keyword, sentence in lines]
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        self.reload()
        return path

    def unused(self) -> dict[str, list[str]]:
        """What nothing asks for. **The same call the command makes**, with the same answer."""
        from .commands import do_unused  # noqa: PLC0415 - the editor reaches one command, as `make` does

        found = do_unused(config=str(self.manifest_path) if self.manifest_path else None)
        return {key: [str(one) for one in value] for key, value in found.data.items()}

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


def render_kind(editor: Editor, kind: str) -> str:
    """Opening a kind lists its instances with what the environment holds for each."""
    rows = "".join(
        f"<tr><td><a href='/catalogue/{kind}/{one['name']}'>{html.escape(one['name'])}</a></td>"
        f"<td>{html.escape(one['state'])}</td>"
        f"<td>{html.escape(', '.join(f'{k}={v}' for k, v in one['recognised_by'].items()))}</td>"
        f"<td>{html.escape(', '.join(one['changes']) or '-')}</td></tr>"
        for one in editor.instances(kind)
    )
    body = (
        f"<p><a href=/catalogue>Catalogue</a></p>"
        f"<table><tr><th>resource<th>state<th>recognised by<th>would change</tr>{rows}</table>"
    )
    return page(kind, body, "catalogue")


def render_resource(editor: Editor, name: str) -> str:
    """The five things opening one resource shows, and the one button.

    None of this is a preview the editor assembles. The create body is what the adapter's `create`
    would receive; the change set is the diff ATF computed and would hand to `update`.
    """
    one = editor.resource(name)
    parts = [
        f"<p>{html.escape(one['name'])} · {html.escape(one['kind'])} · "
        f"{html.escape(one['state'])} in {html.escape(editor.ground.config.name)}</p>",
        _section("the declaration", one["declaration"]),
        _section("what it is recognised by", one["recognised_by"]),
        _section("what the environment holds", one["found"] or "nothing"),
    ]
    if one["would_create"] is not None:
        parts.append(_section("would create with", one["would_create"]))
    if one["would_change"]:
        rows = "".join(
            f"<tr><td>{html.escape(field)}</td><td>{html.escape(str(sides['found']))}</td>"
            f"<td>-&gt;</td><td>{html.escape(str(sides['declared']))}</td></tr>"
            for field, sides in one["would_change"].items()
        )
        parts.append(f"<h2>would change</h2><table>{rows}</table>")

    if one["can_make"]:
        parts.append(
            f"<form method=post action='/make/{name}'>"
            f"<button type=submit>Make</button></form>"
        )
    else:
        parts.append(
            f"<p><button type=button disabled>Make</button> "
            f"disabled — {html.escape(one['why_not'])}</p>"
        )
    return page(f"{one['name']} · {one['kind']}", "".join(parts), "catalogue")


def _section(title: str, value: Any) -> str:
    return f"<h2>{html.escape(title)}</h2><pre>{html.escape(json.dumps(value, indent=2, default=str))}</pre>"


# Small lineage is stated in words and anything larger is drawn. Both numbers are rendering
# decisions: no answer changes with them, only how much of one is a sentence.
WORDS_UPTO = 3
MANY_DEPENDANTS = 3


def render_graph(editor: Editor) -> str:
    """Every node, each one a link. There is no node here that only a search box finds."""
    nodes = editor.graph()
    rows = "".join(
        f"<tr><td>{_node_link(node['id'], node['label'])}</td><td>{html.escape(node['kind'])}</td>"
        f"<td>{', '.join(_node_link(one, one) for one in node['needs']) or '-'}</td></tr>"
        for node in nodes
    )
    entries = (
        "<p>Two questions have their own entry points: "
        "<strong>what breaks if this does</strong> is on every node below, and "
        "<a href=/unused>what nothing asks for</a> is the resources no test reaches.</p>"
    )
    return page("The graph", f"{entries}<table><tr><th>node<th>kind<th>needs</tr>{rows}</table>", "graph")


def _node_link(id: str, label: str) -> str:
    return f"<a href='/graph/{urllib.parse.quote(id, safe='')}'>{html.escape(label)}</a>"


def render_node(editor: Editor, id: str) -> str:
    """One node, its lineage in words, and every edge out of it as a link.

    Past `WORDS_UPTO`, or where many things stand on this one, the lineage is drawn and the
    sentence becomes the drawing's caption.
    """
    here = editor.node(id)
    drawn = len(here["layers"]) > WORDS_UPTO or len(here["needed_by"]) >= MANY_DEPENDANTS
    parts = [f"<p>{html.escape(here['kind'])}</p>"]
    if here["sentence"] and not drawn:
        parts.append(f"<p>{html.escape(here['sentence'])}</p>")
    if drawn and here["layers"]:
        parts.append(_drawing(here["layers"]))
        parts.append(f"<p><small>{html.escape(here['sentence'])}</small></p>")
    parts.append(_edges("needs", here["needs"]))
    parts.append(_edges("what breaks if this does", here["needed_by"]))
    if here["actions"]:
        performed = " ".join(f"<code>{html.escape(one)}</code>" for one in here["actions"])
        parts.append(f"<h2>actions</h2><p>{performed}</p>")
    return page(here["label"], "".join(parts), "graph")


def _edges(title: str, nodes: list[dict[str, Any]]) -> str:
    if not nodes:
        return f"<h2>{title}</h2><p>nothing</p>"
    items = "".join(f"<li>{_node_link(one['id'], one['label'])}</li>" for one in nodes)
    return f"<h2>{title}</h2><ul>{items}</ul>"


ROW, COLUMN, BOX, WIDE = 64, 200, 26, 156


def _drawing(layers: list[list[dict[str, Any]]]) -> str:
    """The lineage as SVG, one column per depth, parents on the left.

    Every box is the same link its row in the table is, so the drawing is moved through like the
    rest of the view.
    """
    at = {
        one["id"]: (column * COLUMN + 4, row * ROW + 4)
        for column, layer in enumerate(layers)
        for row, one in enumerate(layer)
    }
    height = max((len(layer) for layer in layers), default=0) * ROW + 8
    lines = "".join(
        f'<line x1="{at[one["id"]][0]}" y1="{at[one["id"]][1] + BOX // 2}" '
        f'x2="{at[parent][0] + WIDE}" y2="{at[parent][1] + BOX // 2}" stroke="#999" />'
        for layer in layers
        for one in layer
        for parent in one["needs"]
        if parent in at
    )
    boxes = "".join(
        f'<a href="/graph/{urllib.parse.quote(one["id"], safe="")}">'
        f'<rect x="{at[one["id"]][0]}" y="{at[one["id"]][1]}" width="{WIDE}" height="{BOX}" '
        f'fill="#fff" stroke="#333" rx="4" />'
        f'<text x="{at[one["id"]][0] + 8}" y="{at[one["id"]][1] + 18}" font-size="13">'
        f"{html.escape(one['label'])}</text></a>"
        for layer in layers
        for one in layer
    )
    width = len(layers) * COLUMN + 8
    return f'<svg role="img" aria-label="Lineage" width="{width}" height="{height}">{lines}{boxes}</svg>'


def render_unused(editor: Editor) -> str:
    """The graph's second entry point: what nothing asks for."""
    found = editor.unused()
    blocks = ""
    for what in ("resources", "phrases", "steps"):
        loose = found.get(what, [])
        items = "".join(f"<li>{html.escape(one)}</li>" for one in loose)
        blocks += f"<h2>{what}</h2>" + (f"<ul>{items}</ul>" if loose else "<p>nothing</p>")
    return page("What nothing asks for", f"<p><a href=/graph>The graph</a></p>{blocks}", "graph")


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
    blocks = ""
    for keyword in ("Given", "When", "Then"):
        mine = [one for one in offered["offers"] if one["keyword"] == keyword]
        if not mine:
            continue
        rows = "".join(
            f"<li><code>{html.escape(one['sentence'])}</code> "
            f"<small>{html.escape(one['why'])}</small></li>"
            for one in mine
        )
        blocks += f"<h2>{keyword}</h2><ul>{rows}</ul>"
    if offered["quiet"]:
        quiet = "".join(f"<li>{html.escape(one)}</li>" for one in offered["quiet"])
        blocks += f"<h2>Contributing no When</h2><ul>{quiet}</ul>"
    blocks += (
        "<h2>Markers</h2><p>"
        + " ".join(f"<code>{html.escape(one)}</code>" for one in offered["markers"])
        + "</p>"
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
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

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

    @app.get("/unused", response_class=HTMLResponse)
    def _unused() -> Any:
        editor.reload()
        return HTMLResponse(render_unused(editor))

    @app.get("/graph/{id:path}", response_class=HTMLResponse)
    def _node(id: str) -> Any:
        editor.reload()
        try:
            return HTMLResponse(render_node(editor, id))
        except KeyError:
            return HTMLResponse(page("Not found", f"<p>no node {html.escape(id)}</p>", "graph"), status_code=404)

    @app.get("/api/graph/{id:path}")
    def _node_json(id: str) -> Any:
        editor.reload()
        try:
            return JSONResponse(editor.node(id))
        except KeyError:
            return JSONResponse({"error": f"no node {id}"}, status_code=404)

    @app.get("/api/unused")
    def _unused_json() -> Any:
        editor.reload()
        return JSONResponse(editor.unused())

    @app.get("/catalogue/{kind}", response_class=HTMLResponse)
    def _kind(kind: str) -> Any:
        editor.reload()
        try:
            return HTMLResponse(render_kind(editor, kind))
        except KeyError as exc:
            return HTMLResponse(page("Not found", f"<p>{html.escape(str(exc))}</p>", "catalogue"), status_code=404)

    @app.get("/catalogue/{kind}/{name}", response_class=HTMLResponse)
    def _one(kind: str, name: str) -> Any:
        editor.reload()
        try:
            return HTMLResponse(render_resource(editor, name))
        except SuiteError as exc:
            return HTMLResponse(page("Not found", f"<p>{html.escape(str(exc))}</p>", "catalogue"), status_code=404)

    @app.post("/make/{name}")
    def _make_button(name: str) -> Any:
        """The Make button. **The same call the command makes** — there is no privileged path."""
        editor.make(name)
        return RedirectResponse(f"/catalogue/{editor.resource(name)['kind']}/{name}", status_code=303)

    @app.post("/api/compose")
    def _compose(body: dict[str, Any]) -> Any:
        """Write a feature file. **This performs nothing** — it is text, and only text."""
        editor.reload()
        path = editor.compose(
            str(body.get("name", "composed")),
            str(body.get("scenario", "a scenario")),
            [(str(k), str(v)) for k, v in body.get("lines", [])],
        )
        return JSONResponse({"wrote": str(path)})

    @app.post("/api/composer")
    def _offers(body: dict[str, Any]) -> Any:
        """What can be said next, given what is written above it."""
        editor.reload()
        so_far = [(str(k).lower(), str(v)) for k, v in body.get("lines", [])]
        return JSONResponse(editor.composer(so_far))

    @app.get("/api/tools")
    def _tools() -> Any:
        """What `atf edit --mcp` offers, as data, readable without the SDK installed."""
        from .agent import TOOLS  # noqa: PLC0415

        return JSONResponse(TOOLS)

    @app.get("/api/resource/{name}")
    def _resource(name: str) -> Any:
        editor.reload()
        return JSONResponse(editor.resource(name))

    @app.post("/api/make/{name}")
    def _make(name: str) -> Any:
        answer = editor.make(name)
        return JSONResponse(answer, status_code=200 if answer["code"] == 0 else 409)

    # Registered last: `/api/{view}` matches any single segment, and would shadow the routes above.
    @app.get("/api/{view}")
    def _api(view: str) -> Any:
        """The same answers as data. `atf edit --mcp` serves these to an agent."""
        editor.reload()
        reader = getattr(editor, view, None)
        if reader is None or view not in VIEWS:
            return JSONResponse({"error": f"no view called {view!r}"}, status_code=404)
        return JSONResponse(reader())

    return app


def serve(manifest: Path | None, env: str, host: str, port: int) -> None:
    """Start the server. Blocks until interrupted."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run(build_app(Editor(manifest, env)), host=host, port=port, log_level="warning")


def last_run(root: Path, environment: str) -> record.Run | None:
    runs = record.runs_for(root, environment)
    return runs[-1] if runs else None
