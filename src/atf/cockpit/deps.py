"""Per-environment state for the cockpit: bootstrap once, cache status/discovery/results/jobs."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..bootstrap import Boot, bootstrap
from ..discovery import Discovery, discover
from ..jobs import Job, JobRunner
from ..materializer import Materializer
from ..runner import RunSummary, TestResult
from ..runner import run as run_tests


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
    last_run: RunSummary | None = None

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
        self._states[probe.env] = EnvState(
            boot=probe,
            jobs=JobRunner(probe.manifest.root, probe.manifest.specs_dir),
        )

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
                boot = bootstrap(name)
                state = EnvState(boot=boot, jobs=JobRunner(boot.manifest.root, boot.manifest.specs_dir))
                self._states[name] = state
            return state

    # ---- cached views -----------------------------------------------------

    def status(self, env: str | None = None, refresh: bool = False) -> dict[str, dict[str, Any]]:
        state = self.state(env)
        if not (refresh or not state.status):
            return state.status
        with state.lock:
            if refresh or not state.status:
                state.status = state.materializer.status()
                state.status_at = time.time()
            return state.status

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
                self._fold_run_results(state)
            return state.discovery

    def results(self, env: str | None = None) -> dict[str, TestResult]:
        state = self.state(env)
        self._fold_active(state)
        return state.results

    def result_for(self, nodeid: str, env: str | None = None) -> TestResult | None:
        return self.results(env).get(nodeid)

    def invalidate(self, env: str | None = None) -> None:
        state = self.state(env)
        state.materializer.reload()
        state.status = {}
        state.discovery = None

    # ---- runs -------------------------------------------------------------

    def start_run(self, nodeids: list[str], env: str | None = None) -> Job:
        state = self.state(env)
        return state.jobs.start_run(nodeids, state.boot.env)

    def active_job(self, env: str | None = None) -> Job | None:
        state = self.state(env)
        job = state.jobs.active(state.boot.env)
        if job is None:
            self._fold_active(state)
        return job

    def job(self, job_id: str, env: str | None = None) -> Job | None:
        return self.state(env).jobs.get(job_id)

    def recent_jobs(self, env: str | None = None, limit: int = 5) -> list[Job]:
        return self.state(env).jobs.history(limit)

    def run_now(self, nodeids: list[str] | None, env: str | None = None) -> RunSummary:
        """Synchronous run — used by the CLI, not the web UI."""
        state = self.state(env)
        summary = run_tests(nodeids, state.boot.env, self.manifest.root, self.manifest.specs_dir)
        state.results.update(summary.results)
        state.results_at = time.time()
        state.last_run = summary
        return summary

    def _fold_active(self, state: EnvState) -> None:
        for job in state.jobs.history(limit=20):
            if job.finished_at > state.results_at:
                state.results.update(job.merged())
                state.results_at = max(state.results_at, job.finished_at)

    def _fold_run_results(self, state: EnvState) -> None:
        self._fold_active(state)


_cockpit: Cockpit | None = None


def get_cockpit() -> Cockpit:
    global _cockpit
    if _cockpit is None:
        _cockpit = Cockpit()
    return _cockpit


def set_cockpit(cockpit: Cockpit | None) -> None:
    global _cockpit
    _cockpit = cockpit
