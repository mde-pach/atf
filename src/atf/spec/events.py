"""The protocol a run reports itself by: the words, the writer and the reader.

A run appends one JSON object per line to the file `ATF_PROGRESS_OUT` names, and whoever launched it
tails that file. Both halves live here, because a vocabulary with two implementations is two
vocabularies — and this one had four participants and no definition.

Writing never raises and never blocks: observing a run must not be able to fail one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .context import Slot

PROGRESS_OUT = "ATF_PROGRESS_OUT"

# The plugin, named as pytest loads it: `-p atf.spec.progress_plugin`.
PLUGIN = "atf.spec.progress_plugin"

COLLECTED = "collected"
START = "start"
RESULT = "result"
STEP = "step"
PROVISIONED = "provisioned"
HELD = "held"

SETUP, CALL, TEARDOWN = "setup", "call", "teardown"

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
ERROR = "error"

PENDING = "pending"
RUNNING = "running"
# Everything that is not pending or running is a verdict, whatever kind of work produced it.
BUSY_STATES = frozenset({PENDING, RUNNING})

# How much of a failure is worth carrying to whoever is watching.
DETAIL_CHARS = 600
STEP_ERROR_CHARS = 500


@dataclass
class StepResult:
    """One Gherkin step of one scenario, as the run reported it."""

    keyword: str
    text: str
    state: str
    error: str = ""

    @classmethod
    def from_event(cls, event: Mapping[str, Any]) -> StepResult:
        return cls(
            keyword=str(event.get("keyword", "")),
            text=str(event.get("text", "")),
            state=str(event.get("state", PASSED)),
            error=str(event.get("error", "")),
        )


class Recording(Protocol):
    """What one test's row offers the folder below: the parts an event changes."""

    outcome: str
    duration: float
    detail: str
    steps: list[StepResult]
    provisioned: list[str]
    held: list[Slot]

    @property
    def done(self) -> bool: ...


# Where a row for one nodeid lives, created on demand — a reader may hear about a test it was not
# told to expect.
Rows = Callable[[str], Recording]


def channel() -> str:
    """The file this run reports itself to, or `""` under a plain `pytest`."""
    return os.environ.get(PROGRESS_OUT, "")


def channel_in(directory: Path, environment: dict[str, str]) -> Path:
    """Open a channel for a run about to be launched, and point its environment at it."""
    stream = directory / "events.jsonl"
    stream.touch()
    environment[PROGRESS_OUT] = str(stream)
    return stream


def emit(event: dict[str, Any]) -> None:
    """Tell whoever is watching this run what just happened. Silent under a plain `pytest`."""
    path = channel()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
    except Exception:  # noqa: BLE001 - observing a run must never fail one
        pass


def read(text: str) -> Iterator[Mapping[str, Any]]:
    """Every complete event in `text`. An unparseable line is ignored."""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def apply(event: Mapping[str, Any], rows: Rows) -> None:
    """Fold one event into the row it is about.

    The one reader. A `result` arrives once per pytest phase: setup decides a skip and an error,
    the call decides the verdict, a failing teardown turns a pass into an error, and the durations
    add up to the time the test took.
    """
    kind = event.get("event")
    if kind == COLLECTED:
        for nodeid in event.get("nodeids", []):
            rows(str(nodeid))
        return

    nodeid = str(event.get("nodeid", ""))
    if not nodeid:
        return
    row = rows(nodeid)

    if kind == START:
        if not row.done:
            row.outcome = RUNNING
    elif kind == RESULT:
        _verdict(row, event)
    elif kind == STEP:
        row.steps.append(StepResult.from_event(event))
    elif kind == PROVISIONED:
        row.provisioned.extend(
            str(nid) for nid in event.get("ids", []) if str(nid) not in row.provisioned
        )
    elif kind == HELD:
        row.held = slots_from(event.get("slots"))


def _verdict(row: Recording, event: Mapping[str, Any]) -> None:
    row.duration += _number(event.get("duration"))
    phase = str(event.get("phase", CALL))
    outcome = str(event.get("outcome", ERROR))
    detail = str(event.get("detail", ""))

    if phase == SETUP and outcome == FAILED:
        # A test whose setup failed never ran: that is an error, not a failure.
        row.outcome, row.detail = ERROR, detail
    elif phase == SETUP and outcome == SKIPPED:
        row.outcome, row.detail = SKIPPED, detail
    elif phase == CALL:
        row.outcome, row.detail = outcome, detail
    elif phase == TEARDOWN and outcome == FAILED and row.outcome == PASSED:
        row.outcome, row.detail = ERROR, detail


def slots_from(raw: Any) -> list[Slot]:
    """Slot descriptions as reported, or as read back from history — the same shape either way."""
    if not isinstance(raw, list):
        return []
    return [Slot.from_dict(entry) for entry in raw if isinstance(entry, dict)]


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
