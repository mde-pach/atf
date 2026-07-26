"""Runs the self-hosted suite: ATF driving ATF (`selftest/`).

The unit tests below this one exercise the engine's parts in isolation; this one exercises the
whole framework through the surface a consumer actually touches — a real catalog, the pytest
plugin, and the `atf` CLI — with the specs written in Gherkin like any other suite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SELFTEST = REPO / "selftest"

SCENARIOS = 8


def run_selftest(*args: str, src: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=SELFTEST,
        env={
            **os.environ,
            "PYTHONPATH": str(src or REPO / "src"),
            # the suite shells out to `atf`; point that copy at the same source
            "ATF_SELFTEST_SRC": str(src or REPO / "src"),
        },
        capture_output=True,
        text=True,
        timeout=900,
    )


def test_atf_passes_its_own_specs():
    result = run_selftest()
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{SCENARIOS} passed" in result.stdout


def test_the_self_hosted_suite_uses_atf_rather_than_reimplementing_it():
    """Guard the dogfood: if this stops being an ATF suite, it stops proving anything."""
    assert (SELFTEST / "atf.yaml").is_file()
    assert (SELFTEST / "catalog" / "resources.yaml").is_file()
    assert 'pytest_plugins = ["atf.plugin"]' in (SELFTEST / "conftest.py").read_text()

    features = list((SELFTEST / "specs" / "features").glob("*.feature"))
    assert features
    for feature in features:
        assert "Scenario:" in feature.read_text()

    steps = (SELFTEST / "specs" / "steps" / "test_provisioning.py").read_text()
    assert "scenarios(" in steps
    # The provisioning step is ATF's, not something the suite defines for itself.
    assert "@given" not in steps


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
    ],
)
def test_the_self_hosted_suite_catches_regressions(module, find, replace, expected_failure, tmp_path):
    """A green suite proves nothing unless it can go red: break ATF, expect the right scenario to fail.

    The mutation is applied to a *copy* of the source — mutating the working tree would leave ATF
    broken if this process died, and would corrupt a concurrent test session.
    """
    src = tmp_path / "src"
    shutil.copytree(REPO / "src", src)

    path = src / "atf" / module
    original = path.read_text(encoding="utf-8")
    assert find in original, f"{module}: the mutation target moved — update this test"
    path.write_text(original.replace(find, replace), encoding="utf-8")

    result = run_selftest(src=src)
    assert result.returncode != 0, f"{module}: the suite stayed green with the code broken"
    assert expected_failure in result.stdout, result.stdout

    assert (REPO / "src" / "atf" / module).read_text(encoding="utf-8") == original, "the repo must be untouched"
