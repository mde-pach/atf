"""What counts as a record, so that a step's return value is assertable whatever shape it is in.

ATF's bargain with a project is that Python does the *acting* and the readable layer does the
*asserting*: a step performs something the framework has no generic way to perform, and hands back
what it got. That bargain only holds if "what it got" can be almost anything. It could not: the
assertions accepted a `dict` and nothing else, so a step returning a dataclass — the obvious way to
write one in modern Python — had no generic assertion available to it, and the suite was forced to
hand-write the `@then`s instead. Every broken seam converts into hand-written assertions, and
assertions in Python are exactly the half a non-developer is supposed to read.

So this module answers one question — *is this a record, and what are its fields?* — for the two
callers that need it: the assertions in `steps.py`, and the slot descriptions in `context.py`. One
answer for both, or the cockpit would describe a value the assertions cannot read.

**The list of shapes is closed on purpose.** A mapping, a dataclass, a named tuple, and an object
that offers itself as a dict. Anything else is not a record, and saying so is the useful answer: a
step that returned a string meant to return a string, and the failure should say that rather than
inventing fields for it.

**A dataclass's properties are part of its record.** `Outcome` has `stdout` and `stderr` as fields
and `output` as a property joining them — and "the output" is exactly what a scenario wants to talk
about. A property is something the author of the step chose to publish, so it is read; one that
raises is simply left out, because a description must never be the reason a scenario fails.

Reading is **shallow**. A nested dict stays a nested dict rather than being flattened: it is a value
this record holds, not fields of this record, and `compare.py` already knows how to match one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from .adapters import Record

# Methods an object can offer to say "here I am as a dict". `_asdict` is what `NamedTuple`
# generates; `model_dump` is pydantic's; `to_dict` is the convention everywhere else.
_AS_DICT = ("_asdict", "to_dict", "model_dump")


def as_record(value: Any) -> Record | None:
    """This value as a record, or `None` when it is not one."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _from_dataclass(value)
    return _from_conversion(value)


def as_records(value: Any) -> list[Record] | None:
    """This value as the records it holds, or `None` when it holds none.

    One record counts as one record; a list counts only when every item in it is one, because a
    list with a record and a string in it is not a listing of anything and an assertion over it
    would be guessing.
    """
    single = as_record(value)
    if single is not None:
        return [single]
    if isinstance(value, list | tuple):
        converted = [as_record(item) for item in value]
        if all(item is not None for item in converted):
            return [item for item in converted if item is not None]
    return None


def kind(value: Any) -> str:
    """What a failure message should call this value's shape, for a value that is not a record."""
    return type(value).__name__


def _from_dataclass(value: Any) -> Record:
    record: Record = {}
    for field in dataclasses.fields(value):
        record[field.name] = getattr(value, field.name, None)
    for name in _properties(type(value)):
        if name in record:
            continue
        try:
            record[name] = getattr(value, name)
        except Exception:  # noqa: BLE001 - a description must never fail a scenario
            continue
    return record


def _properties(cls: type) -> list[str]:
    """Public properties declared anywhere on this class's ancestry, nearest first."""
    found: list[str] = []
    for ancestor in cls.__mro__:
        for name, attribute in vars(ancestor).items():
            if not name.startswith("_") and isinstance(attribute, property) and name not in found:
                found.append(name)
    return found


def _from_conversion(value: Any) -> Record | None:
    # Bound methods only: a class offering `to_dict` is not itself a record, and neither is a
    # module that happens to have the name.
    if isinstance(value, type):
        return None
    for name in _AS_DICT:
        method = getattr(value, name, None)
        if not callable(method):
            continue
        try:
            converted = method()
        except Exception:  # noqa: BLE001 - an object that refuses to convert is simply not a record
            return None
        if isinstance(converted, Mapping):
            return {str(key): item for key, item in converted.items()}
    return None
