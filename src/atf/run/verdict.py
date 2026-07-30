"""How a scenario stands, in one word, from what its runs said.

A scenario is one line of a feature file and several tests — one per Examples row — so the word for
it is a fold over their outcomes. Every surface that reports a suite needs that fold: the cockpit's
verdict, `atf docs`, and anything else that answers "can I ship?".
"""

from __future__ import annotations

from collections.abc import Iterable

from .events import ERROR, FAILED, PASSED, SKIPPED

PASSING = "passing"
FAILING = "failing"
NEVER_RUN = "never run"
SKIPPED_STATE = "skipped"

# The order a tally reads them out in.
ORDER = (PASSING, FAILING, SKIPPED_STATE, NEVER_RUN)


def state_of(skipped: bool, outcomes: Iterable[str]) -> str:
    """One word for how a scenario stands. A row that failed makes the whole scenario failing."""
    if skipped:
        return SKIPPED_STATE
    said = list(outcomes)
    if not said:
        return NEVER_RUN
    if any(outcome in {FAILED, ERROR} for outcome in said):
        return FAILING
    if all(outcome == SKIPPED for outcome in said):
        return SKIPPED_STATE
    return PASSING if all(outcome in {PASSED, SKIPPED} for outcome in said) else FAILING


def fold(outcomes: Iterable[str]) -> str:
    """The one outcome several rows of the same scenario amount to."""
    said = list(outcomes)
    if not said:
        return "not run"
    unique = set(said)
    if len(unique) == 1:
        return said[0]
    return FAILED if unique & {FAILED, ERROR} else "mixed"
