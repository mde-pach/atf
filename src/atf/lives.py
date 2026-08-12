"""How long a thing lives, read off the suite: the test, the run, or forever."""

from __future__ import annotations

from typing import Any

from . import graph
from .declare import (
    FOREVER,
    SPANS,
    THE_RUN,
    THE_TEST,
    declaration_of,
    instance_of,
    name_of,
)

#: Strictest first, which is the order the rules are applied in.
STRICTEST = (THE_TEST, THE_RUN, FOREVER)


def strictest(*spans: str) -> str:
    """The shortest of several spans. This is how the floor is applied to a resource's parents."""
    for span in STRICTEST:
        if span in spans:
            return span
    return FOREVER


#: The rule that gave each span, for a span ATF read off the suite.
BECAUSE = {
    THE_TEST: "some scenario changes it",
    THE_RUN: "it is resolved rather than declared",
    FOREVER: "it is declared with fixed values",
}


def why(span: str, resource: Any = None) -> str:
    """Why a thing lives as long as it does: the rule that decided it, or who wrote it down.

    Three answers, and they are different facts. Somebody typed it. Its own shape earned it. Or its
    lineage floored it, in which case the rule that applied is not this thing's rule.
    """
    if resource is None:
        return BECAUSE.get(span, "")
    if declaration_of(resource).lives:
        return "written on the declaration — ATF cannot see this one"
    if _own(resource, MUTATED) != span:
        shorter = [
            named(node)
            for node in graph.closure(resource)[:-1]
            if _own(node, MUTATED) == span
        ]
        return f"it cannot outlive {', '.join(shorter) or 'what it needs'}"
    return BECAUSE.get(span, "")


def _own(resource: Any, mutated: frozenset[str]) -> str:
    """The span one resource earns on its own, before its lineage is taken into account."""
    declaration = declaration_of(resource)
    if declaration.lives:
        return declaration.lives
    record = instance_of(resource)
    if record.ephemeral or (record.name and record.name in mutated):
        return THE_TEST
    if record.factorised:
        return THE_RUN
    return FOREVER


def of(resource: Any, mutated: frozenset[str] | None = None) -> str:
    """How long this resource lives, floor included.

    Nothing outlives what it depends on: the answer is the strictest span in the whole closure.
    """
    written = mutated if mutated is not None else MUTATED
    spans = [_own(node, written) for node in graph.closure(resource)]
    return strictest(*spans)


def read(suite: Any, features: list[Any], phrases: dict[str, Any]) -> frozenset[str]:
    """Every resource some scenario changes, read off the sentences that say so.

    Only a sentence whose step declares that it writes counts. A shell command's effect is not
    declared, and treating "it might have done anything" as "it mutated everything" would make the
    whole suite function-scoped for no gain.
    """
    from . import (
        footprint,
    )

    written: set[str] = set()
    for feature in features:
        for scenario in feature.scenarios:
            if getattr(scenario, "is_phrase", False):
                continue
            written |= footprint.of_scenario(suite, scenario, phrases, spans={}).writes
    return frozenset(written)


#: What the suite in this process changes. Set once when a suite is read, so that teardown and the
#: schedule answer the same question the same way without threading the suite through every call.
MUTATED: frozenset[str] = frozenset()


def remember(mutated: frozenset[str]) -> None:
    global MUTATED
    MUTATED = mutated


def forget() -> None:
    remember(frozenset())


def table(suite: Any) -> dict[str, str]:
    """Every declared resource and how long it lives, which is what `atf plan` and `explain` show."""
    return {name: of(node) for name, node in suite.instances.items()}


def spans_of(resources: list[Any]) -> dict[int, str]:
    """The span of each of these, keyed by identity — a graph node is an identity."""
    return {id(node): of(node) for node in resources}


def named(resource: Any) -> str:
    return name_of(resource) or declaration_of(resource).kind


__all__ = [
    "FOREVER",
    "MUTATED",
    "SPANS",
    "THE_RUN",
    "THE_TEST",
    "forget",
    "named",
    "of",
    "read",
    "remember",
    "spans_of",
    "strictest",
    "table",
    "why",
]
