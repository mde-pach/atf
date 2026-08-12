"""`atf.claims` — the comparisons a check is made of, as a library anybody may call."""

from __future__ import annotations

from typing import Any

from . import literals
from .model import compare

MISSING = compare.MISSING


class Failed(AssertionError):
    """A check that did not hold. An `AssertionError`, so pytest reports it as an assertion."""


def fail(message: str) -> None:
    raise Failed(message)


def get(record: Any, field: str) -> Any:
    """A field of a record or of a declared thing, or `MISSING` when it is not there at all."""
    if isinstance(record, dict):
        return record.get(field, MISSING)
    return getattr(record, field, MISSING)


def _about(subject: str, field: str) -> str:
    """How a message names what it is about: `its exit code`, `the list "groceries" slug`."""
    said = field.replace("_", " ")
    return f"{subject} {said}".strip() if subject else said


def field_is(record: Any, field: str, written: str, *, subject: str = "") -> None:
    """`Then its exit code is 0`, and every other shape of the same claim."""
    held, why = literals.is_(get(record, field), written)
    if not held:
        fail(f"{_about(subject, field)}: {why}")


def field_is_not(record: Any, field: str, written: str, *, subject: str = "") -> None:
    """`Then its status is not "draft"`."""
    actual = get(record, field)
    held, _ = literals.is_(actual, written)
    if held:
        fail(f"{_about(subject, field)}: it is {literals.describe(actual)}, and this wants anything else")


def field_contains(record: Any, field: str, written: str, *, subject: str = "") -> None:
    """`Then its output contains "groceries"`."""
    held, why = literals.contains(get(record, field), written)
    if not held:
        fail(f"{_about(subject, field)}: {why}")


def field_does_not_contain(record: Any, field: str, written: str, *, subject: str = "") -> None:
    """`Then its output does not contain "traceback"`."""
    actual = get(record, field)
    if actual is MISSING:
        return
    held, _ = literals.contains(actual, written)
    if held:
        fail(f"{_about(subject, field)}: it is {literals.describe(actual)}, which holds {written.strip()}")


def mentions(record: Any, written: str, *, subject: str = "it") -> None:
    """`Then it mentions "groceries"` — anywhere in what came back, whatever shape it is.

    The one claim that does not name a field. It is what somebody writes before they know the shape
    of the output, which is exactly the author this design is for.
    """
    said = literals.read(written)
    if said.says_a_kind:
        fail(f"`mentions` takes a value, and {said.text} is a kind")
    if not _somewhere(record, said.value):
        fail(f"{subject} mentions nothing like {said.text} — {_shown(record)}")


def does_not_mention(record: Any, written: str, *, subject: str = "it") -> None:
    said = literals.read(written)
    if _somewhere(record, said.value):
        fail(f"{subject} mentions {said.text}, and this wants it not to")


def _somewhere(value: Any, wanted: Any) -> bool:
    """Whether a value holds this anywhere inside it, however deep.

    A record's field names count. `it mentions "exit_code"` is a fair question about what came
    back, and answering only about the values would make it a trick one.
    """
    if isinstance(value, dict):
        return any(
            _somewhere(name, wanted) or _somewhere(one, wanted) for name, one in value.items()
        )
    if isinstance(value, list | tuple):
        return any(_somewhere(one, wanted) for one in value)
    if value is None:
        return False
    return str(wanted) in str(value)


def _shown(value: Any) -> str:
    """What was there instead, kept to one line."""
    if isinstance(value, dict):
        parts = ", ".join(f"{name} {literals.describe(one)}" for name, one in sorted(value.items()))
        return parts or "it holds nothing at all"
    text = str(value)
    return f"it was {text[:120]!r}" if text else "it was empty"


def exists(found: Any, subject: str) -> None:
    """`Then the list "groceries" exists`."""
    if found is None:
        fail(f"{subject} is not there")


def is_gone(found: Any, subject: str) -> None:
    """`Then the list "groceries" is gone`."""
    if found is not None:
        fail(f"{subject} is still there")


def counted(records: list[Any], expected: int, kind: str) -> None:
    """`Then there are 2 lists`."""
    if len(records) != expected:
        fail(f"there are {len(records)} {kind}, and this wants {expected}")


def held(verdict: Any, subject: str = "") -> None:
    """Report whatever a registered check answered.

    A check may raise, return nothing, return `True`/`False`, or return `(held, message)`.
    """
    if verdict is None or verdict is True:
        return
    if verdict is False:
        fail(f"{subject}: it did not hold" if subject else "it did not hold")
        return
    if isinstance(verdict, tuple) and len(verdict) == 2:
        ok, message = verdict
        if not ok:
            fail(f"{subject}: {message}" if subject else str(message))
        return
    fail(f"a check answered {verdict!r}; it answers true or false, with a message")
