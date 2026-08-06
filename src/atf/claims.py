"""`atf.claims` — the comparisons a claim is made of, as a library anybody may call."""

from __future__ import annotations

from typing import Any

from . import markers
from .model import compare

MISSING = compare.MISSING


class Failed(AssertionError):
    """A claim that did not hold. An `AssertionError`, so pytest reports it as an assertion."""


def fail(message: str) -> None:
    raise Failed(message)


def _get(record: Any, field: str) -> Any:
    """A field of a record or of a declared resource, or `MISSING` when it is not there at all."""
    if isinstance(record, dict):
        return record.get(field, MISSING)
    return getattr(record, field, MISSING)


def _describe(value: Any) -> str:
    return "not there" if value is MISSING else compare.describe(value)


def field_is(record: Any, field: str, written: str, *, subject: str = "") -> None:
    """`Then the todo_list "groceries" field "slug" is "groceries"` — and the marker form of it."""
    about = f"{subject} " if subject else ""
    actual = _get(record, field)

    if markers.is_marker(written):
        held, why = markers.holds(actual, written, present=actual is not MISSING)
        if not held:
            fail(f'{about}field "{field}" is not {written.strip()}: {why}')
        return

    if actual is MISSING:
        fail(f'{about}field "{field}" is not there at all, and the claim wants "{written}"')
    if not compare.written_matches(actual, written):
        fail(f'{about}field "{field}" is {_describe(actual)}, and the claim wants "{written}"')


def field_contains(record: Any, field: str, written: str, *, subject: str = "") -> None:
    """`Then the result field "output" contains "groceries"`."""
    about = f"{subject} " if subject else ""
    actual = _get(record, field)
    if actual is MISSING:
        fail(f'{about}field "{field}" is not there at all, and the claim wants it to contain "{written}"')
    try:
        held = compare.written_contains(actual, written)
    except compare.Uncontainable as exc:
        fail(f'{about}field "{field}": {exc}')
        return
    if not held:
        fail(f'{about}field "{field}" is {_describe(actual)}, which does not contain "{written}"')


def exists(found: Any, subject: str) -> None:
    """`Then the todo_list "groceries" exists`."""
    if found is None:
        fail(f"{subject} is not there")


def is_gone(found: Any, subject: str) -> None:
    """`Then the todo_list "groceries" is gone`."""
    if found is not None:
        fail(f"{subject} is still there")


def counted(records: list[Any], expected: int, kind: str) -> None:
    """`Then the environment has 2 todo_list`."""
    if len(records) != expected:
        fail(f"the environment has {len(records)} {kind}, and the claim wants {expected}")


def held(verdict: tuple[bool, str], subject: str = "") -> None:
    """Report a `(held, message)` a registered claim or marker returned."""
    ok, message = verdict
    if not ok:
        fail(f"{subject}: {message}" if subject else message)
