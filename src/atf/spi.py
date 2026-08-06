"""What an adapter is: four required methods, two optional, and the two vocabularies."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, get_type_hints, runtime_checkable

Record = dict[str, Any]


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


@runtime_checkable
class Adapter(Protocol):
    """The four methods every adapter has. `act` and `browse` are optional and checked for."""

    def find(self, resource: Any) -> Record | None: ...

    def create(self, resource: Any) -> Record: ...

    def update(self, resource: Any, found: Record, changes: Record) -> Record: ...

    def delete(self, resource: Any, found: Record) -> None: ...


REQUIRED = ("find", "create", "update", "delete")
OPTIONAL = ("act", "browse")


class SpiError(Exception):
    """Raised when an adapter class is not one, or is configured with something it cannot read."""


def check_shape(name: str, cls: type) -> None:
    """Whether this class is an adapter at all, before an environment is built from it."""
    missing = [method for method in REQUIRED if not callable(getattr(cls, method, None))]
    if missing:
        raise SpiError(
            f"the {name!r} adapter ({cls.__module__}.{cls.__qualname__}) has no "
            f"{', '.join(missing)} — an adapter answers all of {', '.join(REQUIRED)}"
        )


def offers(cls: type, method: str) -> bool:
    """Whether an adapter implements one of the optional methods.

    Which optional methods an adapter has decides which sentences exist. Asked at collection.
    """
    return callable(getattr(cls, method, None))


def check(cls: type, kind: str, given: Record, where: str) -> Record:
    """Check a mapping against the adapter's own `Options` or `Settings`, and return it.

    Both are checked before a run. An adapter that declares neither takes whatever it is given.
    """
    declared = getattr(cls, kind, None)
    if declared is None:
        return dict(given)

    try:
        annotations = get_type_hints(declared)
    except Exception as exc:  # noqa: BLE001 - a type that will not resolve is the adapter's bug, reported as one
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
