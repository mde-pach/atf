"""Synchronous test runs -> structured results.

Runs pytest in a subprocess with `ATF_ENV` set and parses its JSON report. Serialized by a
process-wide lock and guarded by a timeout: one run at a time, and never an unbounded wait.
Use `jobs.JobRunner` instead when progress must be observable while the run is in flight.

The result model lives here because every producer fills the same shape: this module, the job
runner, and a report imported from CI. For a BDD suite the useful unit of failure is the Gherkin
step, not the tail of a traceback, so both execution paths inject `PROGRESS_PLUGIN` into the
pytest process to report steps and provisioning as they happen.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 1800
_LOCK = threading.Lock()

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
ERROR = "error"

PLUGIN_MODULE = "atf_progress"
PROGRESS_OUT = "ATF_PROGRESS_OUT"

# Injected into the pytest process by both execution paths, as a module on PYTHONPATH loaded with
# `-p`. It appends one JSON object per line to the file `ATF_PROGRESS_OUT` names; the reader tails
# that file. Every hook swallows its own errors: observing a run must never fail one. The
# pytest-bdd hooks live on a separate plugin object registered only when pytest-bdd is importable,
# because pytest rejects a plugin declaring hooks no installed plugin specifies.
PROGRESS_PLUGIN = '''
"""Reports a pytest run as it happens, one JSONL event per line. Written by ATF, not by the user."""

import json
import os
import time

_PATH = os.environ["ATF_PROGRESS_OUT"]


def _emit(event):
    try:
        with open(_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\\n")
    except Exception:
        pass


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


def _step(request, step, state, error=""):
    try:
        _emit(
            {
                "event": "step",
                "nodeid": request.node.nodeid,
                "keyword": str(getattr(step, "keyword", "") or "").strip(),
                "text": str(getattr(step, "name", "") or ""),
                "state": state,
                "error": error[:500],
            }
        )
    except Exception:
        pass


def _skip_rest(request, scenario, failed):
    """A failed step abandons the scenario; report what it never got to."""
    try:
        steps = list(getattr(scenario, "steps", []))
        remaining = steps[steps.index(failed) + 1 :]
    except Exception:
        return
    for step in remaining:
        _step(request, step, "skipped")


class _Steps:
    """Gherkin step outcomes. Registered only when pytest-bdd is installed."""

    def pytest_bdd_after_step(self, request, feature, scenario, step, step_func, step_func_args):
        _step(request, step, "passed")

    def pytest_bdd_step_error(self, request, feature, scenario, step, step_func, step_func_args, exception):
        _step(request, step, "failed", f"{type(exception).__name__}: {exception}".strip())
        _skip_rest(request, scenario, step)

    def pytest_bdd_step_func_lookup_error(self, request, feature, scenario, step, exception):
        _step(request, step, "failed", "no step definition matches this step")
        _skip_rest(request, scenario, step)


def pytest_configure(config):
    try:
        __import__("pytest_bdd")
    except Exception:
        return
    config.pluginmanager.register(_Steps(), "atf_progress_steps")
'''


@dataclass
class StepResult:
    keyword: str
    text: str
    state: str
    error: str = ""


@dataclass
class TestResult:
    nodeid: str
    outcome: str
    duration: float = 0.0
    detail: str = ""
    finished_at: float = 0.0
    steps: list[StepResult] = field(default_factory=list)
    provisioned: list[str] = field(default_factory=list)

    @property
    def failed_step(self) -> StepResult | None:
        return next((step for step in self.steps if step.state == FAILED), None)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class RunRecord:
    """One complete run of a suite against one environment — what the store persists."""

    id: str
    env: str
    started_at: float
    finished_at: float
    duration: float
    returncode: int
    results: dict[str, TestResult]

    @property
    def counts(self) -> dict[str, int]:
        return count_outcomes(self.results.values())


@dataclass
class RunSummary:
    results: dict[str, TestResult] = field(default_factory=dict)
    returncode: int = 0
    output: str = ""
    duration: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def counts(self) -> dict[str, int]:
        return count_outcomes(self.results.values())

    def as_record(self, env: str) -> RunRecord:
        return RunRecord(
            id=new_run_id(),
            env=env,
            started_at=self.started_at,
            finished_at=self.finished_at,
            duration=self.duration,
            returncode=self.returncode,
            results=dict(self.results),
        )


def count_outcomes(results: Iterable[TestResult]) -> dict[str, int]:
    totals = {PASSED: 0, FAILED: 0, SKIPPED: 0, ERROR: 0}
    for result in results:
        totals[result.outcome] = totals.get(result.outcome, 0) + 1
    return totals


def new_run_id() -> str:
    return secrets.token_hex(4)


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
        environment = child_env(root, env)
        events = inject_progress_plugin(Path(tmp), environment)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "--json-report",
            f"--json-report-file={report}",
            "-q",
            "-p",
            PLUGIN_MODULE,
            *(targets or ([str(specs_dir)] if specs_dir else [])),
        ]
        started = time.time()
        completed = _launch(command, root, environment, timeout)
        if completed is None:
            return RunSummary(
                returncode=-1,
                output=f"run timed out after {timeout}s",
                started_at=started,
                finished_at=time.time(),
            )
        summary = parse_report(report)
        summary.returncode = completed.returncode
        summary.output = _tail(completed.stdout + completed.stderr)
        summary.started_at = summary.started_at or started
        summary.finished_at = summary.finished_at or time.time()
        fold_events(summary.results, events)
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


def inject_progress_plugin(directory: Path, environment: dict[str, str]) -> Path:
    """Write the progress plugin into `directory`, point `environment` at it, return its event file."""
    (directory / f"{PLUGIN_MODULE}.py").write_text(PROGRESS_PLUGIN, encoding="utf-8")
    events = directory / "events.jsonl"
    events.touch()
    environment[PROGRESS_OUT] = str(events)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(directory), *filter(None, [environment.get("PYTHONPATH")])]
    )
    return events


def read_events(path: Path) -> Iterator[dict[str, Any]]:
    """Every complete event in the file. A truncated or unparseable line is ignored."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def fold_events(results: dict[str, TestResult], events: Path) -> None:
    """Enrich parsed results with the step outcomes and provisioning the plugin reported."""
    for event in read_events(events):
        result = results.get(str(event.get("nodeid", "")))
        if result is None:
            continue
        if event.get("event") == "step":
            result.steps.append(step_from(event))
        elif event.get("event") == "provisioned":
            result.provisioned.extend(nid for nid in _ids(event) if nid not in result.provisioned)


def step_from(event: dict[str, Any]) -> StepResult:
    return StepResult(
        keyword=str(event.get("keyword", "")),
        text=str(event.get("text", "")),
        state=str(event.get("state", PASSED)),
        error=str(event.get("error", "")),
    )


def parse_report(report: Path) -> RunSummary:
    """Read a pytest `--json-report` file. An absent or unreadable one yields an empty summary."""
    summary = RunSummary()
    if not report.exists():
        return summary
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return summary
    if not isinstance(payload, dict):
        return summary

    summary.duration = _number(payload.get("duration"))
    summary.finished_at = _number(payload.get("created"))
    summary.started_at = max(summary.finished_at - summary.duration, 0.0)
    for entry in payload.get("tests", []):
        if not isinstance(entry, dict):
            continue
        nodeid = str(entry.get("nodeid", ""))
        if not nodeid:
            continue
        duration = sum(_phase_duration(entry.get(phase)) for phase in ("setup", "call", "teardown"))
        summary.results[nodeid] = TestResult(
            nodeid=nodeid,
            outcome=str(entry.get("outcome", ERROR)),
            duration=duration,
            detail=_detail(entry),
            finished_at=summary.finished_at,
        )
    return summary


def _launch(
    command: list[str], root: Path, environment: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None


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


def _ids(event: dict[str, Any]) -> list[str]:
    raw = event.get("ids")
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _phase_duration(stage: Any) -> float:
    return _number(stage.get("duration")) if isinstance(stage, dict) else 0.0


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _tail(text: str, limit: int = 2000) -> str:
    stripped = text.strip()
    return stripped[-limit:] if len(stripped) > limit else stripped
