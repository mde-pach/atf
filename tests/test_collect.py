"""A `.feature` nobody bound is collected by ATF itself.

The module a suite used to write per feature is an import and a call — and, for a feature written
entirely in the vocabulary ATF already provides, nothing else. What is tested here is that such a
feature runs, that one with a module is *not* collected twice, and that the boundary of what an
auto-collected feature can reach is the one the docstring claims.
"""

from __future__ import annotations

from pathlib import Path

from atf.collect import binds
from tests.sample_project import run_pytest, write_spec


def feature(project: Path, name: str, text: str) -> Path:
    path = project / "specs" / "features" / f"{name}.feature"
    path.write_text(text, encoding="utf-8")
    return path


GENERIC = """Feature: No code at all
  Scenario: A provisioned account is there
    Given the account "primary"
    Then the account "primary" exists

  Scenario: And so is its plan
    Given the account "primary"
    Then the account "primary" field "plan" is "standard"
"""


def test_a_feature_with_no_module_beside_it_still_runs(project):
    feature(project, "unbound", GENERIC)
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/features/unbound.feature")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout


def test_its_scenarios_are_named_the_way_a_bound_feature_s_are(project):
    """The nodeid is what a run report, the cockpit and `-k` all key on."""
    feature(project, "unbound", GENERIC)
    result = run_pytest(project, "-v", "-p", "no:randomly", "specs/features/unbound.feature")
    assert "test_a_provisioned_account_is_there" in result.stdout
    assert "test_and_so_is_its_plan" in result.stdout


def test_a_feature_a_module_binds_is_not_collected_twice(project):
    """Both would run every scenario, and the module is the one that can see its steps."""
    write_spec(project, "bound", GENERIC)
    result = run_pytest(project, "-q", "-p", "no:randomly")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("passed") == 1
    # Two scenarios in this feature, run once each, not twice.
    assert "No code at all" not in result.stdout


def test_a_phrase_is_reachable_from_an_auto_collected_feature(project):
    """A phrase is registered by the plugin, so it is visible everywhere — module or not."""
    (project / "specs" / "phrasebook.yaml").write_text(
        "'the account is on the standard plan':\n  - the account \"primary\" field \"plan\" is \"standard\"\n",
        encoding="utf-8",
    )
    feature(
        project,
        "phrased",
        """Feature: Phrased and unbound
  Scenario: A phrase needs no module either
    Given the account "primary"
    Then the account is on the standard plan
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/features/phrased.feature")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_step_only_a_module_declares_is_not_reachable(project):
    """The boundary, said out loud: a step in a module is visible only inside that module."""
    feature(
        project,
        "needs_a_step",
        """Feature: Unbound but needy
  Scenario: It wants a When of its own
    Given the account "primary"
    When I read its plan
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/features/needs_a_step.feature")
    assert result.returncode != 0
    assert "Step definition is not found" in result.stdout


def test_binds_sees_a_module_that_hands_the_feature_over(project):
    write_spec(project, "bound", GENERIC)
    specs = project / "specs"
    assert binds(specs, specs / "features" / "bound.feature")
    assert not binds(specs, specs / "features" / "never_written.feature")
