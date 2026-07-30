"""Wording every layer needs and none of them owns."""

from __future__ import annotations


def plural(count: int, noun: str) -> str:
    """`1 scenario`, `2 scenarios` — a count and its noun, agreeing."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
