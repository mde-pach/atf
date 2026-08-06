"""Two more things a suite registers: a claim, and a check.

A **claim** is a sentence that holds or does not, written once and said in any scenario.

```python
@claim('the {type} "{name}" field "{field}" is a valid IBAN')
def _(record, field):
    return checksum_ok(record[field]), f"{field} is not a valid IBAN"
```

It answers `(held, message)`, the same shape a [marker](markers.py) answers in — a marker is about a
value, a claim is about a record.

A **check** is a convention `atf check` enforces. It yields findings, and each finding is a subject
and what is wrong with it.

```python
@check("every scenario names the subcommand it exercises")
def _(suite):
    for scenario in suite.scenarios:
        if not SUBCOMMANDS & set(scenario.tags):
            yield scenario, "no subcommand tag"
```

Neither is a concept in the band table. They are registered the way an adapter is, and met as a
sentence and as a command.
"""

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
    """Register a check. Its findings are `atf check`'s answer, so it exits `1` rather than `2`."""

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
        # The step registry reads a step's parameters off its signature, so the wrapper carries the
        # claim's rather than `**arguments`. That is what makes a registered claim resolve fixtures
        # exactly as a hand-written `@then` does.
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
