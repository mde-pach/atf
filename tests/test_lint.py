"""`atf lint`: a spec line may not say something only the layer below should have to know.

The rule is the one thing holding the four layers apart, and it is the only one that can be checked
by machine — so what is tested here is that each kind of leak is caught, that prose is not mistaken
for a claim, and that a suite mid-migration can waive a rule by name instead of turning the check
off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atf.cli import main
from atf.lint import RULES, check, check_text, report, rule


def findings(text: str) -> list[str]:
    return [found.rule for found in check_text(text, Path("f.feature"))]


def feature(*steps: str) -> str:
    return "Feature: F\n  Scenario: S\n" + "".join(f"    {line}\n" for line in steps)


# ---- what each rule catches -------------------------------------------------


def test_a_field_name_in_a_claim_is_caught():
    assert findings(feature('Then the task "milk" field "done" is "false"')) == ["field-claim"]


def test_a_status_code_is_caught():
    assert findings(feature('Then the page "overview" is "200"')) == ["status-code"]
    assert findings(feature('Then the count is "42"')) == [], "not every number is a status code"
    assert findings(feature('Then the count is "1000"')) == []


def test_a_path_or_a_url_is_caught():
    assert findings(feature('When I call "/tasks"')) == ["path"]
    assert findings(feature('When I call "https://example.test/tasks"')) == ["path"]
    assert findings(feature('Then the note is "a / b"')) == [], "a slash in prose is not a route"


def test_a_command_line_flag_is_caught():
    assert findings(feature('When I run "atf run --json"')) == ["cli-flag"]
    assert findings(feature('When I run "atf seed local"')) == []


def test_a_selector_is_caught():
    assert findings(feature('Then the element "#compose-form li[role=option]" exists')) == ["selector"]
    assert findings(feature('Then the element ".builder-step" exists')) == ["selector"]
    assert findings(feature('Then the element "a > b" exists') ) == ["selector"]


def test_one_line_can_break_more_than_one_rule():
    assert set(findings(feature('Then the page "overview" field "status" is "200"'))) == {
        "field-claim",
        "status-code",
    }


def test_every_rule_says_what_to_write_instead():
    """A check that only says no teaches nothing, and gets argued with rather than followed."""
    for entry in RULES:
        assert entry.forbids and entry.instead
        assert rule(entry.name) is entry


# ---- what it does not catch --------------------------------------------------


def test_prose_is_not_a_claim():
    """The narrative is where an author explains, and explaining is allowed to be specific."""
    text = """Feature: Seeding
  Seeding POSTs to /tasks and expects a 201, and `--keep-going` carries on past a failure.

  Scenario: A list is created
    Then the owner "primary" exists
"""
    assert findings(text) == []


def test_a_comment_between_steps_is_not_a_claim():
    text = """Feature: F
  Scenario: S
    # this one checks the "status" field of /overview with --json
    Then the owner "primary" exists
"""
    assert findings(text) == []


def test_the_claims_that_already_read_as_domain_language_pass():
    assert findings(
        feature(
            'Given the workspace "chained"',
            'Then the owner "primary" exists',
            'And the todo_list "groceries" is gone',
            "And the environment has 1 owner",
            'And it is refused because "not in mutable_envs"',
        )
    ) == []


# ---- waivers -----------------------------------------------------------------


def test_a_waiver_above_a_line_waives_that_line():
    text = """Feature: F
  Scenario: S
    # atf-lint: ignore field-claim
    Then the task "milk" field "done" is "false"
"""
    assert findings(text) == []


def test_a_waiver_does_not_carry_on_to_the_next_line():
    """It sits directly above what it waives, or it is waiving something a reader cannot see."""
    text = """Feature: F
  Scenario: S
    # atf-lint: ignore field-claim
    Then the task "milk" field "done" is "false"
    And the task "bread" field "done" is "true"
"""
    assert findings(text) == ["field-claim"]


def test_a_waiver_before_the_feature_waives_the_whole_file():
    text = """# atf-lint: ignore field-claim
# because this feature is a waypoint and here is why
Feature: F
  Scenario: S
    Then the task "milk" field "done" is "false"
    And the task "bread" field "done" is "true"
"""
    assert findings(text) == []


def test_a_waiver_names_the_rules_it_waives_and_no_others():
    text = """# atf-lint: ignore field-claim
Feature: F
  Scenario: S
    Then the page "overview" field "status" is "200"
"""
    assert findings(text) == ["status-code"]


def test_several_rules_can_be_waived_at_once():
    text = """# atf-lint: ignore field-claim, status-code
Feature: F
  Scenario: S
    Then the page "overview" field "status" is "200"
"""
    assert findings(text) == []


def test_a_waiver_naming_nothing_known_waives_everything_rather_than_silently_nothing():
    """Better to be obviously too broad than to look like a waiver and do nothing at all."""
    text = """# atf-lint: ignore whatever-that-is
Feature: F
  Scenario: S
    Then the task "milk" field "done" is "false"
"""
    assert findings(text) == []


# ---- over a suite ------------------------------------------------------------


def test_checking_a_directory_reads_every_feature_in_a_stable_order(tmp_path):
    (tmp_path / "b.feature").write_text(feature('Then the a "x" field "f" is "1"'), encoding="utf-8")
    (tmp_path / "a.feature").write_text(feature('When I call "/tasks"'), encoding="utf-8")
    found = check(tmp_path)
    assert [item.path.name for item in found] == ["a.feature", "b.feature"]
    assert [item.rule for item in found] == ["path", "field-claim"]


def test_a_clean_suite_says_so_rather_than_saying_nothing(tmp_path):
    (tmp_path / "a.feature").write_text(feature('Then the owner "primary" exists'), encoding="utf-8")
    assert "No technical vocabulary" in report(check(tmp_path), tmp_path)


def test_the_report_says_how_to_answer_a_finding(tmp_path):
    (tmp_path / "a.feature").write_text(feature('Then the a "x" field "f" is "1"'), encoding="utf-8")
    text = report(check(tmp_path), tmp_path)
    assert "Write a phrase for it" in text
    assert "atf-lint: ignore <rule>" in text


# ---- the command --------------------------------------------------------------


@pytest.fixture
def suite(tmp_path, monkeypatch):
    root = tmp_path / "suite"
    (root / "catalog").mkdir(parents=True)
    (root / "specs" / "features").mkdir(parents=True)
    (root / "catalog" / "resources.yaml").write_text("owner:\n  system: rest\n  natural_key: email\n")
    (root / "atf.yaml").write_text(
        "catalog: ./catalog\nspecs: ./specs\ndefault_env: dev\n"
        "environments:\n  dev:\n    adapters:\n      rest:\n        base_url: http://x\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    return root


def test_the_command_passes_a_clean_suite(suite, capsys):
    (suite / "specs" / "features" / "a.feature").write_text(
        feature('Then the owner "primary" exists'), encoding="utf-8"
    )
    assert main(["lint"]) == 0
    assert "No technical vocabulary" in capsys.readouterr().out


def test_the_command_fails_and_reports_on_stderr_so_ci_can_gate_on_it(suite, capsys):
    (suite / "specs" / "features" / "a.feature").write_text(
        feature('Then the owner "primary" field "email" is "x"'), encoding="utf-8"
    )
    assert main(["lint"]) == 1
    captured = capsys.readouterr()
    assert "field-claim" in captured.err
    assert captured.out == ""


def test_the_command_needs_no_environment_at_all(suite, capsys):
    """It checks what a reader reads, so it has to run in a checkout with no backend near it."""
    (suite / "specs" / "features" / "a.feature").write_text(
        feature('When I call "https://nothing.test/x"'), encoding="utf-8"
    )
    assert main(["lint"]) == 1
    assert "path" in capsys.readouterr().err
