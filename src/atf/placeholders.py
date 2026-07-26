"""Placeholder resolution (§6.3). Pure functions; no I/O."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
_NOW_RE = re.compile(r"^now\s*([+-])\s*(\d+)d\s+(\d{1,2}):(\d{2})$")
_REF_RE = re.compile(r"^([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\.id$")

Lookup = Callable[[str], Any]


class Unresolved(Exception):
    """A placeholder could not be resolved (dependency not provisioned yet)."""

    def __init__(self, expression: str, detail: str = "") -> None:
        self.expression = expression
        super().__init__(f"unresolved placeholder ${{{expression}}}" + (f": {detail}" if detail else ""))


def resolve(value: Any, lookup: Lookup, now: datetime | None = None) -> Any:
    """Recursively resolve `${...}` placeholders in strings, lists and dicts.

    A string that is exactly one placeholder keeps the resolved value's type; otherwise the
    resolved value is interpolated as text. Raises `Unresolved` when a reference has no identity.
    """
    if isinstance(value, str):
        return _resolve_string(value, lookup, now)
    if isinstance(value, list):
        return [resolve(item, lookup, now) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, lookup, now) for key, item in value.items()}
    return value


def references(value: Any) -> set[str]:
    """Node ids referenced by `${collection.name.id}` placeholders anywhere inside `value`."""
    found: set[str] = set()
    if isinstance(value, str):
        for expression in PLACEHOLDER_RE.findall(value):
            match = _REF_RE.match(expression.strip())
            if match:
                found.add(f"{match.group(1)}.{match.group(2)}")
    elif isinstance(value, list):
        for item in value:
            found |= references(item)
    elif isinstance(value, dict):
        for item in value.values():
            found |= references(item)
    return found


def _resolve_string(text: str, lookup: Lookup, now: datetime | None) -> Any:
    whole = PLACEHOLDER_RE.fullmatch(text.strip())
    if whole:
        return _resolve_expression(whole.group(1).strip(), lookup, now)
    return PLACEHOLDER_RE.sub(lambda m: str(_resolve_expression(m.group(1).strip(), lookup, now)), text)


def _resolve_expression(expression: str, lookup: Lookup, now: datetime | None) -> Any:
    stamp = _NOW_RE.match(expression)
    if stamp:
        sign, days, hour, minute = stamp.groups()
        offset = timedelta(days=int(days) * (1 if sign == "+" else -1))
        base = (now or datetime.now(UTC)) + offset
        moment = base.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        return moment.isoformat().replace("+00:00", "Z")

    reference = _REF_RE.match(expression)
    if reference:
        node_id = f"{reference.group(1)}.{reference.group(2)}"
        identity = lookup(node_id)
        if identity is None:
            raise Unresolved(expression, f"{node_id} has no identity yet")
        return identity

    raise Unresolved(expression, "unknown placeholder form")
