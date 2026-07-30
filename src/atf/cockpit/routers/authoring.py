"""Authoring the catalog: create a resource, copy one, edit one, delete one.

Editing the catalog is a change to the suite's source, not to an environment — the same edit would
be the same edit whichever environment the cockpit is pointed at. So `mutable_envs` does not gate
anything here; a read-only environment can still have its catalog authored. Every route that writes
is confirmed, and every path written to is derived from the manifest's `catalog_dir`, never from the
form.

One path applies every change: propose the whole new file text, write it, load the entire catalog
back, and restore the original bytes if it no longer loads. The cockpit must never leave a catalog
that does not load. The proposal is shown as a diff before it is applied, because a reader who
follows the diff learns the YAML format, which is worth as much as the edit.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request

from ...adapters import registered_systems
from ...authoring import AuthoringError, Derived, check_name, derive, diff, insert, remove, replace
from ...catalog import TYPES_FILE, Catalog, CatalogError, Node, load_catalog
from ...materializer import Materializer, ScopeRequired
from ..view import cockpit as app
from ..view import current_env, page, partial, require_confirmation, type_views
from .catalog import BROWSE_LIMIT, context, instance_files

router = APIRouter(prefix="/authoring")

SHEET = "partials/resource_form.html"
CHANGE = "partials/proposed_change.html"

CREATE = "create"
EDIT = "edit"
DELETE = "delete"

# Blank rows so the key/value body can be added to without any scripting.
SPARE_ROWS = 3

# Read as a literal rather than as text, so `done: false` is a boolean and `count: 3` a number.
# Deliberately narrow: a date-shaped string stays the string the backend was given.
LITERALS: dict[str, Any] = {"true": True, "false": False, "yes": True, "no": False, "null": None, "~": None}
NUMBER = re.compile(r"[+-]?(\d+|\d*\.\d+)([eE][+-]?\d+)?")

TYPE = Query(default="", alias="type")
SCOPE = Query(default="")
IDENTITY = Query(default="")

F_ACTION = Form(default=CREATE)
F_TYPE = Form(default="", alias="type")
F_NODE = Form(default="")
F_NAME = Form(default="")
F_FILE = Form(default="")
F_REPRESENTS = Form(default="")
F_DEPENDS = Form(default=[])
F_BODY_MODE = Form(default="rows")
F_KEYS = Form(default=[])
F_VALUES = Form(default=[])
F_YAML = Form(default="")
F_CONFIRM = Form(default="")


# ---- the shape of a proposed change ----------------------------------------


@dataclass
class Draft:
    """A form's worth of intent, before it is turned into YAML. Whole-form, so preview and write agree."""

    action: str = CREATE
    resource_type: str = ""
    node_id: str = ""
    name: str = ""
    file: str = ""
    represents: str = ""
    depends_on: list[str] = field(default_factory=list)
    body_mode: str = "rows"
    keys: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    body_yaml: str = ""

    @property
    def rows(self) -> list[tuple[str, str]]:
        return list(zip(self.keys, self.values, strict=False))


@dataclass
class Proposal:
    """One instance file, before and after. Nothing here has been written."""

    action: str
    name: str
    path: Path
    before: str
    after: str
    entry: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    blocked: str = ""

    @property
    def label(self) -> str:
        """The file as a reader of the suite names it, never an absolute path off this machine."""
        root = app().manifest.root
        try:
            return str(self.path.relative_to(root))
        except ValueError:
            return self.path.name

    @property
    def lines(self) -> list[tuple[str, str]]:
        return diff_lines(diff(self.before, self.after, self.label))


def diff_lines(text: str) -> list[tuple[str, str]]:
    """A unified diff as (class, line) pairs, because the diff is rendered one div per line."""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith(("+++", "---", "@@")):
            out.append(("meta", line))
        elif line.startswith("+"):
            out.append(("add", line))
        elif line.startswith("-"):
            out.append(("del", line))
        else:
            out.append(("", line))
    return out


def draft_form(
    action: str = F_ACTION,
    resource_type: str = F_TYPE,
    node: str = F_NODE,
    name: str = F_NAME,
    file: str = F_FILE,
    represents: str = F_REPRESENTS,
    depends_on: list[str] = F_DEPENDS,
    body_mode: str = F_BODY_MODE,
    body_key: list[str] = F_KEYS,
    body_value: list[str] = F_VALUES,
    body_yaml: str = F_YAML,
) -> Draft:
    return Draft(
        action=action,
        resource_type=resource_type,
        node_id=node,
        name=name.strip(),
        file=file.strip(),
        represents=represents.strip(),
        depends_on=list(depends_on),
        body_mode=body_mode,
        keys=list(body_key),
        values=list(body_value),
        body_yaml=body_yaml,
    )


DRAFT = Depends(draft_form)


# ---- reading the form: what the catalog would say ---------------------------


def build(draft: Draft, env: str) -> Proposal:
    """The proposed file text for a draft. Raises `AuthoringError` for anything unwritable."""
    engine = app().state(env).materializer
    nodes = engine.nodes

    if draft.action == DELETE:
        node = _known(nodes, draft.node_id)
        path = _node_path(node)
        after = remove(path, node.name)
        blocked = _dependents_block(node, nodes)
        return Proposal(
            action=DELETE,
            name=node.name,
            path=path,
            before=path.read_text(encoding="utf-8"),
            after=after,
            problems=[] if blocked else would_break(path, after),
            blocked=blocked,
        )

    if draft.action == EDIT:
        node = _known(nodes, draft.node_id)
        resource_type, name, path = node.resource, node.name, _node_path(node)
    else:
        resource_type, name = draft.resource_type, draft.name
        if resource_type not in engine.types:
            raise AuthoringError(f"no resource type {resource_type!r} is declared in this catalog")
        check_name(name, resource_type, nodes)
        path = _instance_path(draft.file or default_file(nodes, resource_type))

    entry = Derived(
        name=name,
        resource=resource_type,
        body=body_of(draft),
        depends_on=_dependencies(draft.depends_on, nodes, exclude=draft.node_id),
        represents=draft.represents,
    ).as_entry()

    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = replace(path, name, entry) if draft.action == EDIT else insert(path, name, entry)
    return Proposal(
        action=draft.action,
        name=name,
        path=path,
        before=before,
        after=after,
        entry=entry,
        problems=would_break(path, after),
    )


def body_of(draft: Draft) -> dict[str, Any]:
    """The body a draft declares: key/value rows, or raw YAML for anything with structure."""
    if draft.body_mode == "yaml":
        text = draft.body_yaml.strip()
        if not text:
            return {}
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise AuthoringError(f"the body is not valid YAML: {str(exc).splitlines()[0]}") from exc
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise AuthoringError("the body must be a mapping of field name to value")
        return parsed

    body: dict[str, Any] = {}
    for key, value in draft.rows:
        field_name = key.strip()
        if field_name:
            body[field_name] = literal(value)
    return body


def literal(text: str) -> Any:
    """A form field as the value it means. Only booleans, numbers and null — everything else is text."""
    stripped = text.strip()
    if stripped.lower() in LITERALS:
        return LITERALS[stripped.lower()]
    if NUMBER.fullmatch(stripped):
        return float(stripped) if {".", "e", "E"} & set(stripped) else int(stripped)
    return text


def as_text(value: Any) -> str:
    """A declared value back in a form field, in the spelling `literal` reads again."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return yaml.safe_dump(value, default_flow_style=True).strip()
    return str(value)


def _dependencies(chosen: list[str], nodes: dict[str, Node], exclude: str = "") -> list[str]:
    ordered: list[str] = []
    for node_id in chosen:
        if node_id in ordered or not node_id:
            continue
        if node_id not in nodes:
            raise AuthoringError(f"{node_id!r} is not a resource in this catalog, so nothing can depend on it")
        if node_id == exclude:
            raise AuthoringError(f"{node_id} cannot depend on itself")
        ordered.append(node_id)
    return ordered


def _known(nodes: dict[str, Node], node_id: str) -> Node:
    node = nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"no resource {node_id!r} is declared in this catalog")
    return node


def _dependents_block(node: Node, nodes: dict[str, Node]) -> str:
    """Why this node cannot go: something else lists it in `depends_on`, which would be left dangling."""
    dependents = [nodes[dep].id for dep in node.dependents if dep in nodes]
    if not dependents:
        return ""
    return (
        f"{', '.join(dependents)} depend{'s' if len(dependents) == 1 else ''} on {node.id}. "
        "Deleting it would leave that depends_on pointing at nothing, so the catalog would stop loading. "
        "Delete or repoint them first."
    )


# ---- paths: always inside the catalog directory ----------------------------


def default_file(nodes: dict[str, Node], resource_type: str) -> str:
    """Where a new instance lands: beside an existing one of its type, else a file named for the type."""
    for node in sorted(nodes.values(), key=lambda item: item.name):
        if node.resource == resource_type:
            return f"{node.collection}.yaml"
    return f"{resource_type}s.yaml"


def _instance_path(name: str) -> Path:
    """A file name from the form, resolved inside `catalog_dir` — or refused.

    The stem becomes the first half of every node id declared in it, so it has to be a plain
    catalog file name. Anything naming a directory is refused rather than quietly stripped: a form
    asking to write outside the catalog is not a request to honour in a different place.
    """
    root = app().manifest.catalog_dir
    given = name.strip()
    stem = given[: -len(".yaml")] if given.endswith(".yaml") else given
    if not stem or stem != Path(stem).name or stem.startswith("."):
        raise AuthoringError(f"{given!r} is not a catalog file name — a resource can only be declared in {root.name}/")
    if not stem.replace("_", "").isalnum() or not stem[0].isalpha():
        raise AuthoringError(
            f"{stem!r} cannot name a collection — use lower case, digits and underscores, starting with a letter"
        )
    if f"{stem}.yaml" == TYPES_FILE:
        raise AuthoringError(f"{TYPES_FILE} is the resource-type registry, not a place for instances")

    path = (root / f"{stem}.yaml").resolve()
    if path.parent != root.resolve():
        raise AuthoringError(f"{given!r} resolves outside {root.name}/, so nothing will be written to it")
    return path


def _node_path(node: Node) -> Path:
    """The file a node is already declared in — read from the catalog, never from the form."""
    return (app().manifest.catalog_dir / f"{node.collection}.yaml").resolve()


# ---- validation and the one write path -------------------------------------


def would_break(path: Path, text: str) -> list[str]:
    """Every problem a proposed file would introduce, found on a copy so nothing is written.

    The same check the write path runs, run early: a name that clashes or a `${...}` reference with
    no `depends_on` is worth reading in the panel before the button is pressed, not after.
    """
    root = app().manifest.catalog_dir
    if not root.is_dir():
        return [f"catalog directory {root} does not exist"]
    with tempfile.TemporaryDirectory() as tmp:
        mirror = Path(tmp) / root.name
        shutil.copytree(root, mirror)
        (mirror / path.name).write_text(text, encoding="utf-8")
        try:
            load_catalog(mirror, registered_systems())
        except CatalogError as exc:
            return list(exc.problems)
    return []


def apply(env: str, proposal: Proposal) -> None:
    """Write the proposal, prove the whole catalog still loads, and roll back byte-for-byte if not."""
    if proposal.blocked:
        raise HTTPException(status_code=409, detail=proposal.blocked)

    path = proposal.path
    original = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proposal.after, encoding="utf-8")
    try:
        load_catalog(app().manifest.catalog_dir, registered_systems())
    except CatalogError as exc:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        detail = f"{proposal.label} was left as it was — that change would stop the catalog loading: " + "; ".join(
            exc.problems
        )
        raise HTTPException(status_code=409, detail=detail) from exc

    # The catalog is source, not environment state: the edit applies to every environment, so no
    # environment gets to keep a materializer holding the catalog as it was.
    app().invalidate_all()


# ---- routes: open a sheet --------------------------------------------------


@router.get("/new")
def new(request: Request, resource_type: str = TYPE, identity: str = IDENTITY, scope: str = SCOPE) -> Any:
    """The create form for a type, empty — or filled in from a record the environment already has."""
    env = current_env(request)
    engine = app().state(env).materializer
    if resource_type not in engine.types:
        raise HTTPException(status_code=404, detail=f"no resource type {resource_type!r} is declared in this catalog")

    derived = _from_record(env, resource_type, identity, scope) if identity else None
    draft = Draft(
        action=CREATE,
        resource_type=resource_type,
        name=derived.name if derived else "",
        file=default_file(engine.nodes, resource_type),
        represents=derived.represents if derived else "",
        depends_on=list(derived.depends_on) if derived else [],
    )
    body = derived.body if derived else dict.fromkeys(engine.spec(resource_type).natural_keys, "")
    return _sheet(request, env, draft, body, dropped=derived.dropped if derived else [], identity=identity)


@router.get("/copy/{node_id}")
def copy(request: Request, node_id: str) -> Any:
    """Everything from an existing resource under a new name — the cheap way to stop sharing one."""
    env = current_env(request)
    node = _known(app().state(env).materializer.nodes, node_id)
    draft = Draft(
        action=CREATE,
        resource_type=node.resource,
        name=_free_name(node, app().state(env).materializer.catalog),
        file=f"{node.collection}.yaml",
        represents=node.represents,
        depends_on=list(node.depends_on),
    )
    return _sheet(request, env, draft, dict(node.body), source=node)


@router.get("/edit/{node_id}")
def edit(request: Request, node_id: str) -> Any:
    env = current_env(request)
    node = _known(app().state(env).materializer.nodes, node_id)
    draft = Draft(
        action=EDIT,
        resource_type=node.resource,
        node_id=node.id,
        name=node.name,
        file=f"{node.collection}.yaml",
        represents=node.represents,
        depends_on=list(node.depends_on),
    )
    return _sheet(request, env, draft, dict(node.body), source=node)


@router.get("/delete/{node_id}")
def confirm_delete(request: Request, node_id: str) -> Any:
    env = current_env(request)
    node = _known(app().state(env).materializer.nodes, node_id)
    draft = Draft(action=DELETE, resource_type=node.resource, node_id=node.id, name=node.name)
    return _sheet(request, env, draft, dict(node.body), source=node)


# ---- routes: propose, then write -------------------------------------------


@router.post("/preview")
def preview(request: Request, draft: Draft = DRAFT) -> Any:
    """The diff this form would write. A read: it proposes text and touches no file."""
    env = current_env(request)
    proposal, problems = _proposed(env, draft)
    return partial(request, CHANGE, proposal=proposal, problems=problems, action=draft.action)


@router.post("/write")
def write(request: Request, draft: Draft = DRAFT, confirm: str = F_CONFIRM) -> Any:
    """Create or edit one resource. Gated by confirmation, not by `mutable_envs`."""
    require_confirmation(confirm)
    env = current_env(request)
    if draft.action not in {CREATE, EDIT}:
        raise HTTPException(status_code=409, detail=f"{draft.action!r} is not a change this route can write")

    proposal = _or_refuse(env, draft)
    resource_type = str(proposal.entry.get("resource", ""))
    apply(env, proposal)

    verb = "Added" if proposal.action == CREATE else "Updated"
    banner = f"{verb} the {resource_type} {proposal.name} in {proposal.label}."
    return _reload(request, env, banner, focus=f"{proposal.path.stem}.{proposal.name}", type_name=resource_type)


@router.post("/remove")
def delete(request: Request, node: str = F_NODE, confirm: str = F_CONFIRM) -> Any:
    """Delete one resource, unless something in the catalog still depends on it."""
    require_confirmation(confirm)
    env = current_env(request)
    known = _known(app().state(env).materializer.nodes, node)
    resource_type = known.resource

    proposal = _or_refuse(env, Draft(action=DELETE, node_id=node))
    apply(env, proposal)

    banner = f"Deleted the {resource_type} {proposal.name} from {proposal.label}."
    return _reload(request, env, banner, focus="", type_name=resource_type)


# ---- rendering -------------------------------------------------------------


def _sheet(
    request: Request,
    env: str,
    draft: Draft,
    body: dict[str, Any],
    dropped: list[str] | None = None,
    source: Node | None = None,
    identity: str = "",
) -> Any:
    """One overlay for all four verbs: the form, the reason it exists, and the diff it would write."""
    engine = app().state(env).materializer
    structured = any(isinstance(value, dict | list) for value in body.values())
    draft.body_mode = "yaml" if structured else "rows"
    draft.keys = [str(key) for key in body]
    draft.values = [as_text(value) for value in body.values()]
    draft.body_yaml = yaml.safe_dump(body, sort_keys=False, allow_unicode=True).strip() if body else ""

    proposal, problems = _proposed(env, draft)
    return partial(
        request,
        SHEET,
        action=draft.action,
        draft=draft,
        source=source,
        type=_view(env, draft.resource_type),
        rows=draft.rows + [("", "")] * SPARE_ROWS,
        choices=_choices(engine.nodes, exclude=draft.node_id),
        files=instance_files(),
        dropped=dropped or [],
        identity=identity,
        structured=structured,
        proposal=proposal,
        problems=problems,
    )


def _reload(request: Request, env: str, banner: str, focus: str, type_name: str) -> Any:
    """After a write, re-render the whole catalog: the list, the selection and the counts all moved."""
    nodes = app().state(env).materializer.nodes
    ctx = context(
        request,
        env,
        focus=focus if focus in nodes else "",
        type_name=type_name,
        banner=banner,
        banner_tone="ok",
    )
    return page(request, "catalog.html", **ctx)


def _proposed(env: str, draft: Draft) -> tuple[Proposal | None, list[str]]:
    """The proposal, or the reasons there is not one — both belong in the same panel.

    A form with no name yet has not been got wrong, it has not been filled in, so it is not worth
    a complaint: the panel says what will appear there instead.
    """
    if draft.action == CREATE and not draft.name:
        return None, []
    try:
        proposal = build(draft, env)
    except AuthoringError as exc:
        return None, [str(exc)]
    return proposal, proposal.problems


def _or_refuse(env: str, draft: Draft) -> Proposal:
    try:
        proposal = build(draft, env)
    except AuthoringError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if proposal.problems:
        raise HTTPException(
            status_code=409,
            detail=f"nothing was written — that change would stop the catalog loading: {'; '.join(proposal.problems)}",
        )
    return proposal


def _view(env: str, resource_type: str) -> Any:
    return type_views(env).get(resource_type)


def _choices(nodes: dict[str, Node], exclude: str = "") -> dict[str, list[Node]]:
    """Every node a resource could depend on, grouped by type so a long list stays navigable."""
    grouped: dict[str, list[Node]] = {}
    for node in sorted(nodes.values(), key=lambda item: item.name):
        if node.id != exclude:
            grouped.setdefault(node.resource, []).append(node)
    return dict(sorted(grouped.items()))


def _free_name(node: Node, catalog: Catalog) -> str:
    """A suggestion that says what the copy is for: `groceries_copy`, then `_copy_2` if that is taken."""
    taken = {one.name for one in catalog.of_type(node.resource)}
    stem = f"{node.name}_copy"
    if stem not in taken:
        return stem
    suffix = 2
    while f"{stem}_{suffix}" in taken:
        suffix += 1
    return f"{stem}_{suffix}"


def _from_record(env: str, resource_type: str, identity: str, scope_id: str) -> Derived:
    """The node that would have produced a record out there, found by browsing for it again.

    The record is re-read rather than carried through the form: what the catalog declares has to
    come from the environment, not from whatever a page happened to post back.
    """
    engine = app().state(env).materializer
    spec = engine.spec(resource_type)
    scope = _scope_of(env, engine, resource_type, engine.nodes.get(scope_id))
    try:
        records = engine.browse(resource_type, limit=BROWSE_LIMIT, scope=scope)
    except ScopeRequired as exc:
        raise HTTPException(
            status_code=409,
            detail=f"listing {resource_type} needs {', '.join(exc.fields)} — choose a parent on the type page first",
        ) from exc

    record = next((item for item in records if str(item.get(spec.id_field)) == identity), None)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"{env} has no {resource_type} with {spec.id_field} {identity!r} any more — rescan and try again",
        )

    identities = app().status.of(env).identities()
    return derive(record, spec, engine.nodes, identities)


def _scope_of(env: str, engine: Materializer, resource_type: str, scope: Node | None) -> dict[str, Any] | None:
    fields = engine.spec(resource_type).browse_fields
    if not fields or scope is None:
        return None
    identity = app().status.of(env).identity(scope.id)
    return None if identity in (None, "") else {fields[0]: identity}
