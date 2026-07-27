from __future__ import annotations

import json

from tests.sample_project import run_pytest


def test_the_whole_sample_suite_passes(project):
    result = run_pytest(project, "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 passed, 1 skipped" in result.stdout


def test_a_pure_config_spec_passes(project):
    result = run_pytest(project, "-q", "-k", "standard_account_reports_its_plan")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_provisioning_a_dependency_chain(project):
    result = run_pytest(project, "-q", "-k", "project_belongs_to_its_account")
    assert result.returncode == 0, result.stdout + result.stderr

    store = json.loads((project / "store.json").read_text())
    assert [record["email"] for record in store["accounts"]] == ["primary@example.test"]
    assert store["projects"][0]["account_id"] == store["accounts"][0]["id"]


def test_scenario_outline_rows_each_provision_their_own_resource(project):
    result = run_pytest(project, "-q", "-k", "Accounts_report_their_own_plan")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout

    store = json.loads((project / "store.json").read_text())
    assert {record["email"] for record in store["accounts"]} == {
        "primary@example.test",
        "secondary@example.test",
    }


def test_generated_factories_are_real_discoverable_fixtures(project):
    result = run_pytest(project, "--fixtures", "-v")
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("account", "project", "visitor", "external_widget"):
        assert f"\n{name} --" in result.stdout or f"\n{name}\n" in result.stdout, name
    assert "Provision a `account` by catalog name" in result.stdout
    for name in ("context", "materializer", "client_config", "env"):
        assert name in result.stdout


def test_ephemeral_resource_is_built_then_torn_down(project):
    result = run_pytest(project, "-q", "-k", "visitor_is_ready_once_provisioned")
    assert result.returncode == 0, result.stdout + result.stderr

    store = json.loads((project / "store.json").read_text())
    assert store.get("visitors") == []  # created during the run, deleted by teardown


def test_reference_resource_is_found_not_created(project):
    result = run_pytest(project, "-q", "-k", "referenced_widget_is_available")
    assert result.returncode == 0, result.stdout + result.stderr

    store = json.loads((project / "store.json").read_text())
    assert [widget["id"] for widget in store["widgets"]] == ["widget-seed"]


def test_missing_reference_fails_the_test_with_the_offending_node(project):
    (project / "conftest.py").write_text('pytest_plugins = ["atf.plugin"]\n', encoding="utf-8")
    result = run_pytest(project, "-q", "-k", "referenced_widget_is_available")
    assert result.returncode != 0
    assert "widgets.imported" in result.stdout


def test_unknown_resource_type_in_a_scenario_fails_clearly(project):
    feature = project / "specs" / "features" / "extra.feature"
    feature.write_text(
        "Feature: Typos\n  Scenario: A typo\n    Given the acount \"primary\"\n    Then the plan is \"standard\"\n",
        encoding="utf-8",
    )
    (project / "specs" / "steps" / "test_extra.py").write_text(
        'from pytest_bdd import scenarios\n\nscenarios("../features/extra.feature")\n', encoding="utf-8"
    )
    result = run_pytest(project, "-q", "-k", "A_typo")
    assert result.returncode != 0
    assert "no resource type 'acount'" in result.stdout


def test_reserved_name_collision_fails_at_load(project):
    types = project / "catalog" / "resources.yaml"
    types.write_text(types.read_text() + "\ncontext:\n  system: store\n  natural_key: name\n", encoding="utf-8")
    result = run_pytest(project, "-q", "--collect-only")
    assert result.returncode != 0
    assert "reserved fixture name" in result.stdout + result.stderr


def test_client_config_comes_from_the_manifest(project):
    check = project / "specs" / "steps" / "test_wiring.py"
    check.write_text(
        "def test_client_config(client_config, env, materializer):\n"
        "    assert env == 'dev'\n"
        "    assert 'api' in client_config\n"
        "    assert materializer.env == 'dev'\n",
        encoding="utf-8",
    )
    result = run_pytest(project, "-q", "-k", "test_client_config")
    assert result.returncode == 0, result.stdout + result.stderr


def test_env_selects_the_environment(project):
    check = project / "specs" / "steps" / "test_wiring.py"
    check.write_text("def test_env(env):\n    assert env == 'locked'\n", encoding="utf-8")
    result = run_pytest(project, "-q", "-k", "test_env", env="locked")
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_ephemeral_dependency_is_torn_down_too(project):
    """`badges.welcome` is persistent but depends on the ephemeral `visitors.walkin`.

    Only the badge is named in the scenario, so a teardown that tracks just the named node
    leaves a visitor behind on every single run.
    """
    result = run_pytest(project, "-q", "-k", "badge_is_issued_to_a_visitor")
    assert result.returncode == 0, result.stdout + result.stderr

    store = json.loads((project / "store.json").read_text())
    assert store["badges"], "the badge itself is persistent and stays"
    assert store["visitors"] == [], "the ephemeral dependency must not leak"
