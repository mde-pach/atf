"""Catalog node model, loader and validation. Import-safe: never touches the network."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict

import yaml

from . import providers
from .placeholders import PLACEHOLDER_RE, Unresolved, references
from .placeholders import generated as is_generated

TYPES_FILE = "resources.yaml"
UNIVERSAL_TYPE_KEYS = frozenset({"system", "mode", "lifecycle", "id_field"})
# What ATF is being asked to do about a resource.
#
# `create` makes it exist. `reference` is a precondition ATF *cannot* create — an account someone
# else provisioned — so an absent one blocks, and that blocking is the whole point of the mode.
# `data` is neither: it is an observation, something to look at and make claims about, and an
# absent one means only that it is not there yet. Conflating the last two would make every page a
# scenario reads into a precondition the environment has to satisfy first.
# Verbs ATF has of its own, which a type may not redefine. `delete` is in the required SPI, so
# every adapter has one and `When I delete the …` needs no declaration; declaring one under that
# name could only mean two different things by the same word.
BUILT_IN_ACTIONS = frozenset({"delete"})

CREATE, REFERENCE, DATA = "create", "reference", "data"
MODES = frozenset({CREATE, REFERENCE, DATA})
LIFECYCLES = frozenset({"persistent", "ephemeral"})

# The plugin generates one fixture per resource type, named after the type. These names are
# already taken, so a type using one would shadow it silently.
PYTEST_BUILTIN_FIXTURES = frozenset(
    {
        "cache",
        "capfd",
        "capfdbinary",
        "caplog",
        "capsys",
        "capsysbinary",
        "doctest_namespace",
        "monkeypatch",
        "pytestconfig",
        "record_property",
        "record_testsuite_property",
        "recwarn",
        "request",
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
    }
)
ATF_FIXTURES = frozenset({"api", "client_config", "context", "env", "materializer"})
RESERVED_FIXTURE_NAMES = PYTEST_BUILTIN_FIXTURES | ATF_FIXTURES


class Node(TypedDict):
    id: str
    collection: str
    name: str
    resource: str
    system: str
    mode: str
    lifecycle: str
    id_field: str
    config: dict[str, Any]
    represents: str
    depends_on: list[str]
    dependents: list[str]
    body: dict[str, Any]


class CatalogError(Exception):
    """Every problem found while loading a catalog, reported at once."""

    def __init__(self, problems: list[str], root: Path | None = None) -> None:
        self.problems = problems
        where = f"{root}: " if root else ""
        super().__init__(f"{where}invalid catalog:\n  - " + "\n  - ".join(problems))


def load_catalog(
    root: Path,
    registered_systems: set[str] | None = None,
    reserved_names: set[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Node]]:
    root = Path(root)
    reserved = RESERVED_FIXTURE_NAMES if reserved_names is None else frozenset(reserved_names)
    problems: list[str] = []

    if not root.is_dir():
        raise CatalogError([f"catalog directory {root} does not exist"])

    types = _load_types(root, reserved, problems)
    nodes = _load_nodes(root, types, problems)

    _link_dependents(nodes, problems)
    _check_placeholders(nodes, problems)
    _check_generated_keys(nodes, problems)
    _check_systems(types, registered_systems, problems)
    _check_unique_names(nodes, problems)
    _check_acyclic(nodes, problems)

    if problems:
        raise CatalogError(problems, root)
    return types, nodes


def _read_yaml_mapping(path: Path, problems: list[str]) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        problems.append(f"{path.name}: invalid YAML: {exc}")
        return {}
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append(f"{path.name}: must be a mapping")
        return {}
    return raw


def _load_types(root: Path, reserved: frozenset[str], problems: list[str]) -> dict[str, dict[str, Any]]:
    path = root / TYPES_FILE
    if not path.is_file():
        problems.append(f"{TYPES_FILE} is missing (the resource-type registry)")
        return {}

    raw = _read_yaml_mapping(path, problems)
    types: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        name = str(key)
        if not isinstance(entry, dict):
            problems.append(f"{TYPES_FILE}: type {name!r} must be a mapping")
            continue
        if name in reserved:
            problems.append(
                f"{TYPES_FILE}: type {name!r} collides with the reserved fixture name {name!r}; "
                "rename the resource type"
            )
        if not isinstance(entry.get("system"), str) or not entry.get("system"):
            problems.append(f"{TYPES_FILE}: type {name!r} needs a `system` string")
        mode = entry.get("mode", "create")
        if mode not in MODES:
            problems.append(f"{TYPES_FILE}: type {name!r} has mode {mode!r}, expected one of {sorted(MODES)}")
        lifecycle = entry.get("lifecycle", "persistent")
        if lifecycle not in LIFECYCLES:
            problems.append(
                f"{TYPES_FILE}: type {name!r} has lifecycle {lifecycle!r}, expected one of {sorted(LIFECYCLES)}"
            )
        _check_actions(name, entry.get("actions"), problems)
        types[name] = entry
    return types


def _check_actions(name: str, actions: Any, problems: list[str]) -> None:
    """`actions:` names what can be *done* to a resource, in terms its adapter understands.

    ATF validates the shape and nothing else: an action's body is adapter configuration, exactly as
    `path` and `natural_key` are, and reading anything into it here would be the framework deciding
    what a system can do.
    """
    if actions is None:
        return
    if not isinstance(actions, dict):
        problems.append(f"{TYPES_FILE}: type {name!r} has `actions` that is not a mapping of name to what it does")
        return
    for action, body in actions.items():
        if not isinstance(action, str) or not action:
            problems.append(f"{TYPES_FILE}: type {name!r} has an action whose name is not text")
            continue
        if action in BUILT_IN_ACTIONS:
            problems.append(
                f"{TYPES_FILE}: type {name!r} declares an action called {action!r}, which is one ATF "
                "already performs — pick another name, or drop the declaration and use ATF's"
            )
        if not isinstance(body, dict):
            problems.append(
                f"{TYPES_FILE}: type {name!r} action {action!r} must be a mapping of what its adapter "
                "should do"
            )


def _load_nodes(root: Path, types: dict[str, dict[str, Any]], problems: list[str]) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    for path in sorted(root.glob("*.yaml")):
        if path.name == TYPES_FILE:
            continue
        collection = path.stem
        raw = _read_yaml_mapping(path, problems)
        for key, entry in raw.items():
            name = str(key)
            nid = f"{collection}.{name}"
            if entry is None:
                entry = {}
            if not isinstance(entry, dict):
                problems.append(f"{nid}: instance must be a mapping")
                continue
            node = _build_node(nid, collection, name, entry, types, problems)
            if node is not None:
                nodes[nid] = node
    return nodes


def _build_node(
    nid: str,
    collection: str,
    name: str,
    entry: dict[str, Any],
    types: dict[str, dict[str, Any]],
    problems: list[str],
) -> Node | None:
    resource = entry.get("resource")
    if not isinstance(resource, str) or not resource:
        problems.append(f"{nid}: needs a `resource` naming its type")
        return None
    type_entry = types.get(resource)
    if type_entry is None:
        problems.append(f"{nid}: unknown resource type {resource!r} (not in {TYPES_FILE})")
        return None

    depends_on = entry.get("depends_on") or []
    if isinstance(depends_on, str):
        depends_on = [depends_on]
    if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
        problems.append(f"{nid}: depends_on must be a list of node ids")
        depends_on = []

    body = entry.get("body") or {}
    if not isinstance(body, dict):
        problems.append(f"{nid}: body must be a mapping")
        body = {}

    represents = entry.get("represents") or ""
    if not isinstance(represents, str):
        problems.append(f"{nid}: represents must be a string")
        represents = ""

    config = {k: v for k, v in type_entry.items() if k not in UNIVERSAL_TYPE_KEYS}
    return Node(
        id=nid,
        collection=collection,
        name=name,
        resource=resource,
        system=str(type_entry.get("system", "")),
        mode=str(type_entry.get("mode", "create")),
        lifecycle=str(type_entry.get("lifecycle", "persistent")),
        id_field=str(type_entry.get("id_field", "id")),
        config=config,
        represents=represents,
        depends_on=list(depends_on),
        dependents=[],
        body=body,
    )


def _link_dependents(nodes: dict[str, Node], problems: list[str]) -> None:
    for nid, node in nodes.items():
        for dep in node["depends_on"]:
            target = nodes.get(dep)
            if target is None:
                problems.append(f"{nid}: depends_on {dep!r}, which is not a known node")
                continue
            target["dependents"].append(nid)
    for node in nodes.values():
        node["dependents"].sort()


def _check_placeholders(nodes: dict[str, Node], problems: list[str]) -> None:
    """A `${...}` reference must name a real node, and one it declares a dependency on."""
    for nid, node in sorted(nodes.items()):
        for referenced in sorted(references(node["body"])):
            if referenced not in nodes:
                problems.append(f"{nid}: body references ${{{referenced}.id}}, which is not a known node")
            elif referenced not in node["depends_on"]:
                problems.append(
                    f"{nid}: body references ${{{referenced}.id}} but does not list it in depends_on, "
                    "so it will not be provisioned first"
                )


def _check_generated_keys(nodes: dict[str, Node], problems: list[str]) -> None:
    """A *fresh* value in a key ATF has to look up again is the one incoherent combination.

    `find` resolves the natural key and asks the backend for a match. A value that is new on every
    pass never matches, so every run creates another record and a shared environment fills up with
    them — quietly, because nothing fails. Refused here rather than seeded around: seeding would
    make a generated value into an elaborate way of writing a literal, which is not what anyone
    reaches for a generator to do.

    Which providers are fresh is theirs to say, not this function's to guess — `${now+1d 09:00}`
    in a key gives one record per day, which is exactly what someone writing it there is asking
    for. Only where the lookup happens, too: an ephemeral resource is never looked up, and a field
    outside the natural key is written once, at creation.
    """
    for nid, node in sorted(nodes.items()):
        if node["lifecycle"] == "ephemeral":
            continue
        for key in natural_keys(node["config"]):
            value = node["body"].get(key)
            if not isinstance(value, str):
                continue
            generated = [
                expression
                for expression in PLACEHOLDER_RE.findall(value)
                if is_generated(expression) and not providers.keyable(providers.split(expression)[0])
            ]
            if not generated:
                continue
            problems.append(
                f"{nid}: {key} is part of the natural key and is generated fresh "
                f"(${{{generated[0]}}}). "
                "A value that changes every run never matches what is already there, so every run "
                "would create another one. Write it out, or make the type ephemeral."
            )


def _check_systems(
    types: dict[str, dict[str, Any]],
    registered_systems: set[str] | None,
    problems: list[str],
) -> None:
    if registered_systems is None:
        return
    for name, entry in types.items():
        system = entry.get("system")
        if isinstance(system, str) and system and system not in registered_systems:
            known = ", ".join(sorted(registered_systems)) or "none"
            problems.append(
                f"{TYPES_FILE}: type {name!r} uses system {system!r} with no registered adapter (have: {known})"
            )


def _check_unique_names(nodes: dict[str, Node], problems: list[str]) -> None:
    seen: dict[tuple[str, str], list[str]] = {}
    for nid, node in nodes.items():
        seen.setdefault((node["resource"], node["name"]), []).append(nid)
    for (resource, name), ids in sorted(seen.items()):
        if len(ids) > 1:
            problems.append(f"duplicate name {name!r} for resource type {resource!r}: {', '.join(sorted(ids))}")


def _check_acyclic(nodes: dict[str, Node], problems: list[str]) -> None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes, WHITE)
    reported: set[frozenset[str]] = set()

    def visit(nid: str, path: list[str]) -> None:
        color[nid] = GREY
        path.append(nid)
        for dep in nodes[nid]["depends_on"]:
            if dep not in nodes:
                continue
            if color[dep] == GREY:
                cycle = path[path.index(dep) :] + [dep]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    problems.append("dependency cycle: " + " -> ".join(cycle))
            elif color[dep] == WHITE:
                visit(dep, path)
        path.pop()
        color[nid] = BLACK

    for nid in sorted(nodes):
        if color[nid] == WHITE:
            visit(nid, [])


def resource_types(nodes: dict[str, Node]) -> set[str]:
    return {node["resource"] for node in nodes.values()}


def natural_keys(config: dict[str, Any]) -> list[str]:
    """The body fields a resource of this type is recognised by, or `[]` if the type names none."""
    keys = config.get("natural_key")
    if isinstance(keys, str):
        return [keys]
    if isinstance(keys, list) and keys and all(isinstance(key, str) for key in keys):
        return [str(key) for key in keys]
    return []


def key_criteria(node: Node, resolve: Callable[[Any], Any]) -> dict[str, Any] | None:
    """`{the field the backend spells it as: the value expected there}` for a node's natural key.

    The one definition of "which record out there is this node", shared by the adapter deciding
    whether to create one and by a step deciding whether a record it was handed is that resource.

    `None` when the question cannot be asked yet: the type names no natural key, the body omits one
    of its fields, or a field holds a `${...}` whose dependency has no identity so far.
    """
    keys = natural_keys(node["config"])
    if not keys:
        return None

    # A single-key type may name the field differently at the backend — `natural_key: name` matched
    # against a record's `slug`. With several keys there is no one field to redirect.
    ref_field = node["config"].get("ref_field")
    criteria: dict[str, Any] = {}
    for key in keys:
        if key not in node["body"]:
            return None
        try:
            value = resolve(node["body"][key])
        except Unresolved:
            return None
        if value is None:
            return None
        criteria[str(ref_field) if (ref_field and len(keys) == 1) else key] = value
    return criteria


def find_node(nodes: dict[str, Node], resource_type: str, name: str) -> Node | None:
    for node in nodes.values():
        if node["resource"] == resource_type and node["name"] == name:
            return node
    return None
