"""Per-environment state for the cockpit: bootstrap once, cache status/discovery/results/jobs.

Everything a router or template asks for comes from here, so a page render never decides for
itself whether to shell out. Run history is read from the store, which is why a fresh `atf serve`
already knows what the last run said.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..bootstrap import Boot, bootstrap
from ..discovery import Discovery, discover
from ..jobs import RUN, Job, JobRunner
from ..materializer import ABSENT, ERROR, Materializer
from ..runner import RunRecord, RunSummary, TestResult
from ..runner import run as run_tests
from ..store import RunStore

MAX_FOLD = 20


@dataclass
class EnvState:
    boot: Boot
    jobs: JobRunner
    # Serialises populating the cached views: the cockpit fires several requests per page and
    # FastAPI runs sync endpoints in a threadpool, so a check-then-act would launch duplicate
    # discovery subprocesses against one environment.
    lock: threading.Lock = field(default_factory=threading.Lock)
    status: dict[str, dict[str, Any]] = field(default_factory=dict)
    status_at: float = 0.0
    discovery: Discovery | None = None
    discovery_at: float = 0.0
    results: dict[str, TestResult] = field(default_factory=dict)
    results_at: float = 0.0
    loaded: bool = False

    @property
    def materializer(self) -> Materializer:
        return self.boot.materializer


class Cockpit:
    """Everything the routers need, cached per environment and refreshed lazily."""

    def __init__(self, env: str | None = None) -> None:
        self._states: dict[str, EnvState] = {}
        self._lock = threading.Lock()
        self.confirm_token = secrets.token_urlsafe(16)
        probe = bootstrap(env)
        self.manifest = probe.manifest
        self.default_env = probe.env
        self.store = RunStore(probe.manifest.root)
        self._states[probe.env] = self._build(probe)

    # ---- environments -----------------------------------------------------

    @property
    def environments(self) -> list[str]:
        return sorted(self.manifest.environments)

    def is_mutable(self, env: str) -> bool:
        return self.manifest.is_mutable(env)

    def state(self, env: str | None = None) -> EnvState:
        name = env or self.default_env
        with self._lock:
            state = self._states.get(name)
            if state is None:
                state = self._build(bootstrap(name))
                self._states[name] = state
            return state

    def _build(self, boot: Boot) -> EnvState:
        jobs = JobRunner(boot.manifest.root, boot.manifest.specs_dir, store=self.store)
        return EnvState(boot=boot, jobs=jobs)

    # ---- cached views -----------------------------------------------------

    def status(self, env: str | None = None, refresh: bool = False) -> dict[str, dict[str, Any]]:
        state = self.state(env)
        self._fold(state)  # a provision job that has finished since means the cache is stale
        if not (refresh or not state.status):
            return state.status
        with state.lock:
            if refresh or not state.status:
                state.status = state.materializer.status()
                state.status_at = time.time()
            return state.status

    def status_age(self, env: str | None = None) -> float | None:
        state = self.state(env)
        return time.time() - state.status_at if state.status_at else None

    def discovery(self, env: str | None = None, refresh: bool = False) -> Discovery:
        state = self.state(env)
        if not (refresh or state.discovery is None):
            return state.discovery
        with state.lock:
            if refresh or state.discovery is None:
                engine = state.materializer
                state.discovery = discover(
                    self.manifest.specs_dir,
                    engine.nodes,
                    set(engine.types),
                    state.boot.env,
                    self.manifest.root,
                )
                state.discovery_at = time.time()
            return state.discovery

    def discovery_age(self, env: str | None = None) -> float | None:
        state = self.state(env)
        return time.time() - state.discovery_at if state.discovery_at else None

    def invalidate(self, env: str | None = None) -> None:
        self._drop(self.state(env))

    def invalidate_all(self) -> None:
        """Every environment's caches, for a change to the source rather than to an environment.

        Editing the catalog is the same edit whichever environment is selected, so an environment
        built earlier would otherwise keep serving the catalog as it was before the edit.
        """
        with self._lock:
            states = list(self._states.values())
        for state in states:
            self._drop(state)

    @staticmethod
    def _drop(state: EnvState) -> None:
        state.materializer.reload()
        state.status = {}
        state.status_at = 0.0
        state.discovery = None
        state.discovery_at = 0.0

    # ---- results ----------------------------------------------------------

    def results(self, env: str | None = None) -> dict[str, TestResult]:
        """What is known about every test: the persisted history, then anything newer."""
        state = self.state(env)
        self._fold(state)
        active = state.jobs.active(state.boot.env)
        if active is None or active.kind != RUN:
            return state.results
        return {**state.results, **active.merged()}

    def result_for(self, nodeid: str, env: str | None = None) -> TestResult | None:
        return self.results(env).get(nodeid)

    def last_run(self, env: str | None = None) -> RunRecord | None:
        return self.store.latest(self.state(env).boot.env)

    def recent_runs(self, env: str | None = None, limit: int = 5) -> list[RunRecord]:
        return self.store.recent(self.state(env).boot.env, limit)

    def flaky(self, env: str | None = None, window: int = 10) -> dict[str, int]:
        return self.store.flaky(self.state(env).boot.env, window)

    def failing_since(self, nodeid: str, env: str | None = None) -> float | None:
        return self.store.failing_since(self.state(env).boot.env, nodeid)

    # ---- jobs -------------------------------------------------------------

    def provision_targets(self, env: str | None = None) -> list[str]:
        """The nodes a seed would actually touch, so the label and the button cannot disagree."""
        engine = self.state(env).materializer
        return [
            nid
            for nid, entry in self.status(env).items()
            if entry["status"] in {ABSENT, ERROR} and engine.provisionable(nid)[0]
        ]

    def start_run(self, nodeids: list[str], env: str | None = None) -> Job:
        state = self.state(env)
        return state.jobs.start_run(nodeids, state.boot.env, labels=_labels(state))

    def start_provision(self, node_ids: list[str], env: str | None = None) -> Job:
        state = self.state(env)
        return state.jobs.start_provision(node_ids, state.boot.env, state.materializer)

    def active_job(self, env: str | None = None) -> Job | None:
        state = self.state(env)
        job = state.jobs.active(state.boot.env)
        if job is None:
            self._fold(state)
        return job

    def job(self, job_id: str, env: str | None = None) -> Job | None:
        return self.state(env).jobs.get(job_id)

    def recent_jobs(self, env: str | None = None, limit: int = 5) -> list[Job]:
        return self.state(env).jobs.history(limit)

    def run_now(self, nodeids: list[str] | None, env: str | None = None) -> RunSummary:
        """Synchronous run — used by the CLI, not the web UI."""
        state = self.state(env)
        summary = run_tests(nodeids, state.boot.env, self.manifest.root, self.manifest.specs_dir)
        self.store.save(summary.as_record(state.boot.env))
        self._fold(state)
        state.results.update(summary.results)
        state.results_at = time.time()
        return summary

    def _fold(self, state: EnvState) -> None:
        """Bring the cached results up to date: the stored history first, then finished jobs."""
        if not state.loaded:
            state.results = {**self.store.merged_results(state.boot.env), **state.results}
            state.loaded = True

        # Oldest first, so the newest run wins whatever order the history is read in.
        pending = sorted(
            (job for job in state.jobs.history(MAX_FOLD) if job.finished_at > state.results_at),
            key=lambda job: job.finished_at,
        )
        for job in pending:
            if job.kind == RUN:
                state.results.update(job.merged())
            # Either kind moves the environment on, so the cached status is now a claim about a
            # world that no longer exists. A run provisions too — naming a resource in a scenario
            # is what creates it — so it invalidates exactly as provisioning does.
            state.status = {}
            state.status_at = 0.0
            state.results_at = max(state.results_at, job.finished_at)


def _labels(state: EnvState) -> dict[str, str]:
    """Scenario names for a run's rows — only if discovery already ran; never worth a subprocess."""
    found = state.discovery
    if found is None:
        return {}
    labels: dict[str, str] = {}
    for test in found.tests:
        spec = found.spec(test.covers) if test.covers else None
        if spec is None or not spec.scenario:
            continue
        labels[test.nodeid] = f"{spec.scenario} [{test.params}]" if test.params else spec.scenario
    return labels


_cockpit: Cockpit | None = None


def get_cockpit() -> Cockpit:
    global _cockpit
    if _cockpit is None:
        _cockpit = Cockpit()
    return _cockpit


def set_cockpit(cockpit: Cockpit | None) -> None:
    global _cockpit
    _cockpit = cockpit
