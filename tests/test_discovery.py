"""Reading a suite without running it: a parser and a static analyser.

The plan expected most of this to become scenarios, on the grounds that the cockpit's pages are
discovery's output. The pages did become scenarios — `specs/features/cockpit.feature` claims what
the catalog page lists, what a scenario page links to, and that the composer offers ATF's own steps
beside the suite's. That is discovery's output, checked through the surface a person sees.

What is left is the machinery underneath, and it is two pure functions over text:

**A parser.** Feature files in, scenarios out — narrative, tags, `Rule:` groupings, `Background:`
steps belonging to every scenario, Examples rows expanded, and the catalog resources each step line
names. Its inputs are files and its outputs are dataclasses; a scenario could only ever observe it
second-hand, through something that renders what it produced.

**A static analyser.** `context_use` reads a step function's source to say what it takes off the
context and what it puts back, so the composer can offer a claim about a slot only once a step above
has produced one. That claim *is* a scenario — but that this analysis reads `context.result = ...`
as a write and `context.result` as a read is a fact about parsing Python, not about a suite.

Both are decision procedures over source text, and a truth table is the honest description.
"""


from __future__ import annotations

import os
import re

import pytest

from atf.catalog import load_catalog
from atf.discovery import (
    PROVISION_PATTERN,
    Discovery,
    StepDef,
    context_use,
    discover,
    fill,
    matching_step,
    parse_feature,
    pattern_regex,
    slug,
)
from atf.discovery import _step_defs as step_defs
from atf.steps import EXISTS, GENERIC_STEPS, SLOT_CONTAINS
from tests.sample_project import write_sample_project

REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("PYTHONPATH", REPO_SRC)
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    return root


@pytest.fixture
def catalog(project):
    from atf.adapters import register, unregister

    class Null:
        def find(self, node, ctx):
            return None

        def create(self, node, body, ctx):
            return {}

        def delete(self, node, record, ctx):
            return None

    for system in ("store", "ephemeral"):
        register(system, lambda settings: Null())
    types, nodes = load_catalog(project / "catalog", {"store", "ephemeral"})
    yield types, nodes
    for system in ("store", "ephemeral"):
        unregister(system)


@pytest.fixture
def found(project, catalog):
    types, nodes = catalog
    return discover(project / "specs", nodes, set(types), "dev", project)


def test_slug():
    assert slug("A standard account reports its plan") == "a-standard-account-reports-its-plan"
    assert slug("  ") == "untitled"


def test_specs_are_parsed_with_narrative_tags_and_steps(found):
    spec = found.spec("accounts::a-standard-account-reports-its-plan")
    assert spec is not None
    assert spec.feature == "Accounts"
    assert spec.scenario == "A standard account reports its plan"
    assert spec.narrative == "Accounts carry a plan and own projects."
    assert [(step.keyword, step.text) for step in spec.steps] == [
        ("Given", 'the account "primary"'),
        ("When", "I read its plan"),
        ("Then", 'the plan is "standard"'),
    ]
    assert spec.resources == ["accounts.primary"]


def test_tags_and_skips(found):
    spec = found.spec("accounts::a-skipped-behaviour")
    assert spec is not None
    assert spec.tags == ["wip"]
    assert spec.skipped is True


def test_dependency_chain_is_linked_per_step(found):
    spec = found.spec("accounts::a-project-belongs-to-its-account")
    assert spec is not None
    assert spec.resources == ["accounts.primary", "projects.alpha"]
    assert spec.steps[0].resources == ["accounts.primary"]
    assert spec.steps[1].resources == ["projects.alpha"]
    assert spec.steps[2].resources == []


def test_scenario_outline_placeholders_expand_through_examples(found):
    spec = found.spec("accounts::accounts-report-their-own-plan")
    assert spec is not None
    assert spec.examples == [
        {"who": "primary", "plan": "standard"},
        {"who": "secondary", "plan": "trial"},
    ]
    assert set(spec.resources) == {"accounts.primary", "accounts.secondary"}


def test_non_type_phrases_are_ignored(tmp_path, catalog):
    types, nodes = catalog
    feature = tmp_path / "noise.feature"
    feature.write_text(
        "Feature: Noise\n"
        "  Scenario: Chatter\n"
        '    Given the account "primary"\n'
        '    When the account requests "a refund"\n'
        '    Then the response "message" is shown\n',
        encoding="utf-8",
    )
    specs = parse_feature(feature, nodes, set(types))
    assert specs[0].resources == ["accounts.primary"]
    assert specs[0].steps[1].resources == []
    assert specs[0].steps[2].resources == []


def test_unknown_instance_name_links_nothing(tmp_path, catalog):
    types, nodes = catalog
    feature = tmp_path / "typo.feature"
    feature.write_text(
        'Feature: Typo\n  Scenario: Missing\n    Given the account "ghost"\n', encoding="utf-8"
    )
    assert parse_feature(feature, nodes, set(types))[0].resources == []


def test_tests_are_observed_and_linked_to_their_spec(found):
    assert found.errors == []
    spec = found.spec("accounts::a-standard-account-reports-its-plan")
    assert spec is not None and len(spec.test_ids) == 1

    tests = found.tests_for_spec(spec.id)
    assert len(tests) == 1
    test = tests[0]
    assert test.nodeid.endswith("test_accounts.py::test_a_standard_account_reports_its_plan")
    assert test.resources == ["accounts.primary"]
    assert "account" in test.fixtures
    assert "api" in test.fixtures
    assert test.skipped is False


def test_outline_rows_become_one_test_each_with_their_own_resource(found):
    tests = found.tests_for_spec("accounts::accounts-report-their-own-plan")
    assert len(tests) == 2
    by_params = {test.params: test for test in tests}
    assert by_params["primary-standard"].resources == ["accounts.primary"]
    assert by_params["secondary-trial"].resources == ["accounts.secondary"]


def test_skipped_tests_are_marked(found):
    tests = found.tests_for_spec("accounts::a-skipped-behaviour")
    assert tests and all(test.skipped for test in tests)


def test_fixtures_include_generated_factories_with_their_users(found):
    account = found.fixture("account")
    assert account is not None
    assert account.generated is True
    assert "Provision a `account` by catalog name" in account.doc
    assert any("test_a_standard_account_reports_its_plan" in nodeid for nodeid in account.used_by)

    materializer = found.fixture("materializer")
    assert materializer is not None and materializer.scope == "session"

    api = found.fixture("api")
    assert api is not None and api.generated is False


def test_resource_back_links(found):
    assert [spec.id for spec in found.specs_for_resource("projects.alpha")] == [
        "accounts::a-project-belongs-to-its-account"
    ]
    assert found.tests_for_resource("visitors.walkin")


def test_discovery_degrades_gracefully_when_the_run_errors(project, catalog):
    types, nodes = catalog
    (project / "specs" / "steps" / "test_broken.py").write_text("import nonexistent_module\n", encoding="utf-8")
    found = discover(project / "specs", nodes, set(types), "dev", project)
    assert found.specs  # static parse still works
    assert found.errors


def test_discovery_with_no_features(tmp_path, catalog):
    types, nodes = catalog
    empty = tmp_path / "nothing"
    empty.mkdir()
    found = discover(empty, nodes, set(types), "dev", tmp_path)
    assert found.specs == []


def test_discovery_never_provisions_anything(project, catalog):
    """Discovery runs on every cockpit page render, including for read-only environments.

    It must therefore collect the suite, never execute it — otherwise viewing a page mutates
    the environment behind the `mutable_envs` gate.
    """
    types, nodes = catalog
    store = project / "store.json"
    store.unlink(missing_ok=True)

    found = discover(project / "specs", nodes, set(types), "locked", project)

    assert found.tests, "collection still has to find the tests"
    assert not store.exists(), "discovery provisioned resources into a read-only environment"


def test_discovery_links_fixtures_without_running(found):
    """The fixture closure survives the move to --collect-only."""
    test = next(item for item in found.tests if "standard_account" in item.nodeid)
    assert "account" in test.fixtures  # generated factory, attributed from the catalog
    assert "api" in test.fixtures  # declared by the step definition
    assert "context" in test.fixtures


# ---- step definitions: the vocabulary a scenario may be written in ----------


def test_step_definitions_are_discovered_with_their_captures(found):
    """The composer can only offer wordings that really exist, so they are read from the registry."""
    by_pattern = {step.pattern: step for step in found.steps}

    plan = by_pattern['the plan is "{expected}"']
    assert plan.keyword == "then"
    assert plan.params == ["expected"]
    assert plan.file.endswith("test_accounts.py")

    assert by_pattern["I read its plan"].keyword == "when"
    assert by_pattern["I read its plan"].params == []
    assert by_pattern["I list the projects of the account"].keyword == "when"
    assert by_pattern['the project "{name}" is listed'].params == ["name"]


def test_steps_no_scenario_uses_yet_are_still_discovered(found):
    """A picker that only showed steps already in use could never help write a new scenario."""
    assert 'the state is "{expected}"' in {step.pattern for step in found.steps_for("then")}


def test_the_generic_provisioning_step_is_a_given_and_only_a_given(found):
    """It is offered as the resource picker instead, and twice would teach the wrong model."""
    provisioning = next(step for step in found.steps if step.pattern == PROVISION_PATTERN)
    assert provisioning.keyword == "given"
    assert provisioning.params == ["resource_type", "name"]
    assert "provisions accounts.primary" in provisioning.docstring

    assert PROVISION_PATTERN in {step.pattern for step in found.steps_for("given")}
    for keyword in ("when", "then"):
        assert PROVISION_PATTERN not in {step.pattern for step in found.steps_for(keyword)}


def test_the_read_and_compare_steps_are_part_of_every_suites_vocabulary(found):
    """They are registered by the plugin, so a project gets them without defining anything.

    This is what makes them offerable in the composer: nothing about them is special-cased there,
    they simply arrive through discovery like any other step the suite can use.
    """
    offered = {step.pattern for step in found.steps_for("then")}
    assert {step.pattern for step in GENERIC_STEPS if step.keyword == "then"} <= offered

    reading = next(step for step in found.steps if step.pattern == EXISTS)
    assert reading.params == ["resource_type", "name"]
    assert reading.docstring
    assert reading.file.endswith("steps.py")


def test_a_step_declares_what_it_touches_on_the_context_by_being_read(found):
    """Steps talk to each other through `context`, and nothing outside a step's body knew which
    attributes — which is why someone could compose a step whose subject was never provisioned."""
    reads = next(step for step in found.steps if step.pattern == "I list the projects of the account")
    assert reads.needs == ["account"]
    assert reads.produces == ["result"]

    asserts = next(step for step in found.steps if step.pattern == 'the plan is "{expected}"')
    assert asserts.needs == ["result"]
    assert asserts.produces == []


def test_atfs_own_steps_declare_what_they_need_rather_than_being_read(found):
    """They reach the context through `getattr`, which no walk over attributes can see."""
    contains = next(step for step in found.steps if step.pattern == SLOT_CONTAINS)
    assert contains.needs == [], "which slot it reads is named in the step, not fixed in advance"
    assert contains.needs_slot

    reads_nothing = next(step for step in found.steps if step.pattern == EXISTS)
    assert reads_nothing.needs == [], "it resolves from the catalog, so it needs nothing put there"


def test_pytest_bdds_own_debugging_step_is_not_part_of_a_projects_vocabulary(found):
    assert "trace" not in {step.pattern for step in found.steps}


def test_a_keywordless_step_is_offered_under_every_keyword():
    """`@step` without a type matches any keyword, so a picker must offer it under all three."""
    found = Discovery(steps=[StepDef(keyword="*", pattern="something happens")])
    for keyword in ("given", "when", "then"):
        assert [step.pattern for step in found.steps_for(keyword)] == ["something happens"]


def test_step_definitions_are_deduplicated_and_junk_is_dropped():
    observed = {
        "steps": [
            {"keyword": "when", "pattern": "I wait", "params": []},
            {"keyword": "WHEN", "pattern": "I wait", "params": []},
            {"keyword": "when", "pattern": "", "params": []},
            {"keyword": "nonsense", "pattern": "I wait", "params": []},
        ]
    }
    assert [(step.keyword, step.pattern) for step in step_defs(observed)] == [("when", "I wait")]


def test_discovery_without_pytest_bdd_information_degrades_to_no_steps():
    assert step_defs({}) == []


def test_a_pattern_is_filled_in_and_matched_back(found):
    then_steps = found.steps_for("then")
    assert fill('the plan is "{expected}"', {"expected": "standard"}) == 'the plan is "standard"'
    assert fill('the plan is "{expected}"', {}) == 'the plan is "{expected}"'

    matched = matching_step('the plan is "standard"', then_steps)
    assert matched is not None and matched.pattern == 'the plan is "{expected}"'
    assert matching_step("I read its plan", found.steps_for("when")) is not None
    assert matching_step("a wording nobody defined", then_steps) is None
    # A `Then` wording is not offered for a `When`, so the two pickers cannot be confused.
    assert matching_step('the plan is "standard"', found.steps_for("when")) is None


def test_a_pattern_read_as_a_regex_keeps_its_literals_literal():
    assert re.fullmatch(pattern_regex('the plan is "{expected}"'), 'the plan is "standard"')
    assert re.fullmatch(pattern_regex("a.b {x}"), "a.b anything")
    assert not re.fullmatch(pattern_regex("a.b {x}"), "axb anything")


def test_a_step_declared_with_a_regex_parser_still_matches():
    """`parsers.re` leaves a regular expression as the pattern, so matching has to try it as one."""
    steps = [StepDef(keyword="then", pattern=r"the plan is (?P<expected>\w+)")]
    assert matching_step("the plan is standard", steps) is steps[0]
    assert matching_step("the plan was standard", steps) is None


def test_background_steps_belong_to_every_scenario(tmp_path, catalog):
    """Background runs before each scenario, so its resources are the scenario's resources."""
    types, nodes = catalog
    feature = tmp_path / "background.feature"
    feature.write_text(
        "Feature: Shared setup\n"
        "  Every scenario needs the same account.\n"
        "\n"
        "  Background:\n"
        '    Given the account "primary"\n'
        "\n"
        "  Scenario: One\n"
        '    Given the project "alpha"\n'
        "    Then it is fine\n"
        "\n"
        "  Scenario: Two\n"
        "    Then it is also fine\n",
        encoding="utf-8",
    )

    one, two = parse_feature(feature, nodes, set(types))

    assert [step.text for step in one.steps] == [
        'the account "primary"',
        'the project "alpha"',
        "it is fine",
    ]
    assert one.resources == ["accounts.primary", "projects.alpha"]
    assert two.resources == ["accounts.primary"]
    # the Background step must not leak into the prose
    assert one.narrative == "Every scenario needs the same account."


# ---- reading what a step touches, without running it ------------------------


def context_use_of(tmp_path, source: str):
    module = tmp_path / "steps_module.py"
    module.write_text(source, encoding="utf-8")
    return context_use(module)


def test_several_wordings_on_one_function_all_get_its_needs(tmp_path):
    use = context_use_of(
        tmp_path,
        'from pytest_bdd import then, parsers\n\n'
        '@then("it is fine")\n'
        '@then(parsers.parse(\'it is "{how}"\'))\n'
        "def _(context):\n"
        "    assert context.result\n",
    )
    assert use["it is fine"] == (["result"], [])
    assert use['it is "{how}"'] == (["result"], [])


def test_a_step_that_rewrites_what_it_was_given_both_needs_and_produces_it(tmp_path):
    use = context_use_of(
        tmp_path,
        'from pytest_bdd import when\n\n@when("I filter them")\n'
        "def _(context):\n    context.result = [x for x in context.result if x]\n",
    )
    assert use["I filter them"] == (["result"], ["result"])


def test_a_function_that_does_not_take_the_context_is_not_analysed(tmp_path):
    use = context_use_of(
        tmp_path,
        'from pytest_bdd import when\n\n@when("I do a thing")\ndef _(api):\n    api.go()\n',
    )
    assert use == {}


def test_atfs_own_bookkeeping_is_not_a_dependency(tmp_path):
    use = context_use_of(
        tmp_path,
        'from pytest_bdd import then\n\n@then("teardown ran")\n'
        "def _(context):\n    assert context._ephemeral == []\n",
    )
    assert use["teardown ran"] == ([], [])


def test_a_module_that_will_not_parse_says_nothing_rather_than_raising(tmp_path):
    """Discovery runs on every page render. A half-written steps module must not take a page down."""
    assert context_use_of(tmp_path, "def broken(:\n") == {}
    assert context_use(tmp_path / "not-there.py") == {}


# ---- phrases ---------------------------------------------------------------


PHRASEBOOK = '''
'the account is on the standard plan':
  - the account "primary" exists
  - the account "primary" field "plan" is "standard"
'the plan came back right':
  - the result field "plan" is "standard"
'''


@pytest.fixture
def phrased(project, catalog):
    (project / "specs" / "phrasebook.yaml").write_text(PHRASEBOOK, encoding="utf-8")
    types, nodes = catalog
    return discover(project / "specs", nodes, set(types), "dev", project)


def test_a_phrase_is_part_of_the_vocabulary_a_scenario_may_be_written_in(phrased):
    """It registers as a step, so anything that offers steps offers phrases without being told."""
    phrase = next(step for step in phrased.steps if step.pattern == "the account is on the standard plan")
    assert phrase.keyword == "*", "a phrase is said under whichever keyword its steps are"
    assert phrase.phrase
    assert phrase.expands_to == ['the account "primary" exists', 'the account "primary" field "plan" is "standard"']


def test_a_phrase_says_it_came_from_the_phrasebook_not_from_atfs_own_source(phrased):
    """Otherwise the interface would send someone to `atf/plugin.py` to change a line of YAML."""
    phrase = next(step for step in phrased.steps if step.pattern == "the account is on the standard plan")
    assert phrase.file.endswith(os.path.join("specs", "phrasebook.yaml"))


def test_a_phrase_needs_whatever_the_steps_it_stands_for_need(phrased):
    """It has no source of its own to read, so its needs are the union of what it says."""
    catalog_only = next(step for step in phrased.steps if step.pattern == "the account is on the standard plan")
    assert catalog_only.needs == [], "both claims resolve from the catalog, so nothing is needed"
    assert not catalog_only.needs_slot

    from_a_slot = next(step for step in phrased.steps if step.pattern == "the plan came back right")
    assert from_a_slot.needs_slot, "it stands for a claim about a slot, so it waits for one"


def test_a_phrase_describes_itself_by_what_it_stands_for(phrased):
    phrase = next(step for step in phrased.steps if step.pattern == "the plan came back right")
    assert phrase.docstring == 'Says in one line: the result field "plan" is "standard"'


# ---- rules -----------------------------------------------------------------


RULED = """Feature: Seeding
  Narrative here.

  Rule: What is declared is made to exist

    Scenario: A list is created under its owner
      Given the account "primary"

    Scenario: Seeding twice changes nothing
      Given the account "primary"

  Rule: An environment not opened for writing is refused

    @slow
    Scenario: Seeding a locked environment touches nothing
      Given the account "primary"
"""


def test_a_rule_groups_the_scenarios_under_it(tmp_path):
    """Gherkin's keyword for Example Mapping's middle card, and it costs the parser one branch."""
    path = tmp_path / "seeding.feature"
    path.write_text(RULED, encoding="utf-8")
    specs = parse_feature(path, {}, set())

    assert [spec.rule for spec in specs] == [
        "What is declared is made to exist",
        "What is declared is made to exist",
        "An environment not opened for writing is refused",
    ]


def test_a_rule_changes_nothing_else_about_a_scenario(tmp_path):
    path = tmp_path / "seeding.feature"
    path.write_text(RULED, encoding="utf-8")
    specs = parse_feature(path, {}, set())

    assert [spec.feature for spec in specs] == ["Seeding"] * 3
    assert specs[0].narrative == "Narrative here."
    assert specs[2].tags == ["slow"], "a tag above a scenario still belongs to that scenario"
    assert all(spec.steps for spec in specs)


def test_a_feature_with_no_rules_has_none(found):
    assert all(spec.rule == "" for spec in found.specs)
