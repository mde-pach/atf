"""Folding a Scenario Outline's rows into one word.

Everything else `atf docs` does is said as scenarios in `specs/features/cli.feature` — a command is
run, a page is read back, and what it says is claimed about. This is the one part with no such
surface: a scenario written as an outline runs once per Examples row, the history holds one result
per row, and the page has one heading to put a verdict under. Which word that is, for every mix of
row outcomes, is a decision procedure over data and nothing else — and the mixes that matter (one
row of five failed; every row was skipped) cannot be arranged from a feature file without writing a
suite whose whole purpose is to fail in a shape.

Getting it wrong is quiet in exactly the way documentation must not be: a page would say `passing`
over a scenario one of whose rows did not.
"""

import pytest

from atf.run.runner import ERROR, FAILED, PASSED, SKIPPED
from atf.run.runner import TestResult as Result  # `Test*` at module level is something pytest collects
from atf.run.verdict import FAILING, NEVER_RUN, PASSING, SKIPPED_STATE
from atf.suite.discovery import Spec
from atf.suite.docs import state_of


def _spec(*, skipped: bool = False) -> Spec:
    return Spec(id="f::s", feature="F", scenario="S", skipped=skipped)


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([], NEVER_RUN),
        ([PASSED], PASSING),
        ([PASSED, PASSED], PASSING),
        # One row of many is enough: a scenario is not passing if part of it is not.
        ([PASSED, FAILED], FAILING),
        ([PASSED, ERROR], FAILING),
        # A skip is not a verdict, so it neither makes a scenario green nor stops it being green.
        ([PASSED, SKIPPED], PASSING),
        ([SKIPPED], SKIPPED_STATE),
        ([SKIPPED, SKIPPED], SKIPPED_STATE),
        ([SKIPPED, FAILED], FAILING),
    ],
)
def test_a_scenarios_word_is_the_worst_thing_any_of_its_rows_did(outcomes, expected):
    found = [Result(nodeid=f"f::s[{index}]", outcome=outcome) for index, outcome in enumerate(outcomes)]
    assert state_of(_spec(), found) == expected


def test_a_scenario_the_suite_skips_says_so_whatever_the_history_holds():
    """`@skip` is a decision in the file, and the file outranks a result from before it was made."""
    stale = [Result(nodeid="f::s", outcome=PASSED)]
    assert state_of(_spec(skipped=True), stale) == SKIPPED_STATE


def test_the_default_output_directory_is_written_down_once():
    """`cli.py` names it too, so that `atf docs` is the only command that imports discovery.

    Two spellings of one default is how drift starts, and this is the whole of the guard against it.
    """
    from atf.cli import DEFAULT_DOCS_OUT
    from atf.suite.docs import DEFAULT_OUT

    assert DEFAULT_DOCS_OUT == DEFAULT_OUT
