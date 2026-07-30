"""The resource types a schema describes, as the YAML a person writes, and the change it makes."""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ...model.catalog import RESERVED_FIXTURE_NAMES, TYPES_FILE
from ...model.typespec import TypeSpec
from ..authoring import diff
from .document import SchemaError
from .score import Collection, collections, convention_of

# Every type an OpenAPI schema describes is served over a JSON API, which is the one system ATF
# ships an adapter for out of the box. Nothing in a schema could say otherwise.
SYSTEM = "rest"


# Every type an OpenAPI schema describes is served over a JSON API, which is the one system ATF
# ships an adapter for out of the box. Nothing in a schema could say otherwise.
SYSTEM = "rest"

COMMENT_WIDTH = 94

def render(collection: Collection) -> str:
    """One resource type as the YAML a person writes by hand, each guessed key annotated."""
    lines = [f"{collection.name}:", f"  system: {SYSTEM}", f"  path: {scalar(collection.path)}"]
    if collection.scope:
        # `path` is what a create posts to and `list_path` is what a lookup fills in from the body,
        # so a scoped collection needs both to say the same thing for `find` to work at all.
        lines.append(f"  list_path: {scalar(collection.path)}")
    lines.append(f"  id_field: {collection.id_field}")

    if collection.scope and collection.parent:
        lines += comment(
            f"scoped under `{collection.parent}`, so declare each one with the {collection.parent} it "
            f"belongs to — `{collection.scope[-1]}` in the body, as a `${{...}}` reference"
        )
    guess = collection.guess
    if guess:
        lines += comment(f"guessed: {guess.because}")
        lines.append(f"  natural_key: {key_said(guess.key)}")
    else:
        lines += comment(f"no natural_key: {guess.because}.")
        lines += comment(
            "Choose one by hand. Until then this type will not provision — which is the safe half of "
            "the trade: a wrong key makes every run create another record instead."
        )
    return "\n".join(lines) + "\n"

def comment(text: str) -> list[str]:
    wrapped = textwrap.wrap(text, width=COMMENT_WIDTH) or [""]
    return [f"  # {wrapped[0]}"] + [f"  #   {line}" for line in wrapped[1:]]

def scalar(value: str) -> str:
    """A value as YAML, quoted only where it has to be — a catalog is read as much as it is loaded."""
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).strip()
    return dumped.removesuffix("...").strip()

def key_said(fields: tuple[str, ...]) -> str:
    if len(fields) == 1:
        return scalar(fields[0])
    return "[" + ", ".join(scalar(one) for one in fields) + "]"

def header(source: str) -> str:
    return (
        f"# Resource types derived from {source} by `atf import openapi`.\n"
        "#\n"
        "# Every `natural_key` here is a guess and says what it was guessed from — check those first,\n"
        "# because a key that does not match makes ATF create another record on every run.\n"
        "#\n"
        "# `mode` and `lifecycle` are absent on purpose. A schema does not say whether ATF may create a\n"
        "# resource or must only ever find one, so every type below takes the defaults: `mode: create`\n"
        "# and `lifecycle: persistent`. Set them yourself where that is wrong.\n"
        "#\n"
        "# Re-running the import never rewrites what is in this file. It proposes the types that are\n"
        "# missing, and reports the ones the schema no longer agrees with.\n"
    )

@dataclass
class Proposal:
    """One `resources.yaml`, before and after. Nothing here has been written."""

    path: Path
    before: str
    after: str
    first: bool = False
    added: list[Collection] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changes(self) -> bool:
        return self.after != self.before

    def as_diff(self, label: str) -> str:
        return diff(self.before, self.after, label)

def propose(document: Mapping[str, Any], catalog_dir: Path, source: str = "") -> Proposal:
    """What this schema would add to a catalog, without touching it.

    The whole file text is proposed and then compared, the same way the cockpit proposes a catalog
    edit: a diff a person reads is worth more than a summary they have to trust, and it is the only
    honest way to show a change to a file that is hand-authored.
    """
    path = Path(catalog_dir) / TYPES_FILE
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    declared = _declared(before)

    found = collections(document, convention_of(declared))
    added: list[Collection] = []
    kept: list[str] = []
    drifted: list[str] = []
    skipped: list[tuple[str, str]] = []

    for collection in found:
        if collection.name in declared:
            kept.append(collection.name)
            if reason := _drift(collection, declared[collection.name]):
                drifted.append(f"{collection.name}: {reason}")
            continue
        if collection.name in RESERVED_FIXTURE_NAMES:
            why = "the name is one ATF reserves for a fixture — rename it, and add it yourself"
            skipped.append((collection.name, why))
            continue
        added.append(collection)

    blocks = [render(collection) for collection in added]
    first = not declared
    if not blocks:
        after = before
    elif first:
        after = header(source or "an OpenAPI schema") + "\n" + "\n".join(blocks)
    else:
        separator = "" if not before or before.endswith("\n\n") else ("\n" if before.endswith("\n") else "\n\n")
        after = before + separator + "\n".join(blocks)

    _must_reload(after, [collection.name for collection in added], before)
    return Proposal(
        path=path,
        before=before,
        after=after,
        first=first,
        added=added,
        kept=kept,
        drifted=drifted,
        absent=sorted(set(declared) - {collection.name for collection in found}),
        skipped=skipped,
    )

def _declared(text: str) -> dict[str, Any]:
    """The types already in the file, or nothing — a registry too broken to read is a blank page."""
    try:
        loaded = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError:
        return {}
    return {str(name): entry for name, entry in loaded.items()} if isinstance(loaded, dict) else {}

def _drift(collection: Collection, declared: Any) -> str:
    """What the schema now says that the catalog does not — reported, never applied.

    Only the two that are actionable and unambiguous. A `path` that moved is why every lookup 404s,
    and a `natural_key` naming a field the API no longer accepts is why every run creates a copy.
    Everything else a schema and a catalog can disagree about is a decision somebody made.
    """
    if not isinstance(declared, Mapping):
        return ""
    said = declared.get("path")
    if isinstance(said, str) and said and said != collection.path:
        return f"the catalog says `{said}`, the schema says `{collection.path}`"
    keys = [
        key for key in TypeSpec.from_entry(collection.name, declared).natural_keys
        if key not in collection.scope
    ]
    if keys and collection.guess.considered:
        known = {one.field for one in collection.guess.considered}
        # Only worth saying when the schema described *some* settable fields; an empty schema
        # fragment would otherwise report every type as drifted for saying nothing at all.
        if missing := [key for key in keys if key not in known]:
            return f"it is keyed on `{missing[0]}`, which this schema does not offer on a create"
    return ""

def _must_reload(text: str, names: list[str], before: str = "") -> None:
    """Proof the proposal is loadable YAML declaring what it claims to, before anyone is shown it.

    Raises `SchemaError` naming the file, not the parse error: almost every way this fails is about
    the file being appended to — a registry written as one flow mapping has nowhere to put a block
    entry — and a reader did not write the lines a parse error would point at.
    """
    try:
        loaded = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        if before.strip():
            raise SchemaError(
                f"nothing was written: these types cannot be added to {TYPES_FILE} as it stands.\n"
                f"  It has to be a block mapping of type name to settings — one `name:` per line, "
                f"with its settings indented under it.\n  ({exc})"
            ) from None
        raise SchemaError(f"the types derived from this schema are not valid YAML: {exc}") from None
    if not isinstance(loaded, dict) or any(name not in loaded for name in names):
        raise SchemaError(f"the types derived from this schema did not survive being written into {TYPES_FILE}")
