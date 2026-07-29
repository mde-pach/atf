"""A green suite proves nothing unless it can go red.

`tests/` is an ATF suite describing ATF. That is worth exactly as much as its ability to fail, so
this breaks the framework in four places — dependency ordering, the `mutable_envs` gate, ephemeral
teardown, the cockpit's lineage threshold — and requires the matching scenario to notice.

The mutation is applied to a *copy* of `src/`. Mutating the working tree would leave ATF broken if
this process died, and would corrupt a concurrent session.

Only `specs/` is run in the subprocess, never the whole of `tests/`: this module lives in `tests/`
too, and running everything would run this.
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
SUITE = REPO / "tests"

SCENARIOS = 167

# The scenarios that need the page to have *run*, not merely been served. They skip where there is
# no browser, which is the one thing about this suite that legitimately differs between machines.
BROWSER_SCENARIOS = 6

NOWHERE = "/nonexistent-so-no-browser-can-be-launched"


def run_suite(
    *args: str, src: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "specs", *args],
        cwd=SUITE,
        env={
            **os.environ,
            # The copy of ATF everything under this run uses: the suite itself, the `atf` it shells
            # out to, and the cockpits it serves. One variable, inherited all the way down.
            "PYTHONPATH": str(src or REPO / "src"),
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


def test_the_suite_is_still_a_meaningful_self_test_without_a_browser():
    """Most of this suite reads pages the server rendered, and that needs nothing installed.

    A checkout that never ran `uv sync --group browser` must still go green and still prove
    something — otherwise the browser layer has quietly become mandatory.

    This is also the one place that runs the whole of `specs/` in a clean process, and it is enough:
    the ordinary `pytest` invocation over this repository already runs every scenario, browser ones
    included, in the environment somebody actually has. A second full run asserting the same thing
    cost two minutes to tell us nothing new.
    """
    result = run_suite(env={"PLAYWRIGHT_BROWSERS_PATH": NOWHERE})
    assert result.returncode == 0, result.stdout + result.stderr

    passed, skipped = counts(result.stdout)
    assert skipped == BROWSER_SCENARIOS
    assert passed == SCENARIOS - BROWSER_SCENARIOS


def test_the_self_hosted_suite_uses_atf_rather_than_reimplementing_it():
    """Guard the dogfood: if this stops being an ATF suite, it stops proving anything.

    The manifest is asserted to be at the *repository root*, not in `tests/`. That is the difference
    between a suite ATF can be pointed at and a suite only pytest can run: a project's config lives
    where the project does, and ATF finds it by walking up. Move it back under `tests/` and every
    `atf` command needs a variable exported first, which is how this stopped demonstrating anything
    the first time.
    """
    assert (REPO / "atf.yaml").is_file(), "the manifest belongs at the root, as in any project"
    assert not (SUITE / "atf.yaml").exists(), "two manifests is two sources of truth"
    assert (SUITE / "catalog" / "resources.yaml").is_file()
    assert '"atf.plugin"' in (SUITE / "conftest.py").read_text()

    features = list((SUITE / "specs" / "features").glob("*.feature"))
    assert features
    for feature in features:
        assert "Scenario:" in feature.read_text()

    # Provisioning and every assertion are ATF's own steps, and so is running a command now. All
    # this suite defines is *where* the command was standing and what the developer had exported,
    # which is the one thing a suite testing a test framework knows that ATF cannot — so a `@given`
    # or a `@then` anywhere under `specs/` means the dogfood has been quietly spat out.
    # A decorator at the start of a line, not the word anywhere: these files explain themselves,
    # and a docstring saying "there is no `@then` here" would otherwise be the thing that fails.
    hand_written = re.compile(r"^@(given|then)\b", re.MULTILINE)
    for module in (SUITE / "specs").rglob("*.py"):
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

    # Only the scenario that has to notice. What this asserts is that *this* break turns *that*
    # scenario red, and running the other hundred and sixty to learn it cost two minutes each. The
    # whole suite still runs, once, unmutated, in the test above.
    result = run_suite("-k", expected_failure, src=src)
    assert result.returncode != 0, f"{module}: the suite stayed green with the code broken"
    assert expected_failure in result.stdout, result.stdout
    # A `-k` that matched nothing also exits non-zero, which would make this pass for the worst
    # possible reason: a mutation nobody checked, reported as caught. pytest says so in one phrase.
    assert "no tests ran" not in result.stdout, (
        f"{module}: `-k {expected_failure}` selected no scenario, so nothing was actually checked"
    )

    assert (REPO / "src" / "atf" / Path(module)).read_text(encoding="utf-8") == original, "the repo must be untouched"
