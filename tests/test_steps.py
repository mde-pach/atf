"""The read-and-compare steps, exercised the only way that proves anything: through a real suite.

Every test here writes a `.feature` into the sample project and runs pytest against it in its own
process, so what is verified is the wording a scenario author writes — not a Python call.
"""

from __future__ import annotations

import json

import pytest

from atf.steps import (
    EXISTS,
    FIELD_IS,
    FIELD_IS_NOT,
    GENERIC_STEPS,
    GONE,
    RESULT_CONTAINS,
    RESULT_LACKS,
    generic,
)
from tests.sample_project import run_pytest, write_spec

# A `When` the sample project does not have: something that changes a resource behind ATF's back,
# which is what makes "the assertion re-reads" a claim worth testing rather than a coincidence.
MUTATE = '''

import json
from pathlib import Path

from pytest_bdd import parsers, when


@when(parsers.parse('I set its plan to "{plan}"'))
def _(context, client_config, plan):
    path = Path(__file__).parent.parent.parent / client_config["api"]["path"]
    data = json.loads(path.read_text())
    for record in data["accounts"]:
        if record["id"] == context.account["id"]:
            record["plan"] = plan
    path.write_text(json.dumps(data, indent=2))
'''


def run_feature(project, name, feature, steps="", **kwargs):
    write_spec(project, name, feature, steps)
    return run_pytest(project, "-q", "-p", "no:randomly", f"specs/steps/test_{name}.py", **kwargs)


# ---- the vocabulary is registered and offered ------------------------------


# One line per generic `Then`, written the way it would be written, chosen so that all of them hold
# at once against the sample project. A pattern in the table and no line here is a wording nothing
# proves; a line here and no pattern is a wording that would be offered and then not match.
PASSING = {
    EXISTS: 'the account "primary" exists',
    GONE: 'the account "secondary" is gone',
    FIELD_IS: 'the account "primary" field "plan" is "standard"',
    FIELD_IS_NOT: 'the account "primary" field "plan" is not "trial"',
    RESULT_CONTAINS: 'the result contains the account "primary"',
    RESULT_LACKS: 'the result does not contain the account "secondary"',
}


def test_the_table_lists_exactly_the_thens_that_are_proved():
    assert {step.pattern for step in GENERIC_STEPS if step.keyword == "then"} == set(PASSING)


def test_every_then_in_the_table_resolves_to_a_registered_definition(project):
    """A pattern in the table with nothing behind it would be offered by the composer, then fail.

    What is under test is that each wording is *matched* by a registered step definition — hence
    one scenario holding every one of them at once, and a plain `no step definition matches` check
    beside the outcome.
    """
    lines = ['    Given the account "primary"', "    When I hold the account"]
    lines += [f"    Then {PASSING[step.pattern]}" for step in GENERIC_STEPS if step.keyword == "then"]

    steps = '''

from pytest_bdd import when


@when("I hold the account")
def _(context):
    context.result = [context.account]
'''
    feature = "Feature: Registered\n  Scenario: Every generic Then resolves\n" + "\n".join(lines) + "\n"
    result = run_feature(project, "registered", feature, steps)
    assert "no step definition matches" not in result.stdout
    assert result.returncode == 0, result.stdout + result.stderr


# ---- reading a resource back -----------------------------------------------


def test_a_provisioned_resource_exists_and_its_fields_read(project):
    feature = """Feature: Reading back
  Scenario: A provisioned account is there with the plan it declares
    Given the account "primary"
    Then the account "primary" exists
    And the account "primary" field "plan" is "standard"
    And the account "primary" field "plan" is not "trial"
"""
    result = run_feature(project, "reading", feature)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_resource_nothing_provisioned_is_gone(project):
    feature = """Feature: Absence
  Scenario: An account nothing asked for is not here
    Then the account "secondary" is gone
"""
    result = run_feature(project, "absence", feature)
    assert result.returncode == 0, result.stdout + result.stderr


def test_is_gone_fails_while_the_resource_is_still_there(project):
    feature = """Feature: Absence
  Scenario: A provisioned account is not gone
    Given the account "primary"
    Then the account "primary" is gone
"""
    result = run_feature(project, "still_there", feature)
    assert result.returncode != 0
    assert "accounts.primary is still in dev" in result.stdout


def test_exists_fails_naming_what_it_looked_for(project):
    feature = """Feature: Absence
  Scenario: An account nothing provisioned does not exist
    Then the account "secondary" exists
"""
    result = run_feature(project, "missing", feature)
    assert result.returncode != 0
    assert "nothing in dev matches accounts.secondary" in result.stdout
    assert "email='secondary@example.test'" in result.stdout


# ---- the point of the whole design: the assertion re-reads ------------------


def test_an_assertion_sees_what_a_when_changed(project):
    """The `When` is hand-written code changing a real backend; the `Then` is still generic.

    This is what catalog-resolved assertions buy. A step that compared against the record the
    scenario provisioned would still be reporting `standard` here.
    """
    feature = """Feature: Re-reading
  Scenario: An account reports the plan it was just moved to
    Given the account "primary"
    When I set its plan to "trial"
    Then the account "primary" field "plan" is "trial"
    And the account "primary" field "plan" is not "standard"
"""
    result = run_feature(project, "rereading", feature, MUTATE)
    assert result.returncode == 0, result.stdout + result.stderr

    store = json.loads((project / "store.json").read_text())
    assert [record["plan"] for record in store["accounts"]] == ["trial"]


# ---- what a failure says ---------------------------------------------------


def test_a_wrong_value_names_both_sides_and_their_kinds(project):
    feature = """Feature: Failing
  Scenario: The plan is not what was written
    Given the account "primary"
    Then the account "primary" field "plan" is "enterprise"
"""
    result = run_feature(project, "wrong_value", feature)
    assert result.returncode != 0
    assert 'field \'plan\' is "standard", not "enterprise"' in result.stdout


def test_an_unknown_field_lists_what_the_record_carries(project):
    feature = """Feature: Failing
  Scenario: The field does not exist on the record
    Given the account "primary"
    Then the account "primary" field "tier" is "gold"
"""
    result = run_feature(project, "unknown_field", feature)
    assert result.returncode != 0
    assert "has no field 'tier' in dev" in result.stdout
    assert "the record carries email, id, plan" in result.stdout


def test_an_unknown_resource_type_says_which_types_there_are(project):
    feature = """Feature: Failing
  Scenario: The type is a typo
    Then the acount "primary" exists
"""
    result = run_feature(project, "unknown_type", feature)
    assert result.returncode != 0
    assert "no resource type 'acount' in the catalog" in result.stdout


def test_an_unknown_instance_says_which_instances_there_are(project):
    feature = """Feature: Failing
  Scenario: The name is a typo
    Then the account "primry" exists
"""
    result = run_feature(project, "unknown_name", feature)
    assert result.returncode != 0
    assert "the catalog declares no account called 'primry'" in result.stdout
    assert "it declares: primary, secondary" in result.stdout


# ---- asserting on what a step produced -------------------------------------


def test_the_result_contains_a_resource(project):
    feature = """Feature: Results
  Scenario: A project is among the ones its account has
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the result contains the project "alpha"
"""
    steps = '''

from pytest_bdd import when


@when("I list the projects of the account")
def _(context, api):
    context.result = api.projects_of(context.account)
'''
    result = run_feature(project, "results", feature, steps)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_result_not_containing_a_resource_fails_saying_what_was_compared(project):
    feature = """Feature: Results
  Scenario: A project is wrongly expected to be absent
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the result does not contain the project "alpha"
"""
    steps = '''

from pytest_bdd import when


@when("I list the projects of the account")
def _(context, api):
    context.result = api.projects_of(context.account)
'''
    result = run_feature(project, "results_absent", feature, steps)
    assert result.returncode != 0
    assert "the result contains projects.alpha, which it must not" in result.stdout
    assert "Looked for" in result.stdout


def test_asking_about_a_result_nothing_produced_says_so(project):
    feature = """Feature: Results
  Scenario: Nothing produced a result
    Given the account "primary"
    Then the result contains the account "primary"
"""
    result = run_feature(project, "no_result", feature)
    assert result.returncode != 0
    assert "nothing has produced a result yet" in result.stdout
    assert "context.result" in result.stdout


def test_a_result_that_is_not_records_says_what_it_is(project):
    feature = """Feature: Results
  Scenario: The result is a plain value
    Given the account "primary"
    When I read its plan
    Then the result contains the account "primary"
"""
    steps = '''

from pytest_bdd import when


@when("I read its plan")
def _(context):
    context.result = context.account["plan"]
'''
    result = run_feature(project, "scalar_result", feature, steps)
    assert result.returncode != 0
    assert 'context.result holds "standard", which is not a record' in result.stdout


# ---- ephemeral resources ---------------------------------------------------


def test_an_ephemeral_resource_is_read_from_what_the_scenario_built(project):
    """It is never looked up — that is what ephemeral means — so the built record is the only one."""
    feature = """Feature: Ephemeral
  Scenario: A visitor carries the state provisioning left it in
    Given the visitor "walkin"
    Then the visitor "walkin" field "state" is "ready"
    And the visitor "walkin" exists
"""
    result = run_feature(project, "ephemeral_read", feature)
    assert result.returncode == 0, result.stdout + result.stderr


def test_is_gone_refuses_on_an_ephemeral_resource_instead_of_passing_vacuously(project):
    feature = """Feature: Ephemeral
  Scenario: Whether a visitor is gone cannot be answered
    Given the visitor "walkin"
    Then the visitor "walkin" is gone
"""
    result = run_feature(project, "ephemeral_gone", feature)
    assert result.returncode != 0
    assert "is ephemeral, so ATF never looks one up" in result.stdout


def test_an_ephemeral_resource_the_scenario_never_built_is_reported_as_such(project):
    feature = """Feature: Ephemeral
  Scenario: Nothing built a visitor
    Then the visitor "walkin" exists
"""
    result = run_feature(project, "ephemeral_absent", feature)
    assert result.returncode != 0
    assert "this scenario has not provisioned visitors.walkin" in result.stdout


# ---- the table ------------------------------------------------------------


@pytest.mark.parametrize("pattern", [EXISTS, GONE, FIELD_IS, RESULT_CONTAINS])
def test_the_capture_table_covers_every_pattern(pattern):
    step = generic(pattern)
    assert step is not None
    assert step.captures[:2] == ("resource_type", "name")
    assert step.summary


def test_a_project_step_is_not_in_the_table():
    assert generic("I read its plan") is None
