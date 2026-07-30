"""What counts as a record, so that a step's return value is assertable whatever shape it is in."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

Record = dict[str, Any]

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

    One record counts as one record; a list counts only when every item in it is one. A list holding a
    record and a string is not a listing of anything, and an assertion over it is a guess.
    """
    single = as_record(value)
    if single is not None:
        return [single]
    if isinstance(value, list | tuple):
        converted = [as_record(item) for item in value]
        if all(item is not None for item in converted):
            return [item for item in converted if item is not None]
    return None


def shared_fields(records: list[Any]) -> list[str]:
    """The fields every record in the list carries — the ones an assertion can count on."""
    common: set[str] | None = None
    for record in records:
        keys = {str(key) for key in record}
        common = keys if common is None else common & keys
    return sorted(common or set())


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
