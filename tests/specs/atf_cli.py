"""The system under test: the `atf` command, run for real inside a provisioned workspace."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[2]
TIMEOUT = 300

# Which copy of ATF the suite-under-test runs. Overridable so the mutation tests can point at a
# throwaway copy instead of editing the working tree.
ATF_SRC = Path(os.environ.get("ATF_TESTS_SRC") or REPO / "src")


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
        root = Path(workspace["id"])
        return self._invoke(root, root, root / "atf.yaml", *args)

    def run_with(self, workspace: dict[str, Any], exported: dict[str, str], *args: str) -> Outcome:
        """The same, with something exported into the command's environment first.

        A few of ATF's promises are about what a person exported rather than what they typed —
        `ATF_ENV` choosing the environment over the manifest's default is the one that matters.
        There is no way to say that through arguments, so it is said here, and the variable's *name*
        stays out of the feature file by living in a phrase.
        """
        root = Path(workspace["id"])
        return self._invoke(root, root, root / "atf.yaml", *args, exported=exported)

    def run_and_find(self, workspace: dict[str, Any], *args: str) -> Outcome:
        """The same, from a directory inside the suite and with nothing pointing at the manifest.

        `ATF_MANIFEST` is how every other call keeps a scenario independent of where it ran from.
        Taking it away is the only way to exercise the promise that the command walks up and finds
        its own suite — and the only way to reach a manifest that is not called `atf.yaml`.
        """
        root = Path(workspace["id"])
        return self._invoke(root / "specs", root, None, *args)

    def run_nowhere(self, *args: str) -> Outcome:
        """Run in a fresh empty directory with no suite above it, the way a newcomer would."""
        empty = Path(tempfile.mkdtemp(prefix="atf-tests-nowhere-"))
        try:
            return self._invoke(empty, None, None, *args)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def _invoke(
        self,
        cwd: Path,
        suite: Path | None,
        manifest: Path | None,
        *args: str,
        exported: dict[str, str] | None = None,
    ) -> Outcome:
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(ATF_SRC), *([str(suite)] if suite else [])]),
            "ATF_TESTS_BACKEND": self.backend_url,
            "ATF_TESTS_ACTOR": self.actor,
            **(exported or {}),
        }
        if manifest is None:
            env.pop("ATF_MANIFEST", None)
        else:
            env["ATF_MANIFEST"] = str(manifest)

        completed = subprocess.run(
            [sys.executable, "-m", "atf.cli", *args],
            cwd=cwd,
            env=env,
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
