"""Resolution of the `${...}` placeholders a catalog body or a step value may contain.

One form is the framework's own: `${<node id>.id}`, a dependency's identity, which is checked when
the catalog loads and becomes an edge in the graph. Everything else is a call to a registered
[provider](providers.py) — `${now+1d 09:00}`, `${uuid}`, `${fake:email}` — so generated values are
an extension point rather than a list written into this module.

A node reference always wins, so no provider can shadow a collection, and a catalog naming one that
way is refused at load.
"""

from __future__ import annotations

import re
from collections.abc import Callable, MutableMapping
from typing import Any

from . import providers

PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")
_REF_RE = re.compile(r"^([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\.id$")

Lookup = Callable[[str], Any]

# Where an already-generated value is remembered for the rest of the scenario. Without it, an
# expression written twice — once in a `When` and once in the `Then` checking it — would generate
# two different values and the assertion could never pass.
Memo = MutableMapping[str, Any]


class Unresolved(Exception):
    """A placeholder could not be resolved (dependency not provisioned yet)."""

    def __init__(self, expression: str, detail: str = "") -> None:
        self.expression = expression
        super().__init__(f"unresolved placeholder ${{{expression}}}" + (f": {detail}" if detail else ""))


def resolve(value: Any, lookup: Lookup, memo: Memo | None = None) -> Any:
    """Recursively resolve `${...}` placeholders in strings, lists and dicts.

    A string that is exactly one placeholder keeps the resolved value's type; otherwise the
    resolved value is interpolated as text. Raises `Unresolved` when a reference has no identity.

    `memo` is what makes a generated value survive from the step that made it to the step that
    checks it: the same expression resolved twice against the same memo gives the same value.
    """
    if isinstance(value, str):
        return _resolve_string(value, lookup, memo)
    if isinstance(value, list):
        return [resolve(item, lookup, memo) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, lookup, memo) for key, item in value.items()}
    return value


def generated(expression: str) -> bool:
    """Whether this expression asks a provider for a value rather than naming a node."""
    return _REF_RE.match(expression.strip()) is None


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


def _resolve_string(text: str, lookup: Lookup, memo: Memo | None) -> Any:
    whole = PLACEHOLDER_RE.fullmatch(text.strip())
    if whole:
        return _resolve_expression(whole.group(1).strip(), lookup, memo)
    return PLACEHOLDER_RE.sub(lambda m: str(_resolve_expression(m.group(1).strip(), lookup, memo)), text)


def _resolve_expression(expression: str, lookup: Lookup, memo: Memo | None) -> Any:
    # A node reference first, always: it is the framework's own form, it is validated when the
    # catalog loads, and no registered name may shadow it.
    reference = _REF_RE.match(expression)
    if reference:
        node_id = f"{reference.group(1)}.{reference.group(2)}"
        identity = lookup(node_id)
        if identity is None:
            raise Unresolved(expression, f"{node_id} has no identity yet")
        return identity

    if memo is not None and expression in memo:
        return memo[expression]

    name, argument = providers.split(expression)
    if not name:
        raise Unresolved(expression, "not a node reference, and not a provider call either")
    try:
        made = providers.instance(name).value(argument)
    except providers.UnknownProvider as exc:
        raise Unresolved(expression, str(exc)) from None
    except Exception as exc:
        raise Unresolved(expression, _short(exc)) from None

    if memo is not None:
        memo[expression] = made
    return made


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text.splitlines()[0]
