"""What a run leaves behind: outcomes, the verdict folded over them, and the history beside them.

**There is no fourth outcome word.** `passed`, `failed`, `skipped`, and nothing else. What used to
be `error` — including a test the runner never heard back about — is `failed` with the reason in its
message, because a run that produced one must not go green.

**A run records what it did, never what the environment held.** Presence is asked of the environment
at the moment the question matters, so there is nothing here to go stale, to be gitignored, or to be
repaired.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

HISTORY_DIR = ".atf/history"
RETAINED = 50
#: What a test that was collected and never reported anything is failed with.
STRANDED = "the run ended before this test reported anything"


class Outcome(StrEnum):
    """What a run did, of one test once. Asked by running, and never mixed with what a place holds."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Verdict(StrEnum):
    """A fold of outcomes, for something that is not a single test."""

    PASSING = "passing"
    FAILING = "failing"
    SKIPPED = "skipped"
    NEVER_RUN = "never run"


@dataclass
class Where:
    """The line in your file, and the sentence written on it."""

    file: str = ""
    line: int = 0
    step: str = ""
    message: str = ""


@dataclass
class TestOutcome:
    """Exactly one per test per run."""

    test: str
    outcome: Outcome
    duration_ms: int = 0
    failed_at: Where | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "test": self.test,
            "outcome": str(self.outcome),
            "duration_ms": self.duration_ms,
        }
        if self.failed_at is not None:
            out["failed_at"] = asdict(self.failed_at)
        return out


@dataclass
class Run:
    """One execution of a selection of tests against one environment."""

    id: str
    environment: str
    started: str
    finished: str = ""
    source: str = "local"
    label: str = ""
    revision: str = ""
    selection: dict[str, Any] = field(default_factory=dict)
    outcomes: list[TestOutcome] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "environment": self.environment,
            "started": self.started,
            "finished": self.finished,
            "source": self.source,
            "label": self.label,
            "revision": self.revision,
            "selection": self.selection,
            "outcomes": [outcome.as_json() for outcome in self.outcomes],
        }

    @property
    def verdict(self) -> Verdict:
        return verdict(outcome.outcome for outcome in self.outcomes)

    @property
    def counts(self) -> dict[str, int]:
        return {
            word: sum(1 for outcome in self.outcomes if outcome.outcome == word)
            for word in (Outcome.PASSED, Outcome.FAILED, Outcome.SKIPPED)
        }


def verdict(outcomes: Any) -> Verdict:
    """Fold outcomes into one word. **Failure wins**, and the order is what makes it win.

    Nineteen rows passing under a heading and one failing is `failing`. `never run` is a verdict
    rather than a failure: a scenario nobody has run yet is labelled, not left blank.
    """
    seen = list(outcomes)
    if any(word == Outcome.FAILED for word in seen):
        return Verdict.FAILING
    if any(word == Outcome.PASSED for word in seen):
        return Verdict.PASSING
    if seen:
        return Verdict.SKIPPED
    return Verdict.NEVER_RUN


def new_id() -> str:
    return f"r-{uuid.uuid4().hex[:6]}"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def revision(root: Path) -> str:
    """The version control revision, if the suite is in one. Never fatal."""
    try:
        found = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return found.stdout.strip() if found.returncode == 0 else ""


# --- History ---------------------------------------------------------------------------------------


def history_dir(root: Path) -> Path:
    return root / HISTORY_DIR


def save(root: Path, run: Run) -> Path:
    """Write one run as one JSON file named by its id, and prune the oldest beyond the retained.

    **History is files, not a database.** A `.db` beside the manifest would read as something under
    test, since a suite's own `sqlite` adapter arranges resources in exactly such a file.
    """
    directory = history_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.id}.json"
    path.write_text(json.dumps(run.as_json(), indent=2) + "\n", encoding="utf-8")
    _prune(directory, run.environment)
    return path


def _prune(directory: Path, environment: str) -> None:
    """Keep the last `RETAINED` runs per environment. The oldest goes when a new one arrives."""
    mine = sorted(
        (run for run in load_all(directory) if run.environment == environment),
        key=lambda run: run.started,
    )
    for old in mine[:-RETAINED]:
        (directory / f"{old.id}.json").unlink(missing_ok=True)


def load_all(directory: Path) -> list[Run]:
    """Every readable run. **A corrupt file is skipped, not raised** — the tests still run."""
    if not directory.is_dir():
        return []
    runs: list[Run] = []
    for path in sorted(directory.glob("*.json")):
        run = _read(path)
        if run is None:
            print(f"atf: skipping unreadable run file {path}", file=sys.stderr)
            continue
        runs.append(run)
    return runs


def _read(path: Path) -> Run | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or "id" not in raw or "environment" not in raw:
        return None
    outcomes = []
    for entry in raw.get("outcomes") or []:
        if not isinstance(entry, dict) or "test" not in entry:
            return None
        try:
            word = Outcome(entry.get("outcome", ""))
        except ValueError:
            return None
        failed_at = entry.get("failed_at")
        outcomes.append(
            TestOutcome(
                test=str(entry["test"]),
                outcome=word,
                duration_ms=int(entry.get("duration_ms", 0)),
                failed_at=Where(**failed_at) if isinstance(failed_at, dict) else None,
            )
        )
    return Run(
        id=str(raw["id"]),
        environment=str(raw["environment"]),
        started=str(raw.get("started", "")),
        finished=str(raw.get("finished", "")),
        source=str(raw.get("source", "local")),
        label=str(raw.get("label", "")),
        revision=str(raw.get("revision", "")),
        selection=raw.get("selection") or {},
        outcomes=outcomes,
    )


def runs_for(root: Path, environment: str) -> list[Run]:
    """This environment's runs, oldest first."""
    return sorted(
        (run for run in load_all(history_dir(root)) if run.environment == environment),
        key=lambda run: run.started,
    )


def last_failed(root: Path, environment: str) -> list[str]:
    """Tests whose **last** outcome in this environment was `failed`. Empty history selects nothing."""
    latest: dict[str, Outcome] = {}
    for run in runs_for(root, environment):
        for outcome in run.outcomes:
            latest[outcome.test] = outcome.outcome
    return sorted(test for test, word in latest.items() if word == Outcome.FAILED)


def flaky(root: Path, environment: str) -> set[str]:
    """Tests whose outcomes in this environment's retained history disagree with each other.

    `skipped` beside one other word is not disagreement — skipping is a selection. ATF flags a flaky
    test and does not colour it: the verdict keeps its own word, and the flag says not to trust it.
    """
    seen: dict[str, set[Outcome]] = {}
    for run in runs_for(root, environment):
        for outcome in run.outcomes:
            seen.setdefault(outcome.test, set()).add(outcome.outcome)
    return {
        test
        for test, words in seen.items()
        if Outcome.PASSED in words and Outcome.FAILED in words
    }


def label_from_environment() -> str:
    """Free text carried in from CI, so an imported run says where it came from."""
    return os.environ.get("ATF_LABEL", "")


def stamp() -> float:
    return time.time()
