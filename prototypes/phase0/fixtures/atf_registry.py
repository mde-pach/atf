"""ATF's own step registry — the piece §1.2 turns out to depend on.

A scenario's fixture closure does not contain its steps' parameters. pytest-bdd asks for those with
`request.getfixturevalue` while the step runs, so `item.fixturenames` for a scenario is
`['_pytest_bdd_example', '_session_faker', 'request']` and nothing else. Collection-time resolution
therefore cannot be read off pytest.

It can be read off ATF, because ATF registers every step: the ones it ships, the ones a suite writes
with `atf.when` / `atf.then`, and the ones a `@phrase` expands to. Keeping the pattern and the
function together here means the question "what does this sentence ask for" is answered by a lookup
ATF owns, without touching a pytest-bdd internal.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest_bdd
from pytest_bdd import parsers

# `{words}` in a pattern is a placeholder the sentence fills; anything else in the signature is a
# fixture the step asks for.
PLACEHOLDER = re.compile(r"\{(\w+)[^}]*\}")


@dataclass(frozen=True)
class StepDefinition:
    """One registered sentence, and what it asks for."""

    kind: str  # given / when / then
    pattern: str
    function: Callable[..., Any]

    @property
    def parameters(self) -> list[str]:
        """The step's parameters that are not placeholders — its fixture requests.

        Read off the pattern with a regular expression rather than out of the parser, so that this
        owes nothing to a pytest-bdd internal. MIGRATION.md ranks those imports as risk 4.
        """
        placeholders = set(PLACEHOLDER.findall(self.pattern))
        return [
            name
            for name in inspect.signature(self.function).parameters
            if name not in placeholders and name != "request"
        ]


STEPS: list[StepDefinition] = []


def _register(kind: str, pattern: str, **options: Any):
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        STEPS.append(StepDefinition(kind=kind, pattern=pattern, function=function))
        registrar = getattr(pytest_bdd, kind)
        # pytest-bdd injects its step fixture into the *caller's* module namespace, found by walking
        # the stack. Wrapping its decorator adds a frame, so the level has to say so or every step a
        # suite writes lands in this module and no scenario finds it. `stacklevel` is a documented
        # parameter, which is what makes owning the registry cheap rather than fragile.
        return registrar(parsers.parse(pattern), stacklevel=2, **options)(function)

    return decorate


def given(pattern: str, **options: Any):
    return _register("given", pattern, **options)


def when(pattern: str, **options: Any):
    return _register("when", pattern, **options)


def then(pattern: str, **options: Any):
    return _register("then", pattern, **options)


def matching_step(kind: str, sentence: str) -> StepDefinition | None:
    """The registered step a scenario line means, or nothing when the suite never taught it."""
    for step in STEPS:
        if step.kind != kind:
            continue
        try:
            if parsers.parse(step.pattern).is_matching(sentence):
                return step
        except Exception:  # noqa: BLE001, S110 - a pattern that cannot match is simply not a match
            continue
    return None
