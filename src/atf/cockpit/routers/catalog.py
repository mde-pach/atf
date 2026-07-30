"""Catalog — resource types, their instances, the lineage graph and the inspector."""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from markupsafe import Markup

from ...adapters import can_browse
from ...engine.materializer import Materializer, ScopeRequired
from ...engine.status import Statuses
from ...model.catalog import TYPES_FILE, Catalog, Node
from ...model.placeholders import Unresolved, references
from ...model.text import first_line, plural
from ..view import (
    TypeView,
    build_graph,
    closure_of,
    current_env,
    is_htmx,
    lineage_sentence,
    page,
    partial,
    type_views,
)
from ..view import cockpit as app

router = APIRouter(prefix="/catalog")

PURPOSE = (
    "Everything a scenario can ask for, whether it exists in this environment, "
    "and what provisioning it would actually do."
)

PLACEHOLDER = re.compile(r"\$\{[^}]*\}")

# Browsing is a convenience, not a run: one page of records, each shown narrow.
BROWSE_LIMIT = 100
MAX_COLUMNS = 8
CELL_CHARS = 48

# A record the environment has that no node declares: a state of a row in the instances table, and
# not a state of a resource — the engine has no word for it.
UNDECLARED = "not declared"

# A resource that depends on nothing has no lineage to draw, and the sentence says so in a line.
# Anything with a dependency gets the diagram: it is the only place the shape of the graph is
# visible, and hiding it until some size threshold means nobody ever finds out it exists.
GRAPH_FROM = 1

_FOREIGN_KEY = re.compile(r"_(id|uuid)$")


@router.get("")
def index(request: Request) -> Any:
    env = current_env(request)
    return page(request, "catalog.html", **_context(request, env))


@router.get("/type/{type_name}")
def type_page(request: Request, type_name: str) -> Any:
    env = current_env(request)
    if type_name not in app().state(env).materializer.types:
        raise HTTPException(status_code=404, detail=f"no resource type {type_name!r} is declared in this catalog")
    context = _context(request, env, focus="", type_name=type_name)
    if is_htmx(request):
        return partial(request, "partials/type_detail.html", **context)
    return page(request, "catalog.html", **context)


@router.get("/node/{node_id}")
def node_page(request: Request, node_id: str) -> Any:
    env = current_env(request)
    if node_id not in app().state(env).materializer.nodes:
        raise HTTPException(status_code=404, detail=f"no resource {node_id!r} is declared in this catalog")
    context = _context(request, env, focus=node_id)
    if is_htmx(request):
        return partial(request, "partials/catalog_focus.html", **context)
    return page(request, "catalog.html", **context)


@router.post("/rescan")
def rescan(request: Request) -> Any:
    """Re-read the catalog from disk and ask the environment what exists.

    This is a read. It changes nothing out there, so it is neither gated by `mutable_envs` nor
    confirmed — the only thing it can cost you is the time the adapters take to answer.
    """
    env = current_env(request)
    cockpit = app()
    cockpit.invalidate(env)
    cockpit.status.of(env, refresh=True)
    banner = f"Re-read the catalog and asked {env} what exists."
    return page(request, "catalog.html", **_context(request, env, banner=banner))


# ---- context ---------------------------------------------------------------


def context(request: Request, env: str, **extra: Any) -> dict[str, Any]:
    """The catalog context, for the authoring router: a write re-renders this whole vertical."""
    return _context(request, env, **extra)


def _context(
    request: Request,
    env: str,
    focus: str | None = None,
    type_name: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One context for every catalog response: the page and both fragments read the same keys."""
    cockpit = app()
    engine = cockpit.state(env).materializer
    nodes = engine.nodes
    status = cockpit.status.of(env)
    types = type_views(env)

    focus = _param(request, "focus", focus)
    wanted = _param(request, "type", type_name)
    scope_id = request.query_params.get("scope") or ""

    # A node selection wins, and pins its own type open in the list; otherwise a type is selected,
    # defaulting to the first one — the catalog always has something to say.
    node = nodes.get(focus)
    focus = node.id if node else ""
    selected = node.resource if node else (wanted if wanted in types else next(iter(types), ""))

    targets = cockpit.jobs.provision_targets(env)
    age = cockpit.status.age(env)

    context: dict[str, Any] = {
        "env": env,
        "title": "Catalog",
        "purpose": PURPOSE,
        "status": status,
        "types": types,
        "type": types.get(selected),
        "selected": selected,
        "focus": focus,
        "node": node,
        "scope_id": scope_id,
        # The environment is only asked what it holds when a type is what the page is about: with a
        # node selected the type page is not rendered, so browsing for it would be a wasted call.
        "records": None if node else environment_records(env, types.get(selected), scope_id),
        "instance_files": instance_files(),
        "keys": types[selected].spec.natural_keys if selected in types else [],
        # The label is derived from the same call the action uses, so the two cannot disagree.
        # With nothing to provision the control is not rendered at all: a disabled button beside
        # an explanation of why it is disabled is two elements saying "ignore me".
        "targets": targets,
        "provision_label": f"Provision {plural(len(targets), 'resource')}",
        "status_at": time.time() - age if age is not None else None,
        "banner": "",
        "banner_tone": "ok",
    }
    context.update(_node_context(env, node, nodes, status) if node else {})
    context.update(_type_context(env, types.get(selected), status))
    context["rows"] = instance_rows(types.get(selected), status, context["records"]) if not node else []
    context.update(extra)
    return context


def _node_context(env: str, node: Node, nodes: dict[str, Node], status: Statuses) -> dict[str, Any]:
    cockpit = app()
    found = cockpit.discovery.of(env)
    node_id = node.id
    entry = status.of(node_id)
    creatable, why = cockpit.state(env).materializer.provisionable(node_id)
    closure = closure_of(node_id, nodes)

    return {
        # Drawn whenever there is something to draw. A standalone resource gets the sentence, which
        # for "nothing has to exist first" is the whole of what there is to say.
        "graph": build_graph(nodes, node_id, status) if len(closure) > GRAPH_FROM else None,
        "lineage": lineage_sentence(node, nodes),
        "needs": [nodes[dep] for dep in node.depends_on if dep in nodes],
        "needed_by": [nodes[dep] for dep in node.dependents if dep in nodes],
        "specs": found.specs_for_resource(node_id),
        "payload": _payload(node.body),
        "identity": entry.identity or "",
        "state": entry.state,
        "detail": entry.detail,
        "node_label": _node_label(node, closure),
        "node_blocked": "" if creatable else why,
    }


def _type_context(env: str, view: TypeView | None, status: Statuses) -> dict[str, Any]:
    if view is None:
        return {
            "type_targets": [],
            "type_label": "Provision",
            "type_blocked": "this catalog declares no resource types yet",
        }

    engine = app().state(env).materializer
    targets = [
        node.id
        for node in view.nodes
        if status.of(node.id).missing and engine.provisionable(node.id)[0]
    ]
    return {
        "type_targets": targets,
        "type_label": f"Provision {plural(len(targets), view.name)}",
        "type_blocked": _type_blocked(env, view, targets),
    }


def _type_blocked(env: str, view: TypeView, targets: list[str]) -> str:
    """Why the type-wide action is off — never an unexplained grey button."""
    if targets:
        return ""
    if not view.nodes:
        return f"no {view.name} is declared in the catalog yet"
    refusals = {app().state(env).materializer.provisionable(node.id)[1] for node in view.nodes}
    refusals.discard("")
    if refusals:
        return sorted(refusals)[0]
    return f"every {view.name} already exists in {env}"


# ---- what this environment already has -------------------------------------


@dataclass
class ScopeChoice:
    """A parent resource a scoped listing can be browsed inside."""

    node: Node
    identity: str = ""
    reason: str = ""


@dataclass
class EnvRow:
    """One record the environment already holds, and the node that declares it, if any."""

    identity: str
    cells: list[str]
    node: Node | None = None


@dataclass
class EnvRecords:
    """What browsing a type found, and — when it found nothing — which of the honest reasons applies."""

    type_name: str = ""
    id_field: str = "id"
    columns: list[str] = field(default_factory=list)
    rows: list[EnvRow] = field(default_factory=list)
    browsable: bool = True
    scope_fields: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    choices: list[ScopeChoice] = field(default_factory=list)
    scope: Node | None = None
    error: str = ""
    truncated: bool = False

    @property
    def declared(self) -> int:
        return sum(1 for row in self.rows if row.node is not None)

def environment_records(env: str, view: TypeView | None, scope_id: str = "") -> EnvRecords:
    """Every record of `view`'s type that `env` already holds, marked with what the catalog declares.

    Browsing is optional for an adapter and sometimes needs a parent named first. Both come back as
    facts on the result — `browsable`, `needs` — for the page to state.
    """
    engine = app().state(env).materializer
    if view is None:
        return EnvRecords(browsable=False)

    out = EnvRecords(type_name=view.name, id_field=view.id_field, scope_fields=view.spec.browse_fields)
    adapter = engine.adapters.get(view.system)
    if adapter is None:
        out.error = f"No adapter for {view.system!r} in {env}, so ATF cannot see what is out there."
        return out
    if not can_browse(adapter):
        out.browsable = False
        return out

    scope: dict[str, Any] | None = None
    if out.scope_fields:
        out.choices = _scope_choices(env, engine.catalog, view, out.scope_fields[0])
        out.scope = engine.nodes.get(scope_id)
        if out.scope is None:
            out.needs = list(out.scope_fields)
            return out
        identity = _identities(env).get(out.scope.id)
        if identity in (None, ""):
            out.needs = list(out.scope_fields)
            out.error = (
                f"{out.scope.name} is not in {env} yet, so there is nothing inside it to list. Provision it first."
            )
            return out
        scope = {out.scope_fields[0]: identity}

    try:
        records = engine.browse(view.name, limit=BROWSE_LIMIT, scope=scope)
    except ScopeRequired as exc:
        out.needs = list(exc.fields)
        return out
    except Exception as exc:  # noqa: BLE001 - reported beside the table; browsing must not 500 a page
        out.error = first_line(exc)
        return out

    out.columns = _columns(records, view.id_field, view.spec.natural_keys)
    out.truncated = len(records) >= BROWSE_LIMIT
    by_identity, by_key = _declared(env, engine, view)
    for record in records:
        identity = record.get(view.id_field)
        out.rows.append(
            EnvRow(
                identity="" if identity is None else str(identity),
                cells=[_cell(record.get(column)) for column in out.columns],
                node=by_identity.get(str(identity)) or by_key.get(view.spec.signature(record)),
            )
        )
    return out


@dataclass
class InstanceRow:
    """One row of a type's single table: a resource the catalog declares, or one only `env` has.

    They were two tables and a nav entry for the same eight things. Whether a resource is declared
    is one column of one table, and it is the column that says what to do about it.
    """

    label: str
    status: str
    detail: str
    node: Node | None = None
    identity: str = ""

    @property
    def declared(self) -> bool:
        return self.node is not None


def instance_rows(view: TypeView | None, status: Statuses, records: EnvRecords | None) -> list[InstanceRow]:
    """Everything of this type: what the catalog declares first, then what only the environment has."""
    if view is None:
        return []
    rows = [
        InstanceRow(
            label=node.name,
            status=status.state(node.id),
            detail=node.represents,
            node=node,
            identity=str(status.identity(node.id) or ""),
        )
        for node in view.nodes
    ]

    if records is None:
        return rows

    keys = view.spec.remote_keys
    at = {name: position for position, name in enumerate(records.columns)}
    for row in records.rows:
        if row.node is not None:
            continue
        named = [row.cells[at[key]] for key in keys if key in at and row.cells[at[key]]]
        rest = [
            f"{name} {row.cells[position]}"
            for name, position in at.items()
            if name not in keys and name != records.id_field and row.cells[position]
        ]
        rows.append(
            InstanceRow(
                label=" · ".join(named) or row.identity or "no identity",
                status=UNDECLARED,
                detail=", ".join(rest[:MAX_COLUMNS]),
                identity=row.identity,
            )
        )
    return rows


def instance_files() -> list[str]:
    """The instance files a new resource could be declared in — the type registry is not one of them."""
    root = app().manifest.catalog_dir
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.glob("*.yaml") if path.name != TYPES_FILE)


def _identities(env: str) -> dict[str, Any]:
    """Every node's identity out there, taken from the status the page has already read."""
    return app().status.of(env).identities()


def _declared(
    env: str,
    engine: Materializer,
    view: TypeView,
) -> tuple[dict[str, Node], dict[tuple[str, ...] | None, Node]]:
    """Two ways to recognise a declared record: by the identity it has here, or by its natural key."""
    identities = _identities(env)
    by_identity: dict[str, Node] = {}
    by_key: dict[tuple[str, ...] | None, Node] = {}
    for node in view.nodes:
        identity = identities.get(node.id)
        if identity not in (None, ""):
            by_identity.setdefault(str(identity), node)
        try:
            values = tuple(str(engine.resolve(node.body[key])) for key in view.spec.natural_keys)
        except (KeyError, Unresolved):
            continue
        if values:
            by_key.setdefault(values, node)
    return by_identity, by_key


def _scope_choices(
    env: str,
    catalog: Catalog,
    view: TypeView,
    scope_field: str,
) -> list[ScopeChoice]:
    """The parents this listing can be browsed inside: every node of the type that supplies the field.

    Which type that is comes from the catalog itself — an existing instance points at its parent
    with a `${...id}` placeholder — and only failing that from the field's name.
    """
    parent_types: list[str] = []
    for node in view.nodes:
        for referenced in sorted(references(node.body.get(scope_field))):
            target = catalog.nodes.get(referenced)
            if target is not None and target.resource not in parent_types:
                parent_types.append(target.resource)
    guessed = _FOREIGN_KEY.sub("", scope_field)
    if not parent_types and guessed in catalog.types:
        parent_types.append(guessed)

    identities = _identities(env)
    choices: list[ScopeChoice] = []
    for node in sorted(catalog.nodes.values(), key=lambda item: item.name):
        if node.resource not in parent_types:
            continue
        identity = identities.get(node.id)
        choices.append(
            ScopeChoice(
                node=node,
                identity="" if identity in (None, "") else str(identity),
                reason="" if identity not in (None, "") else f"not in {env} yet — provision it first",
            )
        )
    return choices


def _columns(records: list[dict[str, Any]], id_field: str, keys: list[str]) -> list[str]:
    """Identity first, then the natural key, then whatever else the records carry."""
    ordered: list[str] = []
    for name in [id_field, *keys]:
        if name not in ordered and any(name in record for record in records):
            ordered.append(name)
    for record in records:
        for name in record:
            if str(name) not in ordered:
                ordered.append(str(name))
    return ordered[:MAX_COLUMNS]


def _cell(value: Any) -> str:
    """A record's value as the backend spells it — `false`, not Python's `False`."""
    if value is None:
        return ""
    text = json.dumps(value, default=str) if isinstance(value, dict | list | bool) else str(value)
    return text if len(text) <= CELL_CHARS else text[: CELL_CHARS - 1] + "…"



def _node_label(node: Node, closure: list[str]) -> str:
    """Provisioning always provisions the closure, so the button says so before you press it."""
    others = len(closure) - 1
    if others <= 0:
        return f"Provision {node.name}"
    count = "1 dependency" if others == 1 else f"{others} dependencies"
    return f"Provision {node.name} + {count}"


def _payload(body: dict[str, Any]) -> Markup:
    """The declared body, with `${...}` placeholders marked — they are the part resolved at runtime."""
    text = html.escape(json.dumps(body, indent=2, default=str), quote=False)
    return Markup(PLACEHOLDER.sub(lambda match: f'<span class="ref">{match.group(0)}</span>', text))


def _param(request: Request, name: str, given: str | None) -> str:
    return given if given is not None else (request.query_params.get(name) or "")

