"""The per-scenario scratchpad, and what it remembers about what it is holding.

`context` used to be a `SimpleNamespace`: a bag that forgets. A `When` set `context.result` to
anything at all, and the `Then` after it knew the shape only because the same person wrote both.
Nothing downstream — not the framework, not the cockpit, not a person reading the scenario — could
say what a scenario had available to assert on once its actions had run.

`Context` behaves exactly like the namespace it replaces and additionally keeps a *description* of
everything set on it. The descriptions are what let the cockpit say "after that step, the result
held three records that look like tasks" instead of showing an opaque bag.

A description never holds a value, only names, kinds and counts. Slots are reported at the end of a
run and persisted with it, and a record can carry a token as easily as a title — so what leaves this
process is the shape of what was held, never the contents.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from typing_extensions import override

from .adapters import Record

# The attribute the provisioning step records ephemeral resources on, read by teardown. Steps that
# assert on an ephemeral resource read it too: an ephemeral resource is never looked up — that is
# what ephemeral means — so the record made for this scenario is the only one there is.
EPHEMERAL_ATTR = "_ephemeral"

# What a `When` writes its output to. Naming it is what makes a generic assertion over that output
# possible: without an agreed word there is nothing for a step to say "the result" about.
RESULT = "result"

RECORD, RECORDS, TEXT, NUMBER, BOOLEAN, NOTHING, OTHER = (
    "record",
    "records",
    "text",
    "number",
    "boolean",
    "nothing",
    "other",
)

# A `Recogniser` answers "which resource type does this record look like?", or "" for no idea. The
# plugin supplies one backed by the catalog; a `Context` built without one simply never guesses.
Recogniser = Callable[[Record], str]


@dataclass(frozen=True)
class Slot:
    """What one attribute of the context is holding, described rather than copied."""

    name: str
    kind: str
    fields: list[str] = field(default_factory=list)
    count: int = 0
    resource_type: str = ""
    node_id: str = ""
    guessed: bool = False

    @property
    def summary(self) -> str:
        """The slot in the words the cockpit and a failure message both use."""
        named = self.resource_type + (" " if self.resource_type else "")
        if self.kind == RECORDS:
            plural = "record" if self.count == 1 else "records"
            return f"{self.count} {named}{plural}{self._carrying}"
        if self.kind == RECORD:
            return f"one {named}record{self._carrying}"
        return {
            TEXT: "some text",
            NUMBER: "a number",
            BOOLEAN: "a true/false value",
            NOTHING: "nothing",
        }.get(self.kind, "something ATF cannot describe")

    @property
    def _carrying(self) -> str:
        return f" carrying {', '.join(self.fields)}" if self.fields else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "fields": list(self.fields),
            "count": self.count,
            "resource_type": self.resource_type,
            "node_id": self.node_id,
            "guessed": self.guessed,
        }


class Context:
    """The per-scenario scratchpad: steps write what they create and read what they need.

    A drop-in for the `SimpleNamespace` it replaces. `context.foo = x`, `context.foo`,
    `del context.foo` and an `AttributeError` for anything never set all behave as before, so no
    existing step changes. Attributes whose name starts with `_` are ATF's own bookkeeping and are
    not described.
    """

    _slots: dict[str, Slot]
    _recognise: Recogniser | None

    def __init__(self, recognise: Recogniser | None = None, **values: Any) -> None:
        object.__setattr__(self, "_slots", {})
        object.__setattr__(self, "_recognise", recognise)
        for key, value in values.items():
            setattr(self, key, value)

    # ---- namespace behaviour ------------------------------------------------

    @override
    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if not name.startswith("_"):
            self._slots[name] = describe(name, value, self._recognise)

    @override
    def __delattr__(self, name: str) -> None:
        object.__delattr__(self, name)
        self._slots.pop(name, None)

    @override
    def __repr__(self) -> str:
        held = ", ".join(f"{name}={value!r}" for name, value in sorted(self.values.items()))
        return f"Context({held})"

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Context) and self.values == other.values

    # ---- what it is holding -------------------------------------------------

    @property
    def values(self) -> dict[str, Any]:
        """Everything a step put here, without ATF's own bookkeeping."""
        return {name: value for name, value in vars(self).items() if not name.startswith("_")}

    @property
    def slots(self) -> dict[str, Slot]:
        """A description of each of those, in the order they were first set."""
        return dict(self._slots)

    def note(self, name: str, resource_type: str = "", node_id: str = "") -> None:
        """Say what a slot is, when the setter knows more than its value shows.

        The provisioning step knows the type and the catalog node behind the record it just wrote;
        nothing about the record itself says so.
        """
        slot = self._slots.get(name)
        if slot is None:
            return
        self._slots[name] = Slot(
            name=slot.name,
            kind=slot.kind,
            fields=slot.fields,
            count=slot.count,
            resource_type=resource_type or slot.resource_type,
            node_id=node_id or slot.node_id,
            guessed=False,
        )


def describe(name: str, value: Any, recognise: Recogniser | None = None) -> Slot:
    """What a value is, in the terms an assertion can be built on."""
    if isinstance(value, dict):
        looks_like = _guess(recognise, value)
        return Slot(
            name=name,
            kind=RECORD,
            fields=sorted(str(key) for key in value),
            count=1,
            resource_type=looks_like,
            guessed=bool(looks_like),
        )
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        looks_like = _guess(recognise, value[0])
        return Slot(
            name=name,
            kind=RECORDS,
            fields=_shared_fields(value),
            count=len(value),
            resource_type=looks_like,
            guessed=bool(looks_like),
        )
    if value is None:
        return Slot(name=name, kind=NOTHING)
    if isinstance(value, bool):
        return Slot(name=name, kind=BOOLEAN)
    if isinstance(value, int | float):
        return Slot(name=name, kind=NUMBER)
    if isinstance(value, str):
        return Slot(name=name, kind=TEXT)
    if isinstance(value, list):
        return Slot(name=name, kind=OTHER, count=len(value))
    return Slot(name=name, kind=OTHER)


def _shared_fields(records: list[Any]) -> list[str]:
    """The fields every record in the list carries — the ones an assertion can count on."""
    common: set[str] | None = None
    for record in records:
        keys = {str(key) for key in record}
        common = keys if common is None else common & keys
    return sorted(common or set())


def _guess(recognise: Recogniser | None, record: Record) -> str:
    if recognise is None:
        return ""
    try:
        return recognise(record) or ""
    except Exception:  # noqa: BLE001 - a guess must never be the reason a scenario fails
        return ""


def ephemeral_record(context: Any, node_id: str) -> Record | None:
    """The record this scenario built for an ephemeral node, if it built one.

    The most recent wins: one scenario can provision the same ephemeral node more than once, and
    the last one is the one the steps after it are talking about.
    """
    for tracked_id, record in reversed(list(getattr(context, EPHEMERAL_ATTR, []) or [])):
        if tracked_id == node_id:
            return record
    return None
