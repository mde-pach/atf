"""The suite ATF ships as its example, driven through the `atf` command.

Not a test of the CLI — `selftest` covers what `seed`, `status` and `run` do, against suites written
to exercise them. What these cover is that the example *we ship* is wired the way its README claims:
a find-only `reference` adapter, a project's own ephemeral adapter, a type whose identity is not
called `id`, and an environment deliberately left out of `mutable_envs`.

It is a claim about the repository rather than about the framework, which is why it sits beside the
other repository-level guards rather than in `selftest`. `examples/todo` has its own gate that runs
the suite directly; this is the half that goes through the command.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "todo"


def example_env(url: str) -> dict[str, str]:
    return {
        **os.environ,
        "TODO_URL": url,
        "TODO_ACTOR": "example",
        "ATF_MANIFEST": str(EXAMPLE / "atf.yaml"),
        "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(EXAMPLE)]),
    }


@pytest.fixture
def example_api():
    sys.path.insert(0, str(EXAMPLE))
    from fake_api import TodoAPI

    api = TodoAPI(actor="example")
    url = api.start()
    yield url
    api.stop()
    sys.path.remove(str(EXAMPLE))


def cli(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "atf.cli", *args],
        cwd=EXAMPLE,
        env=example_env(url),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_the_example_seeds_and_runs_green(example_api):
    seeded = cli(example_api, "seed", "dev")
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    assert "6 created, 1 found" in seeded.stdout  # the ephemeral guest is not seeded

    run = cli(example_api, "run")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "9 passed, 0 failed" in run.stdout


def test_the_example_runs_green_without_seeding_first(example_api):
    """Specs provision what they need — a fresh environment needs no seed step."""
    run = cli(example_api, "run")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "9 passed, 0 failed" in run.stdout


def test_the_example_is_idempotent(example_api):
    assert cli(example_api, "run").returncode == 0
    second = cli(example_api, "run")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "9 passed, 0 failed" in second.stdout


def test_the_example_exercises_rest_reference_and_a_custom_ephemeral_adapter(example_api):
    cli(example_api, "seed", "dev")
    status = cli(example_api, "status", "dev")
    assert status.returncode == 0

    assert "labels.urgent" in status.stdout and "present" in status.stdout   # reference (find-only)
    assert "guests.visitor" in status.stdout and "ephemeral" in status.stdout  # custom adapter
    assert "tasks.milk" in status.stdout                                      # rest, non-default id_field

    import httpx

    headers = {"X-Actor": "example"}
    # the ephemeral guest each run creates is torn down again
    cli(example_api, "run")
    guests = httpx.get(f"{example_api}/guests", headers=headers).json()
    assert guests["results"] == []


def test_the_example_refuses_to_seed_its_read_only_env(example_api):
    result = cli(example_api, "seed", "staging")
    assert result.returncode == 2
    assert "not in `mutable_envs`" in result.stderr
