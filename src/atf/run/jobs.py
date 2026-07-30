"""Background work with live per-item progress: test runs and provisioning, in one model."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from ..engine.materializer import Materializer
from ..engine.status import BLOCKED, CREATED, EXISTS, ProvisionResult
from ..model.typespec import REFERENCE
from ..spec import events
from ..spec.events import BUSY_STATES, ERROR, FAILED, PASSED, PENDING, RUNNING, SKIPPED
from .runner import STRANDED, RunSummary, TestResult, launch
from .store import RunStore

DEFAULT_JOB_TIMEOUT = 1800
MAX_HISTORY = 50

RUN = "run"
PROVISION = "provision"

_COUNTED = {
    RUN: (PENDING, RUNNING, PASSED, FAILED, SKIPPED, ERROR),
    PROVISION: (PENDING, RUNNING, CREATED, EXISTS, REFERENCE, BLOCKED, ERROR),
}


class Row(Protocol):
    """One unit of a job's work, as the progress view reads it.

    What a test result and a node being provisioned have in common, and no more: one row type holds a
    run outcome and a provisioning action in one field, and every reader of it has to know which kind
    of job it is looking at to know what that field means.
    """

    duration: float
    detail: str

    @property
    def id(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def state(self) -> str: ...

    @property
    def done(self) -> bool: ...


@dataclass
class Provisioning:
    """One catalog node's turn in a provisioning job."""

    node_id: str
    state: str = PENDING
    duration: float = 0.0
    detail: str = ""

    @property
    def id(self) -> str:
        return self.node_id

    @property
    def label(self) -> str:
        return self.node_id

    @property
    def done(self) -> bool:
        return self.state not in BUSY_STATES


@dataclass
class Job:
    id: str
    env: str
    kind: str
    started_at: float
    items: dict[str, Row]
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

    def results(self) -> dict[str, TestResult]:
        """The finished tests of a run job — what the cockpit folds into its cached results."""
        return {
            item.nodeid: item for item in list(self.items.values()) if isinstance(item, TestResult) and item.done
        }

    def summary(self) -> RunSummary:
        return RunSummary(
            results=self.results(),
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

    def start_run(
        self,
        nodeids: Sequence[str],
        env: str,
        labels: Mapping[str, str] | None = None,
        keyword: str = "",
        tags: Sequence[str] = (),
    ) -> Job:
        """Run `nodeids` (everything, when empty). Returns the active job if one already holds `env`."""
        targets = list(nodeids)
        names = labels or {}
        items: dict[str, Row] = {
            nodeid: TestResult(nodeid=nodeid, outcome=PENDING, label=names.get(nodeid) or humanize(nodeid))
            for nodeid in targets
        }
        job, fresh = self._begin(env, RUN, items)
        if fresh:
            self._spawn(self._run, job, targets, keyword, tags)
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
        items: dict[str, Row] = {
            nid: Provisioning(node_id=nid)
            for nid in engine.topo(wanted)  # display order is provisioning order
        }
        job, fresh = self._begin(env, PROVISION, items)
        if fresh:
            self._spawn(self._provision, job, engine, node_ids, keep_going)
        return job

    # ---- internals --------------------------------------------------------

    def _begin(self, env: str, kind: str, items: dict[str, Row]) -> tuple[Job, bool]:
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
        stranded = STRANDED if job.kind == RUN else "the job ended before this resource was attempted"
        job.finished_at = time.time()
        for item in list(job.items.values()):
            if not item.done:
                _abandon(item, stranded)
            if isinstance(item, TestResult):
                item.finished_at = job.finished_at
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

    def _run(self, job: Job, targets: list[str], keyword: str, tags: Sequence[str]) -> None:
        launched = launch(
            targets,
            job.env,
            self.root,
            self.specs_dir,
            self.timeout,
            keyword,
            tags,
            on_event=lambda event: events.apply(event, partial(_test, job)),
        )
        job.returncode = launched.returncode
        job.output = launched.output

    # ---- provisioning -----------------------------------------------------

    def _provision(self, job: Job, engine: Materializer, node_ids: Sequence[str], keep_going: bool) -> None:
        started: dict[str, float] = {}

        def on_start(nid: str) -> None:
            started[nid] = time.time()
            _node(job, nid).state = RUNNING

        def on_result(result: ProvisionResult) -> None:
            item = _node(job, result.node_id)
            item.state = result.state
            item.detail = result.detail
            item.duration = time.time() - started.get(result.node_id, job.started_at)

        outcome = engine.materialize(node_ids, keep_going=keep_going, on_start=on_start, on_result=on_result)
        job.returncode = 1 if outcome.failures else 0
        first = next(iter(outcome.failures), None)
        if first is not None:
            job.output = (
                f"{len(outcome.failures)} of {len(outcome.results)} did not provision — "
                f"{first.node_id}: {first.detail or first.action}"
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


def _test(job: Job, nodeid: str) -> TestResult:
    """Where one test's progress is recorded — made the first time the run mentions it."""
    item = job.items.get(nodeid)
    if not isinstance(item, TestResult):
        item = TestResult(nodeid=nodeid, outcome=PENDING, label=humanize(nodeid))
        job.items[nodeid] = item
    return item


def _node(job: Job, node_id: str) -> Provisioning:
    item = job.items.get(node_id)
    if not isinstance(item, Provisioning):
        item = Provisioning(node_id=node_id)
        job.items[node_id] = item
    return item


def _abandon(item: Row, why: str) -> None:
    """Say what became of a row nothing ever reported, in whichever word its kind uses."""
    if isinstance(item, TestResult):
        item.outcome = ERROR
    elif isinstance(item, Provisioning):
        item.state = ERROR
    item.detail = item.detail or why
