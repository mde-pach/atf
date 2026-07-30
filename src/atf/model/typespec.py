"""What a resource type declares, and the words a declaration may use."""

from __future__ import annotations

import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .records import Record

# What ATF is being asked to do about a resource.
#
# `create` makes it exist. `reference` is a precondition ATF *cannot* create — an account someone
# else provisioned — so an absent one blocks. `data` is neither: it is an observation, something to
# look at and make claims about, and an absent one means only that it is not there yet.
CREATE, REFERENCE, DATA = "create", "reference", "data"
MODES = frozenset({CREATE, REFERENCE, DATA})

PERSISTENT, EPHEMERAL = "persistent", "ephemeral"
LIFECYCLES = frozenset({PERSISTENT, EPHEMERAL})

DEFAULT_ID_FIELD = "id"

# The keys ATF reads itself. Every other key in a type entry is its adapter's configuration.
UNIVERSAL_TYPE_KEYS = frozenset({"system", "mode", "lifecycle", "id_field"})

# Verbs ATF has of its own, which a type may not redefine. `delete` is in the required SPI, so every
# adapter has one and `When I delete the …` needs no declaration.
BUILT_IN_ACTIONS = frozenset({"delete"})


@dataclass(frozen=True)
class TypeSpec:
    """One resource type as the catalog declares it.

    `config` is everything the type says that ATF does not read itself: its adapter's options, plus
    `natural_key` and `ref_field`, which are how a resource of this type is recognised.
    """

    name: str
    system: str = ""
    mode: str = CREATE
    lifecycle: str = PERSISTENT
    id_field: str = DEFAULT_ID_FIELD
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_entry(cls, name: str, entry: Mapping[str, Any]) -> TypeSpec:
        return cls(
            name=name,
            system=str(entry.get("system", "")),
            mode=str(entry.get("mode", CREATE)),
            lifecycle=str(entry.get("lifecycle", PERSISTENT)),
            id_field=str(entry.get("id_field", DEFAULT_ID_FIELD)),
            config={key: value for key, value in entry.items() if key not in UNIVERSAL_TYPE_KEYS},
        )

    @property
    def ephemeral(self) -> bool:
        return self.lifecycle == EPHEMERAL

    @property
    def natural_keys(self) -> list[str]:
        """The body fields a resource of this type is recognised by, or `[]` if it names none."""
        keys = self.config.get("natural_key")
        if isinstance(keys, str):
            return [keys]
        if isinstance(keys, list) and keys and all(isinstance(key, str) for key in keys):
            return [str(key) for key in keys]
        return []

    @property
    def ref_field(self) -> str:
        """What the backend calls the natural key, when that is not what the body calls it."""
        declared = self.config.get("ref_field")
        return str(declared) if declared else ""

    def remote_field(self, key: str) -> str:
        """One natural-key field as the *backend* spells it.

        A single-key type may name the field differently there — `natural_key: name` matched against
        a record's `slug`. With several keys there is no one field to redirect.
        """
        return self.ref_field if (self.ref_field and len(self.natural_keys) == 1) else key

    @property
    def remote_keys(self) -> list[str]:
        """The natural key as the backend spells it — what a record's own fields are called."""
        return [self.remote_field(key) for key in self.natural_keys]

    def signature(self, record: Record) -> tuple[str, ...] | None:
        """A record's natural key, positionally: the values an adapter's `find` matches one on.

        `None` when the type names no natural key, or the record does not carry all of it.
        """
        keys = self.natural_keys
        if not keys:
            return None
        values: list[str] = []
        for key in keys:
            value = record.get(self.remote_field(key))
            if value is None:
                return None
            values.append(str(value))
        return tuple(values)

    def fits(self, record: Record) -> bool:
        """Whether a record carries this type's identity and everything it is known by."""
        if not self.natural_keys:
            return False
        return self.id_field in record and all(key in record for key in self.remote_keys)

    @property
    def declared_actions(self) -> list[str]:
        """The domain actions this type declares, in the order the catalog wrote them."""
        declared = self.config.get("actions")
        return [str(name) for name in declared] if isinstance(declared, dict) else []

    @property
    def actions(self) -> list[str]:
        """What can be done to one of these: what the type declares, plus what ATF can always do."""
        return sorted({*self.declared_actions, *BUILT_IN_ACTIONS})

    @property
    def browse_fields(self) -> list[str]:
        """Fields a scoped listing needs before it can run — empty when the type lists globally.

        A type whose `list_path` is scoped to a parent (`/owners/{owner_id}/lists`) cannot be
        enumerated without knowing which parent, so the caller has to supply one.
        """
        template = self.config.get("list_path")
        if not isinstance(template, str) or not template:
            return []
        return [name for _, name, _, _ in string.Formatter().parse(template) if name]
