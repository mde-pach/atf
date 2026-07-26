"""The system under test: the `atf` command, run for real inside a provisioned workspace."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
TIMEOUT = 300

# Which copy of ATF the suite-under-test runs. Overridable so the mutation tests can point at a
# throwaway copy instead of editing the working tree.
ATF_SRC = Path(os.environ.get("ATF_SELFTEST_SRC") or REPO / "src")


@dataclass
class Outcome:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


class AtfUnderTest:
    def __init__(self, backend_url: str, actor: str) -> None:
        self.backend_url = backend_url
        self.actor = actor
        self.http = httpx.Client(base_url=backend_url, headers={"X-Actor": actor}, timeout=10)

    def run(self, workspace: dict[str, Any], *args: str) -> Outcome:
        """Run `atf …` inside the workspace, exactly as a consumer would."""
        completed = subprocess.run(
            [sys.executable, "-m", "atf.cli", *args],
            cwd=workspace["id"],
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join([str(ATF_SRC), workspace["id"]]),
                "ATF_MANIFEST": str(Path(workspace["id"]) / "atf.yaml"),
                "SELFTEST_BACKEND": self.backend_url,
                "SELFTEST_ACTOR": self.actor,
            },
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return Outcome(completed.returncode, completed.stdout, completed.stderr)

    def records(self, collection: str) -> list[dict[str, Any]]:
        response = self.http.get(f"/{collection}")
        response.raise_for_status()
        return response.json()["results"]

    def reset(self) -> None:
        httpx.post(f"{self.backend_url}/_reset", timeout=10).raise_for_status()


@pytest.fixture
def atf(client_config):
    return AtfUnderTest(**client_config["atf"])


@pytest.fixture(autouse=True)
def _clean_backend(atf):
    """Each scenario starts against an empty environment."""
    atf.reset()
