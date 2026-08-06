"""`atf edit` — a local server over the suite, reading only `core`."""

from __future__ import annotations

import html
import json
import urllib.parse
from datetime import UTC
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
        self.default_env = env
        self.env = env
        self.reload()

    def reload(self, env: str | None = None) -> None:
        """Re-read everything for one environment. Refreshing re-asks, never remembers.

        The environment is an argument to every question the core answers, so it is an argument
        here: a request naming one is answered against that one, and `?env=` is how a link carries
        it.
        """
        from .plugin import Loaded  # noqa: PLC0415 - the specs are only needed by the editor here

        self.env = env or self.default_env
        self.suite = load_suite(load(self.manifest_path) if self.manifest_path else None)
        self.ground = build_ground(self.suite, self.env)
        self.root = self.suite.manifest.root
        try:
            loaded = Loaded(self.root)
            self.features, self.phrases = loaded.features, loaded.phrases
        except Exception:  # noqa: BLE001 - a suite whose specs will not read still has a catalogue
            self.features, self.phrases = [], {}

    # --- The views, each one a call into core ---------------------------------------------------

    def faults(self) -> list[dict[str, str]]:
        """What `atf check` finds, through the same call the command makes."""
        from .commands import do_check  # noqa: PLC0415 - the editor reaches one command, as `make` does

        found = do_check(config=str(self.manifest_path) if self.manifest_path else None)
        return [dict(one) for one in found.data.get("faults", [])]

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

    def test(self, id: str) -> dict[str, Any]:
        """One test opened. `KeyError` where the suite describes no such behaviour."""
        found = core.detail_of_test(
            self.suite, self.features, self.root, self.ground.config.name, id
        )
        kinds = {
            name: type(node).__name__.lower() for name, node in self.suite.instances.items()
        }
        return {
            "id": found.id,
            "label": found.label,
            "form": found.form,
            "tags": found.tags,
            "verdict": found.verdict,
            "flaky": found.flaky,
            "where": found.where,
            "lines": found.lines,
            "arranges": [(name, kinds.get(name, "")) for name in found.arranges],
            "last": found.last.as_json() if found.last else None,
            "before": found.before,
        }

    def run_one(self, id: str) -> dict[str, Any]:
        """Run one test. **The same call the command makes**: `atf run` with this identity named."""
        from .entry import Options, do_run  # noqa: PLC0415 - the editor reaches one command, as `make` does

        answer = do_run(
            Options(config=str(self.manifest_path) if self.manifest_path else None, quiet=True),
            env=self.ground.config.name,
            tag=(),
            select="",
            failed=False,
            keyword="",
            tests=(id,),
            report=(),
            no_make=False,
            dry_run=False,
        )
        self.reload(self.env)
        return {"code": answer.code, "lines": answer.lines}

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
        body += [f"    {keyword.title()} {sentence}" for keyword, sentence in lines]
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        self.reload()
        return path

    def unused(self) -> dict[str, list[str]]:
        """What nothing asks for. **The same call the command makes**, with the same answer."""
        from .commands import do_unused  # noqa: PLC0415 - the editor reaches one command, as `make` does

        found = do_unused(config=str(self.manifest_path) if self.manifest_path else None)
        return {key: [str(one) for one in value] for key, value in found.data.items()}

    def activity(self) -> list[dict[str, Any]]:
        return [
            {**run.as_json(), "verdict": str(run.verdict)}
            for run in core.activity(self.root, self.ground.config.name)
        ]

    def run(self, id: str) -> dict[str, Any]:
        """One recorded run. `KeyError` where this environment has no run by that name."""
        for one in core.activity(self.root, self.ground.config.name):
            if one.id == id:
                return {**one.as_json(), "verdict": str(one.verdict)}
        raise KeyError(id)

    def formats(self) -> list[str]:
        """Every registered report format, which is what a completed run can be exported as."""
        from .reports import formats  # noqa: PLC0415

        return formats()

    def export(self, id: str, format_: str) -> tuple[str, str]:
        """One run written out in a registered format, as text. The same writer `--report` uses."""
        import tempfile  # noqa: PLC0415

        from .reports import REGISTRY, ReportError, write  # noqa: PLC0415

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


def page(title: str, body: str, current: str) -> str:
    """One plain page. A heading and a name are what a scenario claims on, so they are the markup."""
    nav = " ".join(
        link(f"/{view}", view.title(), **({"aria-current": "page"} if view == current else {}))
        for view in VIEWS
    )
    switch = " ".join(
        f'<a href="/{current}?env={urllib.parse.quote(one)}">{html.escape(one)}</a>'
        for one in ENVIRONMENTS
    )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{html.escape(title)} · atf</title>"
        "<style>body{font:16px/1.5 system-ui;margin:2rem;max-width:60rem}"
        "nav a{margin-right:1rem}table{border-collapse:collapse}td,th{padding:.2rem .8rem .2rem 0;text-align:left}"
        "code{background:#f4f4f4;padding:.1rem .3rem}"
        "svg a rect{fill:#fff}svg a:hover rect{fill:#eef}</style></head><body>"
        f"<nav aria-label=Views>{nav}</nav>"
        f"<nav aria-label=Environments>environment: {switch}</nav>"
        f"<h1>{html.escape(title)}</h1>{body}</body></html>"
    )


#: Every environment the manifest declares, so the switcher can offer them. Set on each request.
ENVIRONMENTS: list[str] = []


#: The run vocabulary folded into the verdict words the overview speaks.
_FOLDED = {"passed": "passing", "failed": "failing", "skipped": "skipped"}


def render_overview(editor: Editor) -> str:
    """The four things that could contradict the verdict, each linking to what shows the detail."""
    summary = editor.overview()
    last = summary["last_run"] or {}
    rows = "".join(
        f"<tr><th>{link(href, key)}</th><td>{value}</td></tr>"
        for key, href, value in (
            (
                "resources",
                "/catalogue",
                " · ".join(f"{n} {word}" for word, n in summary["resources"].items()),
            ),
            (
                "tests",
                "/tests",
                " · ".join(f"{n} {_FOLDED.get(word, word)}" for word, n in summary["tests"].items())
                or "never run",
            ),
            (
                "last run",
                "/activity",
                f"{_ago(last.get('started', ''))}, {last.get('source', '')} "
                f"{last.get('label') or ''}".strip().rstrip(",")
                if last
                else "none",
            ),
            (
                "suite",
                "/faults",
                "well formed" if summary["well_formed"] else f"{summary['faults']} faults",
            ),
        )
    )
    return page("Overview", f"<p>{html.escape(summary['sentence'])}</p><table>{rows}</table>", "overview")


def _ago(stamp: str) -> str:
    """`6 minutes ago`, which is what a person reads a timestamp as."""
    from datetime import datetime  # noqa: PLC0415

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
    if not found:
        return page("Faults", "<p>no faults</p>", "overview")
    rows = "".join(
        f"<tr><td>{html.escape(one['where'])}</td><td>{html.escape(one['why'])}</td>"
        f"<td>{html.escape(one['check'])}</td></tr>"
        for one in found
    )
    return page("Faults", f"<table><tr><th>where<th>why<th>check</tr>{rows}</table>", "overview")


def render_catalogue(editor: Editor) -> str:
    rows = "".join(
        f"<tr><td>{link('/catalogue/' + one['kind'], one['kind'])}</td>"
        f"<td>{one['declared']} declared</td>"
        f"<td>{html.escape(' · '.join(f'{n} {w}' for w, n in one['states'].items()))}</td>"
        f"<td><code>{html.escape(one['system'])}</code></td></tr>"
        for one in editor.catalogue()
    )
    return page("Catalogue", f"<table>{rows}</table>", "catalogue")


def render_kind(editor: Editor, kind: str) -> str:
    """Opening a kind lists its instances with what the environment holds for each."""
    rows = "".join(
        f"<tr><td>{link(f'/catalogue/{kind}/' + one['name'], one['name'])}</td>"
        f"<td>{html.escape(one['state'])}</td>"
        f"<td>{html.escape(', '.join(f'{k}={v}' for k, v in one['recognised_by'].items()))}</td>"
        f"<td>{html.escape(', '.join(one['changes']) or '-')}</td></tr>"
        for one in editor.instances(kind)
    )
    body = (
        f"<p>{link('/catalogue', 'Catalogue')}</p>"
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
        f"{link('/unused', 'what nothing asks for')} is the resources no test reaches.</p>"
    )
    return page("The graph", f"{entries}<table><tr><th>node<th>kind<th>needs</tr>{rows}</table>", "graph")


def _node_link(id: str, label: str) -> str:
    return link(f"/graph/{urllib.parse.quote(id, safe='')}", label)


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
        f'<a href="{_with_env("/graph/" + urllib.parse.quote(one["id"], safe=""))}">'
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
    return page("What nothing asks for", f"<p>{link('/graph', 'The graph')}</p>{blocks}", "graph")


def render_tests(editor: Editor, verdict: str = "", tag: str = "") -> str:
    """Every behaviour in one list, filtered by verdict and by tag, each one a link into itself."""
    listed = editor.tests()
    shown = [
        one
        for one in listed
        if (not verdict or one["verdict"] == verdict) and (not tag or tag in one["tags"])
    ]
    rows = "".join(
        f"<tr><td>{link('/tests/' + urllib.parse.quote(one['id'], safe=''), one['label'])}</td>"
        f"<td>{html.escape(one['verdict'])}{' · flaky' if one['flaky'] else ''}</td>"
        f"<td>{html.escape(one['form'])}</td>"
        f"<td>{html.escape(' '.join(one['tags']))}</td>"
        f"<td>{html.escape(', '.join(one['arranges']) or '-')}</td></tr>"
        for one in shown
    )
    verdicts = sorted({one["verdict"] for one in listed})
    tags = sorted({one for entry in listed for one in entry["tags"]})
    filters = (
        "<p>verdict: "
        + link("/tests", "any")
        + "".join(" · " + link(f"/tests?verdict={urllib.parse.quote(one)}", one) for one in verdicts)
        + "</p><p>tag: "
        + link("/tests", "any")
        + "".join(" · " + link(f"/tests?tag={urllib.parse.quote(one)}", one) for one in tags)
        + "</p>"
    )
    table = f"<table><tr><th>test<th>verdict<th>form<th>tags<th>arranges</tr>{rows}</table>"
    return page("Tests", filters + table, "tests")


def render_test(editor: Editor, id: str) -> str:
    """One test: its sentences, the resources it asks for as links, its history, and the button."""
    one = editor.test(id)
    head = f"<p>{html.escape(one['form'])} · {html.escape(one['verdict'])}"
    head += " · flaky" if one["flaky"] else ""
    head += f" · {html.escape(one['where'])}</p>" if one["where"] else "</p>"

    said = "".join(
        f"<tr><td><code>{html.escape(keyword)} {html.escape(text)}</code></td></tr>"
        for keyword, text in one["lines"]
    )
    body = head + (f"<table>{said}</table>" if said else "<p>written in Python</p>")

    if one["arranges"]:
        asked = ", ".join(link(f"/catalogue/{kind}/{name}", name) for name, kind in one["arranges"])
        body += f"<h2>arranges</h2><p>{asked}</p>"

    last = one["last"]
    if last:
        body += f"<h2>last run</h2><p>{html.escape(last['outcome'])}"
        if last.get("failed_at"):
            body += f"</p><pre>{html.escape(last['failed_at'].get('message', ''))}</pre>"
        else:
            body += "</p>"
    if one["before"]:
        body += f"<p>before that: {html.escape(', '.join(one['before']))}</p>"

    body += (
        f"<form method=post action=\"{_with_env('/run/' + urllib.parse.quote(one['id'], safe=''))}\">"
        f"<button type=submit>Run this test</button></form>"
    )
    return page(one["label"], body, "tests")


def render_composer(editor: Editor, so_far: list[str] | None = None) -> str:
    """The offers for this position, each one a button that takes it.

    What is offered depends on what is written above, so taking a step re-asks. The lines live in
    the URL: a composer half-written is a link somebody can send.
    """
    so_far = so_far or []
    written = [_split(one) for one in so_far]
    offered = editor.composer(written)

    said = "".join(
        f"<tr><td><code>{html.escape(keyword.title())} {html.escape(text)}</code></td></tr>"
        for keyword, text in written
    )
    blocks = f"<h2>so far</h2><table>{said}</table>" if written else ""
    if written:
        blocks += f"<p>{link(_composing(so_far[:-1]), 'undo')} · {link('/composer', 'start again')}</p>"

    for keyword in ("Given", "When", "Then"):
        mine = [one for one in offered["offers"] if one["keyword"] == keyword]
        if not mine:
            continue
        rows = "".join(
            f"<li>{link(_composing([*so_far, keyword + '|' + one['sentence']]), one['sentence'])} "
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

    if written:
        carried = "".join(
            f'<input type=hidden name=l value="{html.escape(one, quote=True)}">' for one in so_far
        )
        blocks += (
            f'<h2>write it</h2><form method=post action="{_with_env("/compose")}">{carried}'
            "<label>file <input name=name value=composed.feature></label> "
            "<label>scenario <input name=scenario value=\"a scenario\"></label> "
            "<button type=submit>Write</button></form>"
            "<p>This writes Gherkin under the specs directory and performs nothing.</p>"
        )
    return page("The composer", blocks, "composer")


def _split(written: str) -> tuple[str, str]:
    keyword, _, text = written.partition("|")
    return keyword.lower(), text


def _composing(lines: list[str]) -> str:
    query = "&".join(f"l={urllib.parse.quote(one)}" for one in lines)
    return f"/composer?{query}" if query else "/composer"


def render_activity(editor: Editor) -> str:
    """Every run of this environment, newest first, each one a link into its outcomes."""
    rows = "".join(
        f"<tr><td>{link('/activity/' + run['id'], run['id'])}</td>"
        f"<td>{html.escape(_ago(run['started']))}</td>"
        f"<td>{html.escape(run['source'])}{' · ' + html.escape(run['label']) if run.get('label') else ''}</td>"
        f"<td>{html.escape(str(run['verdict']))}</td>"
        f"<td>{sum(1 for o in run['outcomes'] if o['outcome'] == 'failed')} failed</td></tr>"
        for run in editor.activity()
    )
    table = f"<table><tr><th>run<th>when<th>source<th>verdict<th></tr>{rows}</table>"
    return page("Activity", table if rows else "<p>no runs recorded</p>", "activity")


def render_run(editor: Editor, id: str) -> str:
    """One run, item by item, with the message a failure produced quoted whole."""
    run = editor.run(id)
    items = ""
    for one in run["outcomes"]:
        mark = {"passed": "✓", "failed": "✗", "skipped": "·"}.get(one["outcome"], "·")
        items += (
            f"<tr><td>{mark}</td><td>{html.escape(one['outcome'])}</td>"
            f"<td>{html.escape(one['test'])}</td>"
            f"<td>{one['duration_ms'] / 1000:.1f}s</td></tr>"
        )
        if one.get("failed_at"):
            items += (
                f"<tr><td></td><td colspan=3><pre>{html.escape(one['failed_at'].get('message', ''))}</pre></td></tr>"
            )
    head = (
        f"<p>{html.escape(run['environment'])} · {html.escape(_ago(run['started']))} · "
        f"{html.escape(run['source'])} · {html.escape(str(run['verdict']))}</p>"
    )
    reports = " ".join(
        link(f"/activity/{id}/report/{one}", one) for one in sorted(editor.formats())
    )
    return page(
        run["id"],
        f"{head}<table>{items}</table><h2>export</h2><p>{reports}</p><p>{link('/activity', 'Activity')}</p>",
        "activity",
    )


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


def answering(editor: Editor, env: str = "") -> Editor:
    """Re-read for the environment this request names, and tell the page which one that is."""
    editor.reload(env)
    HERE[0] = editor.ground.config.name
    ENVIRONMENTS[:] = sorted(editor.suite.manifest.environments)
    return editor


def _form_defaults() -> tuple[Any, Any, Any]:
    """The composer's form fields, built once: a call in a default argument is a lint error."""
    from fastapi import Form  # noqa: PLC0415

    return Form(default="composed.feature"), Form(default="a scenario"), Form(default=[])


def _query_default() -> Any:
    from fastapi import Query  # noqa: PLC0415

    return Query(default=[])


_NAME, _SCENARIO, _LINES = _form_defaults()
_WRITTEN = _query_default()


def build_app(editor: Editor) -> Any:
    """A FastAPI app over the editor. Every route is one call into `core`, through `Editor`."""
    from fastapi import FastAPI  # noqa: PLC0415 - only the editor needs a web framework
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

    app = FastAPI(title="atf edit", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def _root(env: str = "") -> Any:
        return HTMLResponse(render_overview(answering(editor, env)))

    @app.get("/tests", response_class=HTMLResponse)
    def _tests(env: str = "", verdict: str = "", tag: str = "") -> Any:
        return HTMLResponse(render_tests(answering(editor, env), verdict, tag))

    @app.get("/composer", response_class=HTMLResponse)
    def _composer(env: str = "", l: list[str] = _WRITTEN) -> Any:  # noqa: E741 - `l` is the query name
        return HTMLResponse(render_composer(answering(editor, env), list(l)))

    for view, render in RENDERERS.items():
        if view in ("tests", "composer"):
            continue

        def _view(env: str = "", render: Any = render) -> Any:
            return HTMLResponse(render(answering(editor, env)))

        app.get(f"/{view}", response_class=HTMLResponse)(_view)

    @app.post("/compose")
    def _compose_button(
        env: str = "",
        name: str = _NAME,
        scenario: str = _SCENARIO,
        l: list[str] = _LINES,  # noqa: E741 - `l` is the field name the links write
    ) -> Any:
        """The Write button. **This performs nothing** — it is text, and only text."""
        answering(editor, env)
        path = editor.compose(name, scenario, [_split(one) for one in l])
        wrote = html.escape(str(path))
        return HTMLResponse(
            page("The composer", f"<p>wrote {wrote}</p><p>{link('/composer', 'compose another')}</p>", "composer")
        )

    @app.get("/activity/{id}", response_class=HTMLResponse)
    def _run(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_run(editor, id))
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
            return HTMLResponse(render_node(editor, id))
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

    @app.get("/catalogue/{kind}", response_class=HTMLResponse)
    def _kind(kind: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_kind(editor, kind))
        except KeyError as exc:
            return HTMLResponse(page("Not found", f"<p>{html.escape(str(exc))}</p>", "catalogue"), status_code=404)

    @app.get("/catalogue/{kind}/{name}", response_class=HTMLResponse)
    def _one(kind: str, name: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_resource(editor, name))
        except SuiteError as exc:
            return HTMLResponse(page("Not found", f"<p>{html.escape(str(exc))}</p>", "catalogue"), status_code=404)

    @app.post("/make/{name}")
    def _make_button(name: str, env: str = "") -> Any:
        """The Make button. **The same call the command makes** — there is no privileged path."""
        answering(editor, env)
        editor.make(name)
        where = f"/catalogue/{editor.resource(name)['kind']}/{name}"
        return RedirectResponse(_with_env(where), status_code=303)

    @app.post("/run/{id:path}")
    def _run_button(id: str, env: str = "") -> Any:
        """The Run button. **The same call the command makes** — `atf run -k` on this test."""
        answering(editor, env)
        editor.run_one(editor.test(id)["id"])
        return RedirectResponse(_with_env(f"/tests/{urllib.parse.quote(id, safe='')}"), status_code=303)

    @app.get("/tests/{id:path}", response_class=HTMLResponse)
    def _test(id: str, env: str = "") -> Any:
        answering(editor, env)
        try:
            return HTMLResponse(render_test(editor, id))
        except KeyError:
            return HTMLResponse(page("Not found", f"<p>no test {html.escape(id)}</p>", "tests"), status_code=404)

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

    @app.get("/api/tools")
    def _tools() -> Any:
        """What `atf edit --mcp` offers, as data, readable without the SDK installed."""
        from .agent import TOOLS  # noqa: PLC0415

        return JSONResponse(TOOLS)

    @app.get("/api/resource/{name}")
    def _resource(name: str, env: str = "") -> Any:
        answering(editor, env)
        return JSONResponse(editor.resource(name))

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


def serve(manifest: Path | None, env: str, host: str, port: int) -> None:
    """Start the server. Blocks until interrupted."""
    import uvicorn  # noqa: PLC0415

    uvicorn.run(build_app(Editor(manifest, env)), host=host, port=port, log_level="warning")


def last_run(root: Path, environment: str) -> record.Run | None:
    runs = record.runs_for(root, environment)
    return runs[-1] if runs else None
