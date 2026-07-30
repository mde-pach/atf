"""A run translated into CTRF, and the two translations that decide what runs.

That `atf run --json` writes a file is a scenario — `specs/features/cli.feature` runs the real
command against a real suite and reads what it said. What is here is the *shape* of what it wrote,
which is a pure function over a `RunRecord` and has no observable surface of its own: a scenario
could only claim that a file exists, and the whole value of the flag is that its contents mean
something to software ATF has never heard of.
"""

from __future__ import annotations

import pytest

from atf.run.report import as_ctrf
from atf.run.runner import (
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    RunRecord,
    StepResult,
    keyword_expression,
    tag_expression,
)
from atf.run.runner import TestResult as Result  # not `TestResult`: pytest tries to collect the name


def record(**results: Result) -> RunRecord:
    return RunRecord(
        id="abcd1234",
        env="ci",
        started_at=1_700_000_000.0,
        finished_at=1_700_000_012.5,
        duration=12.5,
        returncode=1,
        results={name.replace("__", "::"): result for name, result in results.items()},
    )


def test_a_run_is_a_ctrf_document():
    document = as_ctrf(record(a__one=Result(nodeid="a::one", outcome=PASSED, duration=1.25)))

    assert document["reportFormat"] == "CTRF"
    assert document["results"]["tool"]["name"] == "atf"
    assert document["results"]["environment"]["testEnvironment"] == "ci"
    assert document["results"]["tests"] == [{"name": "a::one", "status": "passed", "duration": 1250}]


def test_an_error_is_reported_as_a_failure():
    """A gate that treats "it broke before it started" as softer than a failure lets a broken suite
    through, and CTRF has no word of its own for it."""
    document = as_ctrf(
        record(
            a__ok=Result(nodeid="a::ok", outcome=PASSED),
            a__broke=Result(nodeid="a::broke", outcome=ERROR),
            a__failed=Result(nodeid="a::failed", outcome=FAILED),
            a__skipped=Result(nodeid="a::skipped", outcome=SKIPPED),
        )
    )

    summary = document["results"]["summary"]
    assert summary == {
        "tests": 4,
        "passed": 1,
        "failed": 2,
        "pending": 0,
        "skipped": 1,
        "other": 0,
        "start": 1_700_000_000_000,
        "stop": 1_700_000_012_500,
    }
    # Sorted by nodeid, which is what makes two reports of the same run comparable byte for byte.
    assert [(test["name"], test["status"]) for test in document["results"]["tests"]] == [
        ("a::broke", "failed"),
        ("a::failed", "failed"),
        ("a::ok", "passed"),
        ("a::skipped", "skipped"),
    ]


def test_the_gherkin_step_a_scenario_stopped_on_survives_the_translation():
    """The useful unit of failure for a BDD suite, and the first thing a person reading CI wants.

    CTRF has no field for it, so it goes in the message rather than being dropped for want of a home.
    """
    failed = Result(
        nodeid="lists::a-list-belongs",
        outcome=FAILED,
        detail="E   assert 1 == 2",
        steps=[
            StepResult(keyword="Given", text='the owner "primary"', state="passed"),
            StepResult(keyword="Then", text="the list belongs to the owner", state=FAILED),
        ],
    )
    test = as_ctrf(record(lists__a_list_belongs=failed))["results"]["tests"][0]

    assert test["message"] == "Then the list belongs to the owner"
    assert test["trace"] == "E   assert 1 == 2"


def test_a_run_that_says_nothing_is_still_a_document():
    """A run that collected nothing has to be readable by the same gate as one that did."""
    document = as_ctrf(record())
    assert document["results"]["tests"] == []
    assert document["results"]["summary"]["tests"] == 0


# ---- choosing what runs ------------------------------------------------------
#
# Which scenarios a flag selects is `specs/features/cli.feature`, against a real suite. These are
# the two translations underneath it: a person's words into something pytest can match, and several
# tags into the one expression it takes.


@pytest.mark.parametrize(
    ("typed", "matched"),
    [
        ("on its own", "on_its_own"),
        ("A list belongs to its owner", "a_list_belongs_to_its_owner"),
        ("  spaced  out  ", "spaced_out"),
        ("already_underscored", "already_underscored"),
        # Left alone: somebody writing an expression means it, and rewriting it would break it.
        ("lists and not slow", "lists and not slow"),
        ("(one or two)", "(one or two)"),
    ],
)
def test_a_persons_words_reach_pytest_as_something_it_can_match(typed, matched):
    assert keyword_expression(typed) == matched


def test_several_tags_mean_any_of_them():
    """`--tag smoke --tag api` reads as "the smoke ones and the api ones", which is a union."""
    assert tag_expression(["smoke", "api"]) == "smoke or api"


def test_a_tag_may_be_written_the_way_it_is_written_on_the_scenario():
    """`@` is how a tag is said, not part of its name — as the manifest's `requires:` also has it."""
    assert tag_expression(["@browser"]) == "browser"
