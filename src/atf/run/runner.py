"""Launching a suite, and the results a run comes back as."""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from ..spec import events
from ..spec.context import Slot
from ..spec.events import ERROR, FAILED, PASSED, SKIPPED, StepResult

DEFAULT_TIMEOUT = 1800
_LOCK = threading.Lock()

# How often the drain loop looks for more of what the child has said.
_TICK = 0.05

STRANDED = "the run ended before this test reported"


@dataclass
class TestResult:
    """One test, as a run reported it — and the row a job's progress view reads while it runs."""

    nodeid: str
    outcome: str
    label: str = ""
    duration: float = 0.0
    detail: str = ""
    finished_at: float = 0.0
    steps: list[StepResult] = field(default_factory=list)
    provisioned: list[str] = field(default_factory=list)
    held: list[Slot] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.nodeid

    @property
    def state(self) -> str:
        """Its outcome, under the word a job's progress view uses for either kind of work."""
        return self.outcome

    @property
    def done(self) -> bool:
        return self.outcome not in events.BUSY_STATES

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


@dataclass
class Launched:
    """What became of a launched run, whatever it said while it was running."""

    returncode: int = 0
    output: str = ""
    timed_out: bool = False


def launch(
    targets: Sequence[str],
    env: str,
    root: Path,
    specs_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    keyword: str = "",
    tags: Sequence[str] = (),
    on_event: Callable[[Mapping[str, Any]], None] | None = None,
) -> Launched:
    """Run pytest against `env`, handing every progress event to `on_event` as it arrives.

    `keyword` and `tags` narrow what runs — two arguments, and not a bag of pytest flags: a caller
    here is choosing *which scenarios*, which is a thing ATF can describe, and arbitrary flags would
    make `atf run` surface pytest's entire interface by accident.

    Output goes to a file, never a pipe: a pipe fills at ~64KB and the child then blocks forever,
    nothing reading it until the drain loop sees the process exit.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        environment = child_env(root, env)
        stream = events.channel_in(work, environment)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            events.PLUGIN,
            *(["-k", keyword_expression(keyword)] if keyword else []),
            *(["-m", tag_expression(tags)] if tags else []),
            *(list(targets) or ([str(specs_dir)] if specs_dir else [])),
        ]

        log = work / "output.log"
        with log.open("w", encoding="utf-8") as sink:
            process = subprocess.Popen(
                command,
                cwd=root,
                env=environment,
                stdout=sink,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            timed_out = _drain(process, stream, timeout, on_event)
            returncode = process.poll()

        output = _tail(log.read_text(encoding="utf-8", errors="replace"))
        if timed_out:
            output = f"run timed out after {timeout}s\n{output}".strip()
        # A killed process reports the signal that killed it, which says nothing a caller can use.
        return Launched(returncode=-1 if timed_out else (returncode or 0), output=output, timed_out=timed_out)


def _drain(
    process: subprocess.Popen[str],
    stream: Path,
    timeout: int,
    on_event: Callable[[Mapping[str, Any]], None] | None,
) -> bool:
    """Fold progress events until the run ends. Returns True if it had to be killed."""
    offset = 0
    deadline = time.time() + timeout
    while True:
        offset = _consume(stream, offset, on_event)
        if process.poll() is not None:
            _consume(stream, offset, on_event)
            return False
        if time.time() > deadline:
            _kill(process)
            _consume(stream, offset, on_event)
            return True
        time.sleep(_TICK)


def _consume(stream: Path, offset: int, on_event: Callable[[Mapping[str, Any]], None] | None) -> int:
    """Read whatever is complete beyond `offset`, and say where to read from next."""
    with stream.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        for line in handle:
            if not line.endswith("\n"):
                return handle.tell() - len(line)
            if on_event is not None:
                for event in events.read(line):
                    on_event(event)
        return handle.tell()


def _kill(process: subprocess.Popen[str]) -> None:
    """Kill the whole process group — pytest may have spawned children of its own."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)


def run(
    nodeids: Iterable[str] | None,
    env: str,
    root: Path,
    specs_dir: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    keyword: str = "",
    tags: Sequence[str] = (),
) -> RunSummary:
    """One launch, waited on: the same run a job reports live, read at the end instead."""
    results: dict[str, TestResult] = {}
    rows = partial(_row, results)
    started = time.time()
    with _LOCK:
        launched = launch(
            list(nodeids or []),
            env,
            root,
            specs_dir,
            timeout,
            keyword,
            tags,
            on_event=lambda event: events.apply(event, rows),
        )
    finished = time.time()

    for result in results.values():
        if not result.done:
            result.outcome = ERROR
            result.detail = result.detail or STRANDED
        result.finished_at = finished
    return RunSummary(
        results=results,
        returncode=launched.returncode,
        output=launched.output,
        duration=finished - started,
        started_at=started,
        finished_at=finished,
    )


def _row(results: dict[str, TestResult], nodeid: str) -> TestResult:
    """Where one test's progress is recorded, made the first time it is heard of."""
    result = results.get(nodeid)
    if result is None:
        result = TestResult(nodeid=nodeid, outcome=events.PENDING)
        results[nodeid] = result
    return result


# The words pytest reads as operators in a `-k` expression. Text containing one of them is somebody's
# own expression, and is passed through untouched.
_OPERATORS = frozenset({"and", "or", "not"})
_WORDS = re.compile(r"[^0-9a-z]+")


def keyword_expression(text: str) -> str:
    """What a person typed, as something pytest can match on.

    A scenario in ATF has a *title* — `A list belongs to its owner` — and that is what a person will
    type when they want to run it. pytest matches on the generated test name, so the words they
    typed reach it as `on its own` and it answers with a parse error about column 4. For a command
    meant to be the only dev loop, that is unusable.

    So a plain phrase is read as a phrase: the same flattening pytest-bdd does to a title when it
    makes a test name, which turns `belongs to its owner` into `belongs_to_its_owner` and matches.
    Anything containing `and`, `or`, `not` or a bracket is left exactly as written: that is somebody
    writing an expression, and ATF has no business rewriting one.
    """
    lowered = text.strip().lower()
    if not lowered or "(" in lowered or _OPERATORS & set(lowered.split()):
        return text.strip()
    return _WORDS.sub("_", lowered).strip("_")


def tag_expression(tags: Sequence[str]) -> str:
    """Several tags, as the one expression pytest takes: any of them, not all of them.

    `--tag smoke --tag api` reads as *"the smoke ones and the api ones"*, which is a union: a scenario
    carrying both is not what anybody asked for. A leading `@` is accepted and dropped, exactly as the
    manifest's `requires:` accepts one.
    """
    return " or ".join(tag.lstrip("@") for tag in tags if tag.lstrip("@"))


def failed_ids(record: RunRecord) -> list[str]:
    """What did not pass in a run, in the order a report lists them — what `--failed` runs again."""
    return sorted(nodeid for nodeid, result in record.results.items() if result.outcome in {FAILED, ERROR})


def child_env(root: Path, env: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["ATF_ENV"] = env
    manifest = root / "atf.yaml"
    if manifest.is_file():
        environment["ATF_MANIFEST"] = str(manifest)
    return environment


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _tail(text: str, limit: int = 2000) -> str:
    stripped = text.strip()
    return stripped[-limit:] if len(stripped) > limit else stripped
