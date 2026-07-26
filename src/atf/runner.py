"""Synchronous test runs → structured results (§12). Serialized by a lock, timeout-guarded."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT = 1800
_LOCK = threading.Lock()

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
ERROR = "error"


@dataclass
class TestResult:
    nodeid: str
    outcome: str
    duration: float = 0.0
    detail: str = ""
    finished_at: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class RunSummary:
    results: dict[str, TestResult] = field(default_factory=dict)
    returncode: int = 0
    output: str = ""
    duration: float = 0.0

    @property
    def counts(self) -> dict[str, int]:
        totals = {PASSED: 0, FAILED: 0, SKIPPED: 0, ERROR: 0}
        for result in self.results.values():
            totals[result.outcome] = totals.get(result.outcome, 0) + 1
        return totals


def run(
    nodeids: Iterable[str] | None,
    env: str,
    root: Path,
    specs_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> RunSummary:
    """Run pytest in a subprocess with `ATF_ENV` set and parse its JSON report."""
    targets = list(nodeids or [])
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "--json-report",
            f"--json-report-file={report}",
            "-q",
            *(targets or ([str(specs_dir)] if specs_dir else [])),
        ]
        completed = _launch(command, root, env, timeout)
        if completed is None:
            return RunSummary(returncode=-1, output=f"run timed out after {timeout}s")
        summary = _parse(report)
        summary.returncode = completed.returncode
        summary.output = _tail(completed.stdout + completed.stderr)
        return summary


def pytest_command(nodeids: Sequence[str], specs_dir: Path | None) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", *(list(nodeids) or ([str(specs_dir)] if specs_dir else []))]


def child_env(root: Path, env: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["ATF_ENV"] = env
    manifest = root / "atf.yaml"
    if manifest.is_file():
        environment["ATF_MANIFEST"] = str(manifest)
    return environment


def _launch(command: list[str], root: Path, env: str, timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=root,
            env=child_env(root, env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None


def _parse(report: Path) -> RunSummary:
    summary = RunSummary()
    if not report.exists():
        return summary
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except ValueError:
        return summary

    summary.duration = float(payload.get("duration", 0.0))
    for entry in payload.get("tests", []):
        nodeid = str(entry.get("nodeid", ""))
        if not nodeid:
            continue
        outcome = str(entry.get("outcome", ERROR))
        duration = sum(
            float(entry.get(phase, {}).get("duration", 0.0)) for phase in ("setup", "call", "teardown")
        )
        summary.results[nodeid] = TestResult(
            nodeid=nodeid,
            outcome=outcome,
            duration=duration,
            detail=_detail(entry),
        )
    return summary


def _detail(entry: dict[str, object]) -> str:
    for phase in ("call", "setup", "teardown"):
        stage = entry.get(phase)
        if not isinstance(stage, dict):
            continue
        crash = stage.get("crash")
        message = stage.get("longrepr") or (crash.get("message") if isinstance(crash, dict) else None)
        if message:
            return _tail(str(message), 600)
    return ""


def _tail(text: str, limit: int = 2000) -> str:
    stripped = text.strip()
    return stripped[-limit:] if len(stripped) > limit else stripped
