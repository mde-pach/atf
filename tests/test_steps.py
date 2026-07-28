"""The read-and-compare steps, exercised the only way that proves anything: through a real suite.

Every test here writes a `.feature` into the sample project and runs pytest against it in its own
process, so what is verified is the wording a scenario author writes — not a Python call.
"""

from __future__ import annotations

import json

import pytest
from _pytest.outcomes import Failed

from atf.steps import (
    COUNT,
    EXISTS,
    FIELD_CONTAINS,
    FIELD_EMPTY,
    FIELD_IS,
    FIELD_IS_NOT,
    FIELD_LACKS,
    FIELD_NOT_EMPTY,
    GENERIC_STEPS,
    GONE,
    SLOT_CONTAINS,
    SLOT_FIELD_CONTAINS,
    SLOT_FIELD_EMPTY,
    SLOT_FIELD_IS,
    SLOT_FIELD_IS_NOT,
    SLOT_FIELD_LACKS,
    SLOT_FIELD_NOT_EMPTY,
    SLOT_LACKS,
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
    SLOT_CONTAINS: 'the result contains the account "primary"',
    SLOT_LACKS: 'the result does not contain the account "secondary"',
    SLOT_FIELD_IS: 'the result field "plan" is "standard"',
    SLOT_FIELD_IS_NOT: 'the result field "plan" is not "trial"',
    FIELD_CONTAINS: 'the account "primary" field "email" contains "example.test"',
    FIELD_LACKS: 'the account "primary" field "email" does not contain "nowhere"',
    FIELD_EMPTY: 'the account "primary" field "notes" is empty',
    FIELD_NOT_EMPTY: 'the account "primary" field "plan" is not empty',
    SLOT_FIELD_CONTAINS: 'the result field "email" contains "example.test"',
    SLOT_FIELD_LACKS: 'the result field "email" does not contain "nowhere"',
    SLOT_FIELD_EMPTY: 'the result field "notes" is empty',
    SLOT_FIELD_NOT_EMPTY: 'the result field "plan" is not empty',
    COUNT: "the environment has 0 visitor",
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
    assert "the record carries email, id, notes, plan" in result.stdout


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
    assert "result contains projects.alpha, which it must not" in result.stdout
    assert "Looked for" in result.stdout


def test_asking_about_a_result_nothing_produced_says_so(project):
    feature = """Feature: Results
  Scenario: Nothing produced a result
    Given the account "primary"
    Then the result contains the account "primary"
"""
    result = run_feature(project, "no_result", feature)
    assert result.returncode != 0
    assert "nothing has put 'result' on the context" in result.stdout
    assert "context.result" in result.stdout
    # What it *does* hold, so a mistyped slot name is one line to fix rather than a hunt.
    assert "It holds: account (one account record carrying" in result.stdout


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


@pytest.mark.parametrize("pattern", [EXISTS, GONE, FIELD_IS])
def test_the_capture_table_covers_every_pattern(pattern):
    step = generic(pattern)
    assert step is not None
    assert step.captures[:2] == ("resource_type", "name")
    assert step.summary


def test_a_claim_about_a_slot_names_the_slot_first(project):
    """Which slot is half of what the claim says, so it is the first thing the pattern captures."""
    step = generic(SLOT_CONTAINS)
    assert step is not None
    assert step.captures == ("slot", "resource_type", "name")
    assert step.needs == (), "which slot it needs is the author's choice, not a fixed one"
    assert step.needs_slot


def test_a_project_step_is_not_in_the_table():
    assert generic("I read its plan") is None


# ---- a generated value, from the step that makes it to the step that checks it


RENAME = '''

import json
from pathlib import Path

from pytest_bdd import parsers, when


@when(parsers.parse('I rename it to "{title}"'))
def _(context, client_config, title):
    path = Path(__file__).parent.parent.parent / client_config["api"]["path"]
    data = json.loads(path.read_text())
    for record in data["accounts"]:
        if record["id"] == context.account["id"]:
            record["plan"] = title
    path.write_text(json.dumps(data, indent=2))
'''


def test_a_generated_value_survives_from_the_when_that_made_it_to_the_then(project):
    """The whole point of naming a provider: an action takes a generated value in, and the
    assertion checking it writes the same expression and sees the same answer."""
    feature = """Feature: Generated
  Scenario: An account reports the plan it was just moved to
    Given the account "primary"
    When I rename it to "${uuid}"
    Then the account "primary" field "plan" is "${uuid}"
"""
    result = run_feature(project, "generated", feature, RENAME)
    assert result.returncode == 0, result.stdout + result.stderr


def test_two_calls_are_told_apart_by_a_discriminator(project):
    feature = """Feature: Generated
  Scenario: Two generated values are not the same value
    Given the account "primary"
    When I rename it to "${uuid}"
    Then the account "primary" field "plan" is not "${uuid#other}"
"""
    result = run_feature(project, "discriminated", feature, RENAME)
    assert result.returncode == 0, result.stdout + result.stderr


def test_each_scenario_generates_its_own(project):
    """Values stand still within a scenario; across scenarios they must not."""
    feature = """Feature: Generated
  Scenario Outline: Every row gets its own value
    Given the account "<who>"
    When I rename it to "${uuid}"
    Then the account "<who>" field "plan" is "${uuid}"

    Examples:
      | who       |
      | primary   |
      | secondary |
"""
    result = run_feature(project, "per_scenario", feature, RENAME)
    assert result.returncode == 0, result.stdout + result.stderr

    plans = {record["plan"] for record in json.loads((project / "store.json").read_text())["accounts"]}
    assert len(plans) == 2, "one value per scenario, not one for the whole run"


def test_a_placeholder_that_cannot_resolve_says_which_one(project):
    feature = """Feature: Generated
  Scenario: A provider nobody registered
    Given the account "primary"
    Then the account "primary" field "plan" is "${nosuchprovider:x}"
"""
    result = run_feature(project, "unknown_provider", feature)
    assert result.returncode != 0
    assert "no provider registered as 'nosuchprovider'" in result.stdout


# ---- asserting on a field of what a step produced ---------------------------


def test_a_field_of_what_a_step_produced_is_compared(project):
    """Your rename example, whole: an action takes a generated value in, and the assertion checks
    the value that came back against the same expression."""
    feature = """Feature: Produced
  Scenario: The rename comes back in what the API returned
    Given the account "primary"
    When I rename it to "${uuid}"
    Then the result field "plan" is "${uuid}"
    And the result field "plan" is not "standard"
"""
    steps = '''

import json
from pathlib import Path

from pytest_bdd import parsers, when


@when(parsers.parse('I rename it to "{title}"'))
def _(context, client_config, title):
    path = Path(__file__).parent.parent.parent / client_config["api"]["path"]
    data = json.loads(path.read_text())
    for record in data["accounts"]:
        if record["id"] == context.account["id"]:
            record["plan"] = title
            context.result = dict(record)
    path.write_text(json.dumps(data, indent=2))
'''
    result = run_feature(project, "produced", feature, steps)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_field_assertion_on_a_listing_says_to_use_contains(project):
    feature = """Feature: Produced
  Scenario: A listing has no one field
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the result field "slug" is "alpha"
"""
    steps = '''

from pytest_bdd import when


@when("I list the projects of the account")
def _(context, api):
    context.result = [{"slug": "alpha"}, {"slug": "beta"}]
'''
    result = run_feature(project, "listing_field", feature, steps)
    assert result.returncode != 0
    assert "a field assertion needs one" in result.stdout
    assert 'the result contains the <type>' in result.stdout


def test_an_unknown_field_on_the_result_lists_what_it_carries(project):
    feature = """Feature: Produced
  Scenario: The result has no such field
    Given the account "primary"
    When I read its plan
    Then the result field "nope" is "x"
"""
    steps = '''

from pytest_bdd import when


@when("I read its plan")
def _(context):
    context.result = {"plan": context.account["plan"]}
'''
    result = run_feature(project, "unknown_result_field", feature, steps)
    assert result.returncode != 0
    assert "result has no field 'nope' — it carries plan" in result.stdout


# ---- matchers --------------------------------------------------------------
#
# `is` and `is not` were the whole vocabulary for a value, so every suite wrote its own
# `the output mentions "…"`. These are the same claim generalised, and the point of each test
# below is a kind of value where containment or emptiness means something different.


HOLDS = '''

from pytest_bdd import when


@when("I read what it holds")
def _(context):
    context.result = {"tags": ["red", "green"], "meta": {"a": 1}, "count": 12}
'''


def test_containment_reaches_into_a_list_the_way_a_field_is_matched(project):
    feature = """Feature: Matchers
  Scenario: A list holds an item
    Given the account "primary"
    When I read what it holds
    Then the result field "tags" contains "red"
    And the result field "tags" does not contain "blue"
    And the result field "count" contains "1"
    And the result field "tags" is not empty
"""
    result = run_feature(project, "containment", feature, HOLDS)
    assert result.returncode == 0, result.stdout + result.stderr


def test_containment_over_a_record_is_refused_rather_than_guessed(project):
    """A record holds keys and values both, so `contains` cannot say which was meant."""
    feature = """Feature: Matchers
  Scenario: A record is not something `contains` can answer about
    Given the account "primary"
    When I read what it holds
    Then the result field "meta" contains "a"
"""
    result = run_feature(project, "uncontainable", feature, HOLDS)
    assert result.returncode != 0
    assert "a record holds keys and values both" in result.stdout
    assert "Name the field inside it instead." in result.stdout


def test_a_wrong_count_says_what_the_environment_actually_holds(project):
    feature = """Feature: Matchers
  Scenario: The environment holds one visitor, not three
    Given the visitor "walkin"
    Then the environment has 3 visitor
"""
    result = run_feature(project, "miscount", feature)
    assert result.returncode != 0
    assert "dev holds 1 visitor record, not 3" in result.stdout


def test_counting_an_unknown_type_lists_the_ones_there_are(project):
    feature = """Feature: Matchers
  Scenario: Counting something the catalog never declared
    Given the account "primary"
    Then the environment has 1 acount
"""
    result = run_feature(project, "miscount_type", feature)
    assert result.returncode != 0
    assert "no resource type 'acount' in the catalog" in result.stdout


def test_counting_says_so_when_the_adapter_cannot_list():
    """`browse` is optional SPI, so the claim has to degrade with the reason, not an AttributeError."""
    from types import SimpleNamespace

    from atf.steps import _listing

    engine = SimpleNamespace(
        env="dev",
        types={"thing": {"system": "flat"}},
        adapters={"flat": object()},
        resource_types=lambda: ["thing"],
    )
    with pytest.raises(Failed) as caught:
        _listing(engine, "thing")
    assert "cannot list what an environment holds" in str(caught.value)
    assert "`browse`" in str(caught.value)
