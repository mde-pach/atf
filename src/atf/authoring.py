"""Writing the catalog: derive a node from a real record, and edit instance files in place.

Two halves. `derive` turns a record the environment already holds into the node that would have
produced it — which is how a catalog gets written against a system that predates it. `edit`,
`insert` and `remove` change one top-level entry in one instance file and leave every other byte
alone, because those files are hand-authored and their comments and ordering are part of the work.

Nothing here writes without the caller validating first: `load_catalog` reports every problem in a
proposed catalog, so a change that would stop the suite loading is refused rather than saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from typing_extensions import override

from .catalog import Node

# Fields a backend owns rather than the catalog: they appear in a record but must never be declared,
# because the backend will assign them again on the next create.
SERVER_OWNED = frozenset(
    {
        "id",
        "uuid",
        "created",
        "created_at",
        "createdat",
        "updated",
        "updated_at",
        "updatedat",
        "modified",
        "modified_at",
        "deleted_at",
        "href",
        "url",
        "self",
        "_links",
        "etag",
        "revision",
        "version",
    }
)

_NAME_OK = re.compile(r"^[a-z][a-z0-9_]*$")


class AuthoringError(Exception):
    """A proposed catalog change that must not be written."""


@dataclass
class Derived:
    """A node proposed from a record, and what had to be decided along the way."""

    name: str
    resource: str
    body: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    represents: str = ""
    dropped: list[str] = field(default_factory=list)
    identity: Any = None

    def as_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"resource": self.resource}
        if self.represents:
            entry["represents"] = self.represents
        if self.depends_on:
            entry["depends_on"] = list(self.depends_on)
        entry["body"] = self.body
        return entry


def derive(
    record: dict[str, Any],
    resource_type: str,
    type_config: dict[str, Any],
    id_field: str,
    nodes: dict[str, Node],
    identities: dict[str, Any] | None = None,
    name: str = "",
) -> Derived:
    """The catalog node that would have produced `record`.

    Server-assigned fields are dropped rather than declared. A field whose value is the identity of
    a resource already in the catalog becomes a `${...id}` placeholder and a dependency, which is
    what makes the derived node re-creatable in an empty environment instead of tied to this one.
    """
    identities = identities or {}
    by_identity = {
        str(value): node_id for node_id, value in identities.items() if value not in (None, "") and node_id in nodes
    }

    keys = _natural_keys(type_config)
    body: dict[str, Any] = {}
    depends_on: list[str] = []
    dropped: list[str] = []

    for key, value in record.items():
        lowered = str(key).lower()
        if lowered == str(id_field).lower() or lowered in SERVER_OWNED:
            dropped.append(str(key))
            continue
        # Nested structures are rarely declarable as-is; keep the natural key, drop the rest.
        if (value is None or isinstance(value, dict | list)) and str(key) not in keys:
            dropped.append(str(key))
            continue

        owner = by_identity.get(str(value))
        if owner is not None:
            body[str(key)] = f"${{{owner}.id}}"
            if owner not in depends_on:
                depends_on.append(owner)
            continue
        body[str(key)] = value

    return Derived(
        name=name or _suggest_name(record, keys, resource_type, nodes, set(by_identity)),
        resource=resource_type,
        body=body,
        depends_on=depends_on,
        dropped=dropped,
        identity=record.get(id_field),
    )


def _natural_keys(type_config: dict[str, Any]) -> list[str]:
    keys = type_config.get("natural_key")
    if isinstance(keys, str):
        return [keys]
    if isinstance(keys, list):
        return [str(key) for key in keys]
    return []


def _suggest_name(
    record: dict[str, Any],
    keys: list[str],
    resource_type: str,
    nodes: dict[str, Node],
    foreign: set[str] | None = None,
) -> str:
    """A name from what the record calls itself — never `account_1`, which says nothing.

    Human labels come before natural keys, because a composite natural key often leads with a
    foreign key: naming a list after its owner's identity would describe the parent, not the list.
    """
    foreign = foreign or set()
    candidates = ["name", "slug", "title", "label", "reference", "email", *keys]
    raw = next(
        (
            str(record[key])
            for key in candidates
            if record.get(key) not in (None, "") and str(record.get(key)) not in foreign
        ),
        resource_type,
    )
    stem = re.sub(r"[^a-z0-9]+", "_", raw.split("@")[0].lower()).strip("_") or resource_type
    taken = {node["name"] for node in nodes.values() if node["resource"] == resource_type}
    if stem not in taken:
        return stem
    suffix = 2
    while f"{stem}_{suffix}" in taken:
        suffix += 1
    return f"{stem}_{suffix}"


def check_name(name: str, resource_type: str, nodes: dict[str, Node]) -> None:
    if not _NAME_OK.match(name):
        raise AuthoringError(
            f"{name!r} is not a usable name — use lower case, digits and underscores, starting with a letter"
        )
    clash = next(
        (node["id"] for node in nodes.values() if node["resource"] == resource_type and node["name"] == name), None
    )
    if clash is not None:
        article = "an" if resource_type[:1].lower() in "aeiou" else "a"
        raise AuthoringError(f"there is already {article} {resource_type} called {name!r} ({clash})")


# ---- file surgery ----------------------------------------------------------


class _CatalogDumper(yaml.SafeDumper):
    """Indents block sequences under their key, the way the catalogs are hand-written.

    PyYAML's default is an indentless sequence, so a round-tripped `depends_on` would reindent and
    show up in the diff as a change to a value nobody touched.
    """

    @override
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, False)


def render_entry(name: str, entry: dict[str, Any], indent: int = 2) -> str:
    """One top-level catalog entry as the YAML a person would have written."""
    dumped = yaml.dump(
        {name: entry},
        Dumper=_CatalogDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        indent=indent,
    )
    return dumped.rstrip("\n") + "\n"


def block_of(text: str, name: str) -> tuple[int, int] | None:
    """The line range of a top-level entry, or None if it is not in this file.

    Catalog instance files are a mapping of name to entry, so a top-level key is a line with no
    indentation. The block runs to the next such line, keeping any trailing comment that belongs
    to the following entry out of it.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.startswith((" ", "\t", "#")) or not line.strip():
            continue
        key = line.split(":", 1)[0].strip().strip("'\"")
        if start is None and key == name:
            start = index
            continue
        if start is not None:
            end = index
            while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
                end -= 1
            return start, end
    if start is None:
        return None
    return start, len(lines)


def insert(path: Path, name: str, entry: dict[str, Any]) -> str:
    """Append an entry to an instance file, leaving every existing byte where it was."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if block_of(text, name) is not None:
        raise AuthoringError(f"{path.name} already declares {name!r}")
    separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + separator + render_entry(name, entry)


def replace(path: Path, name: str, entry: dict[str, Any]) -> str:
    text = path.read_text(encoding="utf-8")
    span = block_of(text, name)
    if span is None:
        raise AuthoringError(f"{path.name} does not declare {name!r}")
    lines = text.splitlines(keepends=True)
    start, end = span
    return "".join(lines[:start]) + render_entry(name, entry) + "".join(lines[end:])


def remove(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    span = block_of(text, name)
    if span is None:
        raise AuthoringError(f"{path.name} does not declare {name!r}")
    lines = text.splitlines(keepends=True)
    start, end = span

    # Take the blank line that separated this entry from the one before it, so removing an entry
    # leaves the file as it was rather than accumulating gaps where entries used to be.
    if start > 0 and not lines[start - 1].strip():
        start -= 1
    remaining = "".join(lines[:start]) + "".join(lines[end:])
    return remaining if remaining.strip() else ""


def diff(before: str, after: str, label: str) -> str:
    """A unified diff of a proposed change, so it can be read before it is written."""
    import difflib

    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=label,
            tofile=label,
            n=3,
        )
    )
