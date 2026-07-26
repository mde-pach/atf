"""Background runs with live per-test progress (§12).

A run writes one JSONL event per test phase to a temp file; a drain thread folds those events
into per-nodeid state the cockpit polls. One active job per environment.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .runner import ERROR, FAILED, PASSED, SKIPPED, RunSummary, TestResult, child_env

DEFAULT_JOB_TIMEOUT = 1800
MAX_HISTORY = 50

PENDING = "pending"
RUNNING = "running"
DONE_STATES = frozenset({PASSED, FAILED, SKIPPED, ERROR})

_PROGRESS_PLUGIN = '''
import json
import os
import time

_PATH = os.environ["ATF_PROGRESS_OUT"]


def _emit(event):
    with open(_PATH, "a") as handle:
        handle.write(json.dumps(event) + "\\n")
        handle.flush()


def pytest_collection_modifyitems(session, config, items):
    _emit({"event": "collected", "nodeids": [item.nodeid for item in items]})


def pytest_runtest_logstart(nodeid, location):
    _emit({"event": "start", "nodeid": nodeid, "at": time.time()})


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        outcome = report.outcome
        if report.when == "setup" and outcome == "failed":
            outcome = "error"
        _emit(
            {
                "event": "result",
                "nodeid": report.nodeid,
                "outcome": outcome,
                "duration": getattr(report, "duration", 0.0),
                "detail": str(report.longrepr)[-600:] if report.longrepr else "",
                "at": time.time(),
            }
        )


def pytest_sessionfinish(session, exitstatus):
    _emit({"event": "finished", "exitstatus": int(exitstatus), "at": time.time()})
'''


@dataclass
class TState:
    nodeid: str
    state: str = PENDING
    duration: float = 0.0
    detail: str = ""

    @property
    def done(self) -> bool:
        return self.state in DONE_STATES


@dataclass
class Job:
    id: str
    env: str
    nodeids: list[str]
    started_at: float
    states: dict[str, TState] = field(default_factory=dict)
    done: bool = False
    returncode: int | None = None
    output: str = ""
    finished_at: float = 0.0

    @property
    def total(self) -> int:
        return len(list(self.states))

    @property
    def completed(self) -> int:
        return sum(1 for state in list(self.states.values()) if state.done)

    @property
    def counts(self) -> dict[str, int]:
        totals = {PENDING: 0, RUNNING: 0, PASSED: 0, FAILED: 0, SKIPPED: 0, ERROR: 0}
        for state in list(self.states.values()):
            totals[state.state] = totals.get(state.state, 0) + 1
        return totals

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def merged(self) -> dict[str, TestResult]:
        """Finished tests as run results, for folding into the cached results."""
        return {
            nodeid: TestResult(
                nodeid=nodeid,
                outcome=state.state,
                duration=state.duration,
                detail=state.detail,
                finished_at=time.time(),
            )
            for nodeid, state in list(self.states.items())
            if state.done
        }

    def summary(self) -> RunSummary:
        return RunSummary(results=self.merged(), returncode=self.returncode or 0, output=self.output)


class JobRunner:
    """Owns at most one active job per environment."""

    def __init__(self, root: Path, specs_dir: Path | None = None, timeout: int = DEFAULT_JOB_TIMEOUT) -> None:
        self.root = root
        self.specs_dir = specs_dir
        self.timeout = timeout
        self._jobs: dict[str, Job] = {}
        self._history: list[Job] = []
        self._lock = threading.Lock()
        self._counter = 0

    def active(self, env: str) -> Job | None:
        job = self._jobs.get(env)
        return job if job is not None and not job.done else None

    def get(self, job_id: str) -> Job | None:
        for job in [*self._jobs.values(), *self._history]:
            if job.id == job_id:
                return job
        return None

    def history(self, limit: int = 10) -> list[Job]:
        return list(reversed(self._history[-limit:]))

    def start_run(self, nodeids: Sequence[str], env: str) -> Job:
        with self._lock:
            running = self.active(env)
            if running is not None:
                return running
            self._counter += 1
            job = Job(
                id=f"job-{self._counter}",
                env=env,
                nodeids=list(nodeids),
                started_at=time.time(),
                states={nodeid: TState(nodeid=nodeid) for nodeid in nodeids},
            )
            self._jobs[env] = job

        thread = threading.Thread(target=self._execute, args=(job,), daemon=True)
        thread.start()
        return job

    # ---- internals --------------------------------------------------------

    def _execute(self, job: Job) -> None:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                plugin_dir = Path(tmp)
                (plugin_dir / "atf_progress.py").write_text(_PROGRESS_PLUGIN, encoding="utf-8")
                events = plugin_dir / "events.jsonl"
                events.touch()

                environment = child_env(self.root, job.env)
                environment["ATF_PROGRESS_OUT"] = str(events)
                environment["PYTHONPATH"] = _prepend_path(str(plugin_dir), environment.get("PYTHONPATH"))

                targets = job.nodeids or ([str(self.specs_dir)] if self.specs_dir else [])
                # Output goes to a file, never a pipe: a pipe fills at ~64KB and the child blocks
                # forever, because nothing reads it until the drain loop sees the process exit.
                log = plugin_dir / "output.log"
                with log.open("w", encoding="utf-8") as sink:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "pytest", "-q", "-p", "atf_progress", *targets],
                        cwd=self.root,
                        env=environment,
                        stdout=sink,
                        stderr=subprocess.STDOUT,
                        text=True,
                        start_new_session=True,
                    )
                    timed_out = self._drain(job, events, process)
                    job.returncode = process.poll()

                job.output = log.read_text(encoding="utf-8", errors="replace").strip()[-2000:]
                if timed_out:
                    job.output = f"run timed out after {self.timeout}s\n{job.output}".strip()
        except Exception as exc:
            job.output = f"run failed: {exc}"
            job.returncode = -1
        finally:
            for state in list(job.states.values()):
                if not state.done:
                    state.state = ERROR
                    state.detail = state.detail or "the run ended before this test reported"
            job.finished_at = time.time()
            job.done = True
            self._history.append(job)
            del self._history[:-MAX_HISTORY]

    def _drain(self, job: Job, events: Path, process: subprocess.Popen[str]) -> bool:
        """Fold progress events until the run ends. Returns True if it had to be killed."""
        offset = 0
        deadline = time.time() + self.timeout
        while True:
            offset = self._consume(job, events, offset)
            if process.poll() is not None:
                self._consume(job, events, offset)
                return False
            if time.time() > deadline:
                self._kill(process)
                self._consume(job, events, offset)
                return True
            time.sleep(0.05)

    @staticmethod
    def _kill(process: subprocess.Popen[str]) -> None:
        """Kill the whole process group — pytest may have spawned children of its own."""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)

    def _consume(self, job: Job, events: Path, offset: int) -> int:
        with events.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            for line in handle:
                if not line.endswith("\n"):
                    return handle.tell() - len(line)
                self._apply(job, line)
            return handle.tell()

    def _apply(self, job: Job, line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            return

        kind = event.get("event")
        if kind == "collected":
            for nodeid in event.get("nodeids", []):
                job.states.setdefault(nodeid, TState(nodeid=nodeid))
            return

        nodeid = event.get("nodeid")
        if not nodeid:
            return
        state = job.states.setdefault(nodeid, TState(nodeid=nodeid))
        if kind == "start" and not state.done:
            state.state = RUNNING
        elif kind == "result":
            state.state = str(event.get("outcome", ERROR))
            state.duration = float(event.get("duration", 0.0))
            state.detail = str(event.get("detail", ""))


def _prepend_path(entry: str, existing: str | None) -> str:
    import os

    return os.pathsep.join([entry, *filter(None, [existing])])
