"""Runs the self-hosted suite: ATF driving ATF (`selftest/`).

The unit tests below this one exercise the engine's parts in isolation; this one exercises the
whole framework through the surface a consumer actually touches — a real catalog, the pytest
plugin, and the `atf` CLI — with the specs written in Gherkin like any other suite.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"

SCENARIOS = 61

# The scenarios that need the page to have *run*, not merely been served. They skip where there is
# no browser, which is the one thing about this suite that legitimately differs between machines.
BROWSER_SCENARIOS = 4

NOWHERE = "/nonexistent-so-no-browser-can-be-launched"


def run_selftest(
    *args: str, src: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=SELFTEST,
        env={
            **os.environ,
            "PYTHONPATH": str(src or REPO / "src"),
            # the suite shells out to `atf`; point that copy at the same source
            "ATF_SELFTEST_SRC": str(src or REPO / "src"),
            **(env or {}),
        },
        capture_output=True,
        text=True,
        timeout=900,
    )


def counts(output: str) -> tuple[int, int]:
    def number(word: str) -> int:
        found = re.search(rf"(\d+) {word}", output)
        return int(found.group(1)) if found else 0

    return number("passed"), number("skipped")


def test_atf_passes_its_own_specs():
    result = run_selftest()
    assert result.returncode == 0, result.stdout + result.stderr

    passed, skipped = counts(result.stdout)
    assert passed + skipped == SCENARIOS, result.stdout
    assert skipped in (0, BROWSER_SCENARIOS), "only the browser-tagged scenarios may skip"


def test_the_suite_is_still_a_meaningful_self_test_without_a_browser():
    """Most of this suite reads pages the server rendered, and that needs nothing installed.

    A checkout that never ran `uv sync --group browser` must still go green and still prove
    something — otherwise the browser layer has quietly become mandatory.
    """
    result = run_selftest(env={"PLAYWRIGHT_BROWSERS_PATH": NOWHERE})
    assert result.returncode == 0, result.stdout + result.stderr

    passed, skipped = counts(result.stdout)
    assert skipped == BROWSER_SCENARIOS
    assert passed == SCENARIOS - BROWSER_SCENARIOS


def test_the_self_hosted_suite_uses_atf_rather_than_reimplementing_it():
    """Guard the dogfood: if this stops being an ATF suite, it stops proving anything."""
    assert (SELFTEST / "atf.yaml").is_file()
    assert (SELFTEST / "catalog" / "resources.yaml").is_file()
    assert 'pytest_plugins = ["atf.plugin"]' in (SELFTEST / "conftest.py").read_text()

    features = list((SELFTEST / "specs" / "features").glob("*.feature"))
    assert features
    for feature in features:
        assert "Scenario:" in feature.read_text()

    # Provisioning and every assertion are ATF's own steps, not something the suite writes for
    # itself. All it defines is running a command, which is the one thing a framework cannot do
    # generically — so a `@given` or a `@then` anywhere under `specs/` means the dogfood has been
    # quietly spat out.
    # A decorator at the start of a line, not the word anywhere: these files explain themselves,
    # and a docstring saying "there is no `@then` here" would otherwise be the thing that fails.
    hand_written = re.compile(r"^@(given|then)\b", re.MULTILINE)
    for module in (SELFTEST / "specs").rglob("*.py"):
        found = hand_written.search(module.read_text(encoding="utf-8"))
        assert found is None, f"{module.name} writes its own {found.group(0)}; ATF's own steps do that"


@pytest.mark.parametrize(
    ("module", "find", "replace", "expected_failure"),
    [
        pytest.param(
            "materializer.py",
            "        for nid in self.topo(wanted):",
            "        for nid in wanted:",
            "dependency_chain_in_order",
            id="dependency ordering",
        ),
        pytest.param(
            "cli.py",
            "    if not boot.manifest.is_mutable(boot.env):",
            "    if False:",
            "outside_mutable_envs_is_refused",
            id="mutable_envs gate",
        ),
        pytest.param(
            "plugin.py",
            "    materializer.teardown(getattr(context, EPHEMERAL_ATTR, []))",
            "    pass",
            "torn_down_afterwards",
            id="ephemeral teardown",
        ),
        pytest.param(
            "cockpit/routers/catalog.py",
            "GRAPH_FROM = 1",
            "GRAPH_FROM = 9",
            "a_resource_that_depends_on_something_is_drawn_as_well_as_described",
            id="the interface, through the interface",
        ),
    ],
)
def test_the_self_hosted_suite_catches_regressions(module, find, replace, expected_failure, tmp_path):
    """A green suite proves nothing unless it can go red: break ATF, expect the right scenario to fail.

    The mutation is applied to a *copy* of the source — mutating the working tree would leave ATF
    broken if this process died, and would corrupt a concurrent test session.
    """
    src = tmp_path / "src"
    shutil.copytree(REPO / "src", src)

    path = src / "atf" / Path(module)
    original = path.read_text(encoding="utf-8")
    assert find in original, f"{module}: the mutation target moved — update this test"
    path.write_text(original.replace(find, replace), encoding="utf-8")

    result = run_selftest(src=src)
    assert result.returncode != 0, f"{module}: the suite stayed green with the code broken"
    assert expected_failure in result.stdout, result.stdout

    assert (REPO / "src" / "atf" / Path(module)).read_text(encoding="utf-8") == original, "the repo must be untouched"
