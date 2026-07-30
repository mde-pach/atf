"""One live view of a suite: its environments, and what each of them is doing."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from .engine.bootstrap import Boot, bootstrap
from .engine.materializer import Materializer
from .engine.status import Statuses
from .model.manifest import Manifest
from .run.jobs import RUN, Job, JobRunner
from .run.runner import RunRecord, RunSummary, TestResult
from .run.runner import run as run_tests
from .run.store import RunStore
from .suite.discovery import Discovery, discover

# How far back to look for a finished job whose results are not in the cache yet.
MAX_FOLD = 20


@dataclass
class EnvState:
    """One environment: what was bootstrapped for it, and what has been read since."""

    boot: Boot
    jobs: JobRunner
    # Serialises populating the cached views: several requests arrive per page and a web server runs
    # sync endpoints in a threadpool, so a check-then-act would launch duplicate discovery
    # subprocesses against one environment.
    lock: threading.Lock = field(default_factory=threading.Lock)
    status: Statuses = field(default_factory=Statuses)
    status_at: float = 0.0
    discovery: Discovery | None = None
    discovery_at: float = 0.0
    results: dict[str, TestResult] = field(default_factory=dict)
    results_at: float = 0.0
    loaded: bool = False

    @property
    def env(self) -> str:
        return self.boot.env

    @property
    def materializer(self) -> Materializer:
        return self.boot.materializer

    def forget_environment(self) -> None:
        """Drop what was read *about* the environment, keeping what was read about the suite."""
        self.status = Statuses()
        self.status_at = 0.0


class Environments:
    """Every environment this suite declares, bootstrapped the first time it is asked for."""

    def __init__(self, env: str | None = None) -> None:
        self._states: dict[str, EnvState] = {}
        self._lock = threading.Lock()
        probe = bootstrap(env)
        self.manifest: Manifest = probe.manifest
        self.default_env = probe.env
        self.store = RunStore(probe.manifest.root)
        self._states[probe.env] = self._build(probe)

    @property
    def names(self) -> list[str]:
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

    def all_states(self) -> list[EnvState]:
        with self._lock:
            return list(self._states.values())

    def materializer(self, env: str | None = None) -> Materializer:
        return self.state(env).materializer

    def _build(self, boot: Boot) -> EnvState:
        return EnvState(boot=boot, jobs=JobRunner(boot.manifest.root, boot.manifest.specs_dir, store=self.store))


class StatusCache:
    """What each environment holds, as of the last time anyone looked."""

    def __init__(self, environments: Environments, results: ResultsView) -> None:
        self._environments = environments
        self._results = results

    def of(self, env: str | None = None, refresh: bool = False) -> Statuses:
        state = self._environments.state(env)
        self._results.catch_up(state)  # a job that finished since means this cache is stale
        if not (refresh or not state.status):
            return state.status
        with state.lock:
            if refresh or not state.status:
                state.status = state.materializer.status()
                state.status_at = time.time()
            return state.status

    def age(self, env: str | None = None) -> float | None:
        state = self._environments.state(env)
        return time.time() - state.status_at if state.status_at else None


class DiscoveryCache:
    """What each environment's suite says: its features, steps and fixtures."""

    def __init__(self, environments: Environments) -> None:
        self._environments = environments

    def of(self, env: str | None = None, refresh: bool = False) -> Discovery:
        state = self._environments.state(env)
        if not (refresh or state.discovery is None):
            return state.discovery
        with state.lock:
            if refresh or state.discovery is None:
                state.discovery = discover(
                    self._environments.manifest.specs_dir,
                    state.materializer.catalog,
                    state.env,
                    self._environments.manifest.root,
                )
                state.discovery_at = time.time()
            return state.discovery


class ResultsView:
    """What the runs so far said, from the persisted history and from jobs that have since finished."""

    def __init__(self, environments: Environments) -> None:
        self._environments = environments
        self.store = environments.store

    def of(self, env: str | None = None) -> dict[str, TestResult]:
        """What is known about every test: the persisted history, then anything newer."""
        state = self._environments.state(env)
        self.catch_up(state)
        active = state.jobs.active(state.env)
        if active is None or active.kind != RUN:
            return state.results
        return {**state.results, **active.results()}

    def last_run(self, env: str | None = None) -> RunRecord | None:
        return self.store.latest(self._environments.state(env).env)

    def recent_runs(self, env: str | None = None, limit: int = 5) -> list[RunRecord]:
        return self.store.recent(self._environments.state(env).env, limit)

    def flaky(self, env: str | None = None, window: int = 10) -> dict[str, int]:
        return self.store.flaky(self._environments.state(env).env, window)

    def failing_since(self, nodeid: str, env: str | None = None) -> float | None:
        return self.store.failing_since(self._environments.state(env).env, nodeid)

    def catch_up(self, state: EnvState) -> None:
        """Bring the cached results up to date: the stored history first, then finished jobs."""
        if not state.loaded:
            state.results = {**self.store.merged_results(state.env), **state.results}
            state.loaded = True

        # Oldest first, so the newest run wins whatever order the history is read in.
        pending = sorted(
            (job for job in state.jobs.history(MAX_FOLD) if job.finished_at > state.results_at),
            key=lambda job: job.finished_at,
        )
        for job in pending:
            if job.kind == RUN:
                state.results.update(job.results())
            # Either kind moves the environment on, so the cached status is now a claim about a world
            # that no longer exists. A run provisions too — naming a resource in a scenario is what
            # creates it — so it invalidates exactly as provisioning does.
            state.forget_environment()
            state.results_at = max(state.results_at, job.finished_at)

    def record(self, state: EnvState, summary: RunSummary) -> None:
        """File a run that happened here, so the history and the cache both know about it."""
        self.store.save(summary.as_record(state.env))
        self.catch_up(state)
        state.results.update(summary.results)
        state.results_at = time.time()


class JobGateway:
    """Starting work against an environment, and watching what is in flight."""

    def __init__(self, environments: Environments, status: StatusCache, results: ResultsView) -> None:
        self._environments = environments
        self._status = status
        self._results = results

    def provision_targets(self, env: str | None = None) -> list[str]:
        """The nodes a seed would actually touch, so the label and the button cannot disagree."""
        engine = self._environments.materializer(env)
        return [
            nid for nid, entry in self._status.of(env).items() if entry.missing and engine.provisionable(nid)[0]
        ]

    def start_run(
        self, nodeids: list[str], env: str | None = None, keyword: str = "", tags: Sequence[str] = ()
    ) -> Job:
        state = self._environments.state(env)
        found = state.discovery
        # Only if discovery has already run: a name is never worth a subprocess.
        names = found.scenario_names() if found is not None else {}
        return state.jobs.start_run(nodeids, state.env, labels=names, keyword=keyword, tags=tags)

    def start_provision(self, node_ids: list[str], env: str | None = None) -> Job:
        state = self._environments.state(env)
        return state.jobs.start_provision(node_ids, state.env, state.materializer)

    def active(self, env: str | None = None) -> Job | None:
        state = self._environments.state(env)
        job = state.jobs.active(state.env)
        if job is None:
            self._results.catch_up(state)
        return job

    def get(self, job_id: str, env: str | None = None) -> Job | None:
        return self._environments.state(env).jobs.get(job_id)

    def recent(self, env: str | None = None, limit: int = 5) -> list[Job]:
        return self._environments.state(env).jobs.history(limit)

    def run_now(self, nodeids: list[str] | None, env: str | None = None) -> RunSummary:
        """Synchronous run — used by the CLI, not by a surface that can watch one."""
        state = self._environments.state(env)
        manifest = self._environments.manifest
        summary = run_tests(nodeids, state.env, manifest.root, manifest.specs_dir)
        self._results.record(state, summary)
        return summary


class Session:
    """One suite, live: its environments and the four views of each of them."""

    def __init__(self, env: str | None = None) -> None:
        self.confirm_token = secrets.token_urlsafe(16)
        self.environments = Environments(env)
        self.results = ResultsView(self.environments)
        self.status = StatusCache(self.environments, self.results)
        self.discovery = DiscoveryCache(self.environments)
        self.jobs = JobGateway(self.environments, self.status, self.results)

    # ---- what every surface asks first ------------------------------------

    @property
    def manifest(self) -> Manifest:
        return self.environments.manifest

    @property
    def default_env(self) -> str:
        return self.environments.default_env

    @property
    def store(self) -> RunStore:
        return self.environments.store

    def state(self, env: str | None = None) -> EnvState:
        return self.environments.state(env)

    def is_mutable(self, env: str) -> bool:
        return self.environments.is_mutable(env)

    # ---- the source changed -------------------------------------------------

    def invalidate(self, env: str | None = None) -> None:
        _drop(self.environments.state(env))

    def invalidate_all(self) -> None:
        """Every environment's caches, for a change to the suite's source.

        Editing the catalog is the same edit whichever environment is selected, so an environment
        built earlier would otherwise keep serving the catalog as it was before the edit.
        """
        for state in self.environments.all_states():
            _drop(state)


def _drop(state: EnvState) -> None:
    state.materializer.reload()
    state.forget_environment()
    state.discovery = None
    state.discovery_at = 0.0

