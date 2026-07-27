"""Background work with live per-item progress: test runs and provisioning, in one model.

A run happens in a pytest subprocess that writes one JSONL event per phase; a drain thread folds
those events into per-item state the cockpit polls. Provisioning happens in-process — the
materializer holds the adapters — on a thread reporting through the same item states. One shape,
so one progress view renders both.

At most one job is active per environment *across both kinds*: provisioning an environment while
tests run against it would race the very resources they read.
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .materializer import BLOCKED, CREATED, EXISTS, REFERENCE, Materializer
from .runner import (
    ERROR,
    FAILED,
    PASSED,
    PLUGIN_MODULE,
    SKIPPED,
    Held,
    RunSummary,
    StepResult,
    TestResult,
    child_env,
    held_from,
    inject_progress_plugin,
    step_from,
)
from .store import RunStore

DEFAULT_JOB_TIMEOUT = 1800
MAX_HISTORY = 50

RUN = "run"
PROVISION = "provision"

PENDING = "pending"
RUNNING = "running"
# Everything that is not pending or running is a verdict, whatever kind of job produced it.
BUSY_STATES = frozenset({PENDING, RUNNING})

_COUNTED = {
    RUN: (PENDING, RUNNING, PASSED, FAILED, SKIPPED, ERROR),
    PROVISION: (PENDING, RUNNING, CREATED, EXISTS, REFERENCE, BLOCKED, ERROR),
}


@dataclass
class ItemState:
    """One row of a job: a test in a run, a catalog node in a provision."""

    id: str
    label: str
    state: str
    duration: float = 0.0
    detail: str = ""
    steps: list[StepResult] = field(default_factory=list)
    provisioned: list[str] = field(default_factory=list)
    held: list[Held] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.state not in BUSY_STATES

    @property
    def failed_step(self) -> StepResult | None:
        return next((step for step in self.steps if step.state == FAILED), None)


@dataclass
class Job:
    id: str
    env: str
    kind: str
    started_at: float
    items: dict[str, ItemState]
    done: bool = False
    finished_at: float = 0.0
    returncode: int | None = None
    output: str = ""

    @property
    def total(self) -> int:
        return len(list(self.items))

    @property
    def completed(self) -> int:
        return sum(1 for item in list(self.items.values()) if item.done)

    @property
    def counts(self) -> dict[str, int]:
        totals = dict.fromkeys(_COUNTED.get(self.kind, ()), 0)
        for item in list(self.items.values()):
            totals[item.state] = totals.get(item.state, 0) + 1
        return totals

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    def merged(self) -> dict[str, TestResult]:
        """Finished tests as run results, for folding into the cached results."""
        finished = self.finished_at or time.time()
        return {
            item.id: TestResult(
                nodeid=item.id,
                outcome=item.state,
                duration=item.duration,
                detail=item.detail,
                finished_at=finished,
                steps=list(item.steps),
                provisioned=list(item.provisioned),
                held=list(item.held),
            )
            for item in list(self.items.values())
            if item.done
        }

    def summary(self) -> RunSummary:
        return RunSummary(
            results=self.merged(),
            returncode=self.returncode or 0,
            output=self.output,
            duration=self.elapsed,
            started_at=self.started_at,
            finished_at=self.finished_at or time.time(),
        )


class JobRunner:
    """Owns at most one active job per environment, of either kind, plus the recent history."""

    def __init__(
        self,
        root: Path,
        specs_dir: Path | None = None,
        timeout: int = DEFAULT_JOB_TIMEOUT,
        store: RunStore | None = None,
    ) -> None:
        self.root = root
        self.specs_dir = specs_dir
        self.timeout = timeout
        self.store = store if store is not None else RunStore(root)
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

    def start_run(self, nodeids: Sequence[str], env: str, labels: Mapping[str, str] | None = None) -> Job:
        """Run `nodeids` (everything, when empty). Returns the active job if one already holds `env`."""
        targets = list(nodeids)
        names = labels or {}
        items = {
            nodeid: ItemState(id=nodeid, label=names.get(nodeid) or humanize(nodeid), state=PENDING)
            for nodeid in targets
        }
        job, fresh = self._begin(env, RUN, items)
        if fresh:
            self._spawn(self._run, job, targets)
        return job

    def start_provision(
        self,
        node_ids: Sequence[str],
        env: str,
        engine: Materializer,
        keep_going: bool = True,
    ) -> Job:
        """Provision `node_ids` and their closure. Returns the active job if one already holds `env`."""
        wanted: list[str] = []
        for nid in node_ids:
            wanted.extend(item for item in engine.closure(nid) if item not in wanted)
        items = {
            nid: ItemState(id=nid, label=nid, state=PENDING)
            for nid in engine.topo(wanted)  # display order is provisioning order
        }
        job, fresh = self._begin(env, PROVISION, items)
        if fresh:
            self._spawn(self._provision, job, engine, node_ids, keep_going)
        return job

    # ---- internals --------------------------------------------------------

    def _begin(self, env: str, kind: str, items: dict[str, ItemState]) -> tuple[Job, bool]:
        with self._lock:
            running = self.active(env)
            if running is not None:
                return running, False
            self._counter += 1
            job = Job(id=f"job-{self._counter}", env=env, kind=kind, started_at=time.time(), items=items)
            self._jobs[env] = job
            return job, True

    def _spawn(self, work: Callable[..., None], job: Job, *args: Any) -> None:
        threading.Thread(target=self._guard, args=(work, job, *args), daemon=True).start()

    def _guard(self, work: Callable[..., None], job: Job, *args: Any) -> None:
        """Every job finishes exactly once, whatever the work did."""
        try:
            work(job, *args)
        except Exception as exc:  # noqa: BLE001 - a job reports its own failure, it never raises
            job.output = f"{job.kind} failed: {exc}"
            job.returncode = -1
        finally:
            self._finish(job)

    def _finish(self, job: Job) -> None:
        stranded = (
            "the run ended before this test reported"
            if job.kind == RUN
            else "the job ended before this resource was attempted"
        )
        for item in list(job.items.values()):
            if not item.done:
                item.state = ERROR
                item.detail = item.detail or stranded
        job.finished_at = time.time()
        if job.kind == RUN:
            # A run the cockpit started is history the next `atf serve` must still know about.
            with contextlib.suppress(OSError):
                self.store.save(job.summary().as_record(job.env))
        self._history.append(job)
        del self._history[:-MAX_HISTORY]
        # Last, and only now: `done` is what releases the environment, and a caller that sees it
        # must find the job in the history and its results in the store.
        job.done = True

    # ---- test runs --------------------------------------------------------

    def _run(self, job: Job, targets: list[str]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp)
            environment = child_env(self.root, job.env)
            events = inject_progress_plugin(plugin_dir, environment)

            selected = targets or ([str(self.specs_dir)] if self.specs_dir else [])
            # Output goes to a file, never a pipe: a pipe fills at ~64KB and the child blocks
            # forever, because nothing reads it until the drain loop sees the process exit.
            log = plugin_dir / "output.log"
            with log.open("w", encoding="utf-8") as sink:
                process = subprocess.Popen(
                    [sys.executable, "-m", "pytest", "-q", "-p", PLUGIN_MODULE, *selected],
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
                _item(job, str(nodeid))
            return

        nodeid = event.get("nodeid")
        if not nodeid:
            return
        item = _item(job, str(nodeid))
        if kind == "start" and not item.done:
            item.state = RUNNING
        elif kind == "result":
            item.state = str(event.get("outcome", ERROR))
            item.duration = float(event.get("duration", 0.0))
            item.detail = str(event.get("detail", ""))
        elif kind == "step":
            item.steps.append(step_from(event))
        elif kind == "provisioned":
            item.provisioned.extend(
                str(nid) for nid in event.get("ids", []) if str(nid) not in item.provisioned
            )
        elif kind == "held":
            item.held = held_from(event.get("slots"))

    # ---- provisioning -----------------------------------------------------

    def _provision(self, job: Job, engine: Materializer, node_ids: Sequence[str], keep_going: bool) -> None:
        started: dict[str, float] = {}

        def on_start(nid: str) -> None:
            started[nid] = time.time()
            item = _item(job, nid)
            item.state = RUNNING

        def on_result(result: dict[str, Any]) -> None:
            nid = str(result["id"])
            item = _item(job, nid)
            item.state = _provision_state(result)
            item.detail = str(result.get("detail", ""))
            item.duration = time.time() - started.get(nid, job.started_at)

        outcome = engine.materialize(node_ids, keep_going=keep_going, on_start=on_start, on_result=on_result)
        failures = [entry for entry in outcome["results"] if not entry["ok"]]
        job.returncode = 1 if failures else 0
        if failures:
            first = failures[0]
            job.output = (
                f"{len(failures)} of {len(outcome['results'])} did not provision — "
                f"{first['id']}: {first.get('detail') or first['action']}"
            )


def humanize(nodeid: str) -> str:
    """`…::test_a_list_belongs_to_its_owner` -> `A list belongs to its owner`.

    A fallback label: discovery knows the real scenario name, but a job may be started before
    discovery has run, and a row with no name is worse than a derived one.
    """
    name = nodeid.rsplit("::", 1)[-1]
    head, bracket, params = name.partition("[")
    text = head.removeprefix("test_").replace("_", " ").strip()
    if not text:
        return name
    return text[:1].upper() + text[1:] + (f" [{params}" if bracket else "")


def _item(job: Job, item_id: str) -> ItemState:
    item = job.items.get(item_id)
    if item is None:
        item = ItemState(id=item_id, label=humanize(item_id) if job.kind == RUN else item_id, state=PENDING)
        job.items[item_id] = item
    return item


def _provision_state(result: dict[str, Any]) -> str:
    """A node's action is its state only when it worked: a `reference` that was not found failed."""
    action = str(result["action"])
    if result["ok"]:
        return action
    return BLOCKED if action == BLOCKED else ERROR
