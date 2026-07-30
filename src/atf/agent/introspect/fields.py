"""The fields of a resource, for an assertion built without an editor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ...engine.status import ResourceStatus
from ...model.catalog import Node
from .surface import Option


@dataclass
class FieldChoice:
    """One field an assertion can name, and what it holds right now."""

    name: str
    current: str = ""
    source: str = ""

    def as_option(self) -> Option:
        """This field as a choice: what it is called, and what it holds right now."""
        return Option(value=self.name, label=self.name, meta=self.current, desc=self.source)

    @property
    def hint(self) -> str:
        if self.current:
            return f"currently {self.current} · {self.source}" if self.source else f"currently {self.current}"
        return self.source

def field_choices(node: Node, entry: ResourceStatus) -> list[FieldChoice]:
    """The fields of one resource, best-known first.

    Three sources, in decreasing authority: what the environment's record actually carries, what
    the catalog body declares, and the two fields the type itself names — its identity and whatever
    it is recognised by. A field is only ever *offered*; nothing here requires one to exist, which
    is the line the framework holds on record shape.
    """
    record = entry.fields
    declared = node.body
    named = [node.id_field, *node.natural_keys]

    ordered: list[str] = []
    for name in [*named, *sorted(record), *sorted(declared)]:
        if name not in ordered:
            ordered.append(str(name))

    choices: list[FieldChoice] = []
    for name in ordered:
        if name in record:
            choices.append(FieldChoice(name, written(record[name]), "on the record in this environment"))
        elif name in declared:
            choices.append(FieldChoice(name, written(declared[name]), "declared in the catalog"))
        elif name == node.id_field:
            choices.append(FieldChoice(name, "", "the identity field, assigned when it is created"))
        else:
            choices.append(FieldChoice(name, "", "part of the natural key"))
    return choices

def written(value: Any) -> str:
    """A record's value as a scenario would write it between quotes."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)[:60]
    return str(value)[:60]
