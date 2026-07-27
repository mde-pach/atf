"""Run history on disk, so "can I ship?" survives a restart of the cockpit.

One JSON file per run under `<manifest root>/.atf/runs`, named `<millis>-<env>-<id>.json` so a
directory listing is already in newest-last order. Reading is total: a file this version cannot
parse is skipped rather than raised, because a corrupt history must never take a page down, and
unknown keys are ignored so a newer ATF's runs stay readable by an older one.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .runner import (
    ERROR,
    FAILED,
    PASSED,
    SKIPPED,
    Held,
    RunRecord,
    StepResult,
    TestResult,
    held_from,
    parse_report,
    step_from,
)

DEFAULT_KEEP = 50
STORE_DIR = ".atf"
RUNS_DIR = "runs"

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class ReportError(Exception):
    """A pytest JSON report that cannot be ingested."""


class RunStore:
    """The run history of one suite, partitioned by environment and capped at `keep` runs each."""

    def __init__(self, root: Path, keep: int = DEFAULT_KEEP) -> None:
        self.root = Path(root)
        self.keep = keep

    @property
    def dir(self) -> Path:
        return self.root / STORE_DIR / RUNS_DIR

    def save(self, record: RunRecord) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / _filename(record)
        # Written aside and moved into place: a reader tailing the directory must never see half
        # a run, and on every platform we support the replace is atomic.
        staging = path.with_suffix(".writing")
        staging.write_text(json.dumps(asdict(record)), encoding="utf-8")
        os.replace(staging, path)
        self._prune(record.env)
        return path

    def recent(self, env: str, limit: int = 20) -> list[RunRecord]:
        """The `limit` newest runs of `env`, newest first."""
        found: list[RunRecord] = []
        for path in self._files():
            record = _load(path)
            if record is None or record.env != env:
                continue
            found.append(record)
            if len(found) >= limit:
                break
        return found

    def latest(self, env: str) -> RunRecord | None:
        return next(iter(self.recent(env, 1)), None)

    def merged_results(self, env: str, limit: int = 20) -> dict[str, TestResult]:
        """What is known about every test, newest run wins — the state of the suite as a whole."""
        merged: dict[str, TestResult] = {}
        for record in self.recent(env, limit):
            for nodeid, result in record.results.items():
                merged.setdefault(nodeid, result)
        return merged

    def flaky(self, env: str, window: int = 10) -> dict[str, int]:
        """Tests whose verdict changed across the recent runs, and how often, worst first.

        A skip is not a verdict: a test that did not run contradicts nothing, and an error counts
        as a failure — what makes a test flaky is that it stopped agreeing with itself.
        """
        flips: dict[str, int] = {}
        previous: dict[str, str] = {}
        for record in reversed(self.recent(env, window)):
            for nodeid, result in record.results.items():
                if result.outcome == SKIPPED:
                    continue
                verdict = PASSED if result.outcome == PASSED else FAILED
                if previous.get(nodeid, verdict) != verdict:
                    flips[nodeid] = flips.get(nodeid, 0) + 1
                previous[nodeid] = verdict
        return dict(sorted(flips.items(), key=lambda item: (-item[1], item[0])))

    def failing_since(self, env: str, nodeid: str) -> float | None:
        """The start of the oldest run in this test's current failing streak; None if it is green.

        A run that did not include the test leaves the streak intact — a subset run says nothing
        about what it never exercised.
        """
        oldest: float | None = None
        for record in self.recent(env, self.keep):
            result = record.results.get(nodeid)
            if result is None or result.outcome == SKIPPED:
                continue
            if result.outcome == PASSED:
                break
            oldest = record.started_at
        return oldest

    def import_report(self, path: Path, env: str) -> RunRecord:
        """Ingest a pytest `--json-report` file produced elsewhere — a CI run — into the history."""
        report = Path(path)
        if not report.is_file():
            raise ReportError(f"{report}: no such file")
        summary = parse_report(report)
        if not summary.results:
            raise ReportError(f"{report}: no test results — is this a pytest --json-report file?")
        counts = summary.counts
        summary.returncode = 1 if counts[FAILED] or counts[ERROR] else 0
        record = summary.as_record(env)
        self.save(record)
        return record

    # ---- internals --------------------------------------------------------

    def _files(self) -> list[Path]:
        """Every run file, newest first — the name sorts chronologically by construction."""
        if not self.dir.is_dir():
            return []
        return sorted(self.dir.glob("*.json"), key=lambda path: path.name, reverse=True)

    def _prune(self, env: str) -> None:
        kept = 0
        for path in self._files():
            record = _load(path)
            if record is None or record.env != env:
                continue
            kept += 1
            if kept > self.keep:
                path.unlink(missing_ok=True)


def _filename(record: RunRecord) -> str:
    # Zero-padded so string order is time order, and salted with the run id so two runs starting
    # in the same millisecond cannot overwrite each other.
    return f"{int(record.started_at * 1000):015d}-{_slug(record.env)}-{record.id}.json"


def _slug(text: str) -> str:
    return _UNSAFE.sub("-", text).strip("-") or "unknown"


def _load(path: Path) -> RunRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _record_from(payload) if isinstance(payload, dict) else None


def _record_from(payload: dict[str, Any]) -> RunRecord | None:
    identifier = str(payload.get("id", ""))
    env = str(payload.get("env", ""))
    if not identifier or not env:
        return None
    raw = payload.get("results")
    results = {
        str(nodeid): _result_from(str(nodeid), entry)
        for nodeid, entry in (raw.items() if isinstance(raw, dict) else [])
        if isinstance(entry, dict)
    }
    return RunRecord(
        id=identifier,
        env=env,
        started_at=_number(payload.get("started_at")),
        finished_at=_number(payload.get("finished_at")),
        duration=_number(payload.get("duration")),
        returncode=int(_number(payload.get("returncode"))),
        results=results,
    )


def _result_from(nodeid: str, entry: dict[str, Any]) -> TestResult:
    steps = entry.get("steps")
    provisioned = entry.get("provisioned")
    return TestResult(
        nodeid=str(entry.get("nodeid", "")) or nodeid,
        outcome=str(entry.get("outcome", "")),
        duration=_number(entry.get("duration")),
        detail=str(entry.get("detail", "")),
        finished_at=_number(entry.get("finished_at")),
        steps=_steps_from(steps),
        provisioned=[str(item) for item in provisioned] if isinstance(provisioned, list) else [],
        held=held_from(entry.get("held")),
    )


def _steps_from(raw: Any) -> list[StepResult]:
    if not isinstance(raw, list):
        return []
    return [step_from(item) for item in raw if isinstance(item, dict)]


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


__all__ = ["DEFAULT_KEEP", "Held", "ReportError", "RunRecord", "RunStore", "StepResult", "TestResult"]
