"""What the pytest plugin wires up, where a scenario cannot watch it happen.

Most of what this module used to hold is now `tests/specs/features/` — provisioning a chain, an
ephemeral resource torn down after a run, a reference that must already be there, a misspelled type
in a spec, every row of an outline getting its own resources. Those are things a person can watch a
command do, and a scenario says them better.

Three kinds are left.

**The suite as a whole passes.** One assertion that the reference consuming project is green, which
is what every other test in `tests/` quietly assumes and none of them state.

**Fixtures are real fixtures.** A generated `account` fixture has to be visible to `--fixtures` and
carry its docstring, because that is how someone discovers what a suite gave them. Nothing a
scenario does observes a fixture *listing*.

**A system this machine cannot reach is skipped, with the reason.** The suite proves its own
`@browser` scenarios skip; these prove the mechanism underneath, including that the reason reaches
the report — which is the half that decides whether anyone ever removes the skip.
"""

from __future__ import annotations

from tests.sample_project import run_pytest, write_spec

TAGGED = """Feature: Needs a system
  @ephemeral
  Scenario: This one needs the ephemeral system
    Given the visitor "walkin"

  Scenario: This one does not
    Given the account "primary"
"""


def test_the_whole_sample_suite_passes(project):
    result = run_pytest(project, "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 passed, 1 skipped" in result.stdout


def test_generated_factories_are_real_discoverable_fixtures(project):
    result = run_pytest(project, "--fixtures", "-v")
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("account", "project", "visitor", "external_widget"):
        assert f"\n{name} --" in result.stdout or f"\n{name}\n" in result.stdout, name
    assert "Provision a `account` by catalog name" in result.stdout
    for name in ("context", "materializer", "client_config", "env"):
        assert name in result.stdout


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


def test_a_scenario_is_skipped_when_the_system_it_needs_is_unavailable(project, monkeypatch):
    monkeypatch.setenv("SAMPLE_EPHEMERAL_DOWN", "the farm is unreachable from here")
    write_spec(project, "needs_a_system", TAGGED)
    result = run_pytest(project, "-q", "-rs", "-p", "no:randomly", "specs/steps/test_needs_a_system.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout and "1 skipped" in result.stdout
    # The reason names the system and what is wrong with it: a skip nobody can act on is a skip
    # nobody ever removes.
    assert "needs ephemeral: the farm is unreachable from here" in result.stdout


def test_nothing_is_skipped_when_the_system_is_there(project, monkeypatch):
    monkeypatch.delenv("SAMPLE_EPHEMERAL_DOWN", raising=False)
    write_spec(project, "system_is_fine", TAGGED)
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_system_is_fine.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
