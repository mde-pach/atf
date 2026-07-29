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


def test_the_adapters_are_closed_when_the_run_ends(project):
    """`Closeable` is part of the SPI and nothing called it until now.

    A REST adapter holds an HTTP client and a browser adapter holds a browser and the process
    driving it. An adapter of a project's own may hold a socket, a tunnel or a container, and the
    only honest moment to tell it the run is over is the end of the run. No scenario can watch this
    — it happens after the last one — so it is here.

    The adapter is added to the project's own adapters module rather than to a steps file, because
    the plugin builds every adapter the environment names when it imports, which is before a steps
    module has been read.
    """
    adapters = project / "suite_adapters.py"
    adapters.write_text(
        adapters.read_text()
        + '''

class Holding:
    """Registered for one run, so that the session finishing can be observed at all."""

    def __init__(self, settings):
        self.root = Path(__file__).parent

    def find(self, node, ctx):
        return None

    def create(self, node, body, ctx):
        return {}

    def delete(self, node, record, ctx):
        return None

    def close(self):
        (self.root / "closed.txt").write_text("yes", encoding="utf-8")


register("holding", Holding)
''',
        encoding="utf-8",
    )
    manifest = project / "atf.yaml"
    manifest.write_text(
        manifest.read_text().replace("    adapters:", "    adapters:\n      holding: {}", 1), encoding="utf-8"
    )
    write_spec(
        project,
        "closing",
        '''Feature: Closing
  Scenario: Something ran at all
    Given the account "primary"
''',
    )

    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_closing.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (project / "closed.txt").is_file(), "the run ended without closing the adapters"
