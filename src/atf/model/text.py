"""Wording every layer needs and none of them owns."""

from __future__ import annotations

# How much of a failure is worth carrying into a message a person reads.
DETAIL_CHARS = 200


def first_line(exc: BaseException, limit: int = DETAIL_CHARS) -> str:
    """What an exception said, in one line: its first, truncated, and its class where it said nothing."""
    text = str(exc).strip() or exc.__class__.__name__
    first = text.splitlines()[0]
    return first if len(first) <= limit else first[: limit - 3] + "..."


def plural(count: int, noun: str) -> str:
    """`1 scenario`, `2 scenarios` — a count and its noun, agreeing."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
