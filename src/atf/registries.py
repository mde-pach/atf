"""Two more things a suite registers: a claim, and a check."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from . import claims
from .steps import THEN, Step, register

Verdict = tuple[bool, str]


@dataclass(frozen=True)
class Check:
    """One convention, and what it finds wrong."""

    description: str
    find: Callable[[Any], Iterator[tuple[Any, str]]]


CHECKS: list[Check] = []


def check(description: str) -> Callable[[Any], Any]:
    """Register a check. Its findings are `atf check`'s answer, and it exits `1` on them."""

    def decorate(find: Any) -> Any:
        CHECKS.append(Check(description=description, find=find))
        return find

    return decorate


def claim(pattern: str) -> Callable[[Any], Any]:
    """Register a claim: a `Then` sentence whose function answers `(held, message)`.

    What a claim's function is handed follows one rule. A parameter named `record` gets the resource
    the sentence named, looked up now. A parameter named after a placeholder gets that placeholder's
    value — or, when the value names a slot this test has filled, the slot's contents, which is what
    lets `the {result} lists ...` be written about a whole result.
    """

    def decorate(function: Any) -> Any:
        def run(**arguments: Any) -> None:
            claims.held(function(**arguments), subject="")

        run.__name__ = getattr(function, "__name__", "claim")
        run.__doc__ = function.__doc__
        # The registry reads parameters off a signature, so the wrapper carries the claim's.
        setattr(run, "__signature__", inspect.signature(function))  # noqa: B010
        setattr(run, "__atf_claim__", function)  # noqa: B010
        register(THEN, pattern)(run)
        return function

    return decorate


def resolve_claim_arguments(step: Step, values: dict[str, str], scope: Any) -> dict[str, Any]:
    """What a registered claim is called with, given the sentence that said it."""
    function = getattr(step.function, "__atf_claim__", None)
    if function is None:
        return {}
    out: dict[str, Any] = {}
    for name in inspect.signature(function).parameters:
        if name == "record":
            out[name] = _record_for(values, scope)
        elif name in values and values[name] in scope.slots:
            out[name] = scope.slots[values[name]]
        elif name in values:
            out[name] = values[name]
        else:
            out[name] = scope.slots.get(name)
    return out


def _record_for(values: dict[str, str], scope: Any) -> Any:
    kind, name = values.get("type") or values.get("kind", ""), values.get("name", "")
    if kind and name:
        return scope.look_up(kind, name)
    return scope.slots.get("result")
