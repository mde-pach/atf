"""What the MCP layer answers when it is asked for something it must not do.

The layer itself is thin on purpose — `describe` and `compose` are the
[introspection API](../src/atf/introspect.py) with a cockpit bound to them, and that is covered by
`test_introspect.py`. What is only here is `run`, which is the one verb that touches an environment,
and its refusals: an environment nobody declared, an environment nobody allowed to be changed, a
scenario that does not exist, and one written but never collected.

None of these runs pytest, and that is the point of each of them: a refusal has to happen *before*
anything is provisioned, or it is not a refusal.

Not scenarios, for the same reason `test_introspect.py` is not: there is no interface to watch. The
one thing a person can watch — `atf serve --mcp` saying what to install — is a scenario, in
`specs/features/cli.feature`.
"""

from __future__ import annotations

import pytest

from atf.cockpit.deps import set_session
from atf.engine.session import Session
from atf.mcp import Tools, unavailable
from tests.sample_project import write_sample_project


@pytest.fixture
def tools(tmp_path, monkeypatch) -> Tools:
    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    monkeypatch.setenv("ATF_ENV", "dev")
    monkeypatch.chdir(root)
    monkeypatch.delitem(__import__("sys").modules, "suite_adapters", raising=False)
    yield Tools(Session("dev"))
    set_session(None)


def test_an_environment_nobody_declared_is_refused_rather_than_quietly_replaced(tools):
    """Answering about dev when somebody asked about staging is how an agent acts on the wrong place."""
    with pytest.raises(ValueError, match="unknown environment 'staging'"):
        tools.describe(environment="staging")


def test_running_against_an_environment_nobody_allowed_to_change_is_refused(tools):
    """Running provisions, so `run` is held to `mutable_envs` exactly as the composer's Try it is."""
    answered = tools.run(scenario="anything", environment="locked")
    assert answered["ran"] is False
    assert "mutable_envs" in answered["problems"][0]


def test_running_a_scenario_this_suite_has_not_got_names_the_ones_it_has(tools):
    answered = tools.run(scenario="no::such-thing")
    assert answered["ran"] is False
    assert "no scenario 'no::such-thing' here" in answered["problems"][0]


def test_running_a_draft_that_is_not_a_scenario_yet_reports_why_instead_of_running_it(tools):
    """The refusal arrives before anything is provisioned, which is what makes it a refusal."""
    answered = tools.run(title="", rows=[{"keyword": "when", "pattern": "I invent a step"}])
    assert answered["ran"] is False
    assert not answered["ready"]
    assert any("worded 'I invent a step'" in problem for problem in answered["problems"])


def test_the_sdk_being_absent_is_an_answer_with_what_to_install_in_it():
    """The same shape as the browser adapter reporting itself unavailable: a reason, not a crash.

    Which branch runs depends on whether the optional group is installed, and both are real: this
    repository's own checks do not install it, so the reason is what CI sees.
    """
    reason = unavailable()
    assert reason == "" or "uv sync --group mcp" in reason


@pytest.mark.skipif(unavailable() != "", reason=unavailable() or "")
def test_with_the_sdk_installed_the_server_offers_exactly_the_three_verbs(tools):
    """Three tools, and they do not grow when the vocabulary does — that is the whole design."""
    import asyncio

    from atf.mcp import server

    built = server(tools.session)
    assert built.name == "atf"
    assert {tool.name for tool in asyncio.run(built.list_tools())} == {"describe", "compose", "run"}
