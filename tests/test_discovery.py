from __future__ import annotations

import os

import pytest

from atf.catalog import load_catalog
from atf.discovery import discover, parse_feature, slug
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
