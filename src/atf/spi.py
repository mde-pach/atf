"""The two vocabularies a system answers in, and the settings-checking every driver goes through."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, get_type_hints

#: A raw record of wire data — what a system's `find`/`create`/etc. actually hands back or is given.
#: Not `Record`: that name is a declared kind's own base class now (`class Owner(Record, at=...)`),
#: and a floating `dict[str, Any]` alias of the same name would only be confusing beside it.
Payload = dict[str, Any]


class State(StrEnum):
    """What an environment holds. One of exactly three words, and never a fourth."""

    PRESENT = "present"
    ABSENT = "absent"
    UNREACHABLE = "unreachable"


class Did(StrEnum):
    """What a provisioning pass did to one resource. Not a state — a state is what is there now."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    # `atf status` and a dry run report this. There is no "blocked": a resource that cannot be
    # made fails the test that asked for it.
    LEFT_ALONE = "left alone"


# `find` is the only one every system answers. A thing that is looked at and never made — a page,
# a table somebody else owns — writes this and nothing else.
REQUIRED = ("find",)
# `create`, `update` and `delete` are what a thing ATF makes needs; a system without one refuses
# that operation by name. `browse` adds a sentence, `find_many` answers about several resources at
# once, and `begin`/`rollback` wrap a test.
WRITES = ("create", "update", "delete")
OPTIONAL = (
    *WRITES,
    "browse",
    "find_many",
    "begin",
    "rollback",
    "capture",
    "describe",
    "close",
)


class SpiError(Exception):
    """Raised when a system class is not one, or is configured with something it cannot read."""


def check(cls: type, kind: str, given: Payload, where: str) -> Payload:
    """Check a mapping against a driver's own `Settings`, and return it.

    A driver that declares none takes whatever it is given.
    """
    declared = getattr(cls, kind, None)
    if declared is None:
        return dict(given)

    try:
        annotations = get_type_hints(declared)
    except Exception as exc:
        raise SpiError(f"{where}: {cls.__qualname__}.{kind} cannot be read: {exc}") from exc

    required = set(getattr(declared, "__required_keys__", frozenset(annotations)))
    known = set(annotations)

    problems = []
    for missing in sorted(required - set(given)):
        problems.append(f"{missing} is required ({_name(annotations[missing])})")
    for unknown in sorted(set(given) - known):
        problems.append(f"{unknown} is not one of {', '.join(sorted(known)) or 'no settings at all'}")
    for name, value in sorted(given.items()):
        if name in annotations and not _fits(value, annotations[name]):
            problems.append(f"{name} is {value!r}, and it is {_name(annotations[name])}")

    if problems:
        raise SpiError(f"{where}:\n  - " + "\n  - ".join(problems))
    return dict(given)


def _fits(value: Any, annotation: Any) -> bool:
    """A shallow check: a manifest holds scalars and lists of them and nothing deeper."""
    if annotation is Any:
        return True
    if not isinstance(annotation, type):
        return True  # a union, a generic, an alias — not worth a half-check that would misfire
    if annotation is float:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if annotation is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, annotation)


def _name(annotation: Any) -> str:
    return getattr(annotation, "__name__", None) or str(annotation)
