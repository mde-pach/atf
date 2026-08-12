"""Choosing which tests run, and turning what pytest said into a run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from . import runs
from .runs import Outcome, Run, TestOutcome, Where


@dataclass
class Selection:
    """What chose the tests, kept on the run so a partial one is never mistaken for a full one."""

    tags: list[str] = field(default_factory=list)
    failed: bool = False
    keyword: str = ""
    #: The scenario titles `--select` resolved to, or nothing where it was not given. Worked out by
    #: `atf explain`, from the sentences — never from a label somebody had to remember to add.
    titles: set[str] | None = None
    #: The order the tests ran in, where anything chose one. Recorded so a run can be repeated.
    seed: int | None = None
    #: Resolved from history when `failed` is set, so the plugin does not read history itself.
    failed_ids: set[str] = field(default_factory=set)

    def as_json(self) -> dict[str, Any]:
        return {
            "tag": self.tags or None,
            "select": sorted(self.titles) if self.titles is not None else None,
            "failed": self.failed,
            "seed": self.seed,
        }

    def is_empty(self) -> bool:
        return not (self.tags or self.titles is not None or self.failed or self.keyword)


class SelectionError(Exception):
    """Raised when a selection names something the suite does not declare — never started, exit 2."""


@dataclass
class Collected:
    """A pytest plugin that keeps one outcome per test, whatever pytest did to it."""

    outcomes: dict[str, TestOutcome] = field(default_factory=dict)
    collected: list[str] = field(default_factory=list)

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        self.collected = [item.nodeid for item in items]

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        """A test nobody selected is not a test that failed to report.

        `finish` marks anything collected and never heard from as stranded, which applies to a
        killed subprocess and not to `-k` or `--tag`.
        """
        dropped = {item.nodeid for item in items}
        self.collected = [nodeid for nodeid in self.collected if nodeid not in dropped]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Fold every phase of a test into one word, and keep where it failed."""
        existing = self.outcomes.get(report.nodeid)
        if report.when == "setup" and report.passed and existing is None:
            self.outcomes[report.nodeid] = TestOutcome(test=report.nodeid, outcome=Outcome.PASSED)

        duration = int(report.duration * 1000)
        if report.failed:
            self.outcomes[report.nodeid] = TestOutcome(
                test=report.nodeid,
                outcome=Outcome.FAILED,
                duration_ms=duration,
                failed_at=_where(report),
            )
        elif report.skipped and (existing is None or existing.outcome is not Outcome.FAILED):
            self.outcomes[report.nodeid] = TestOutcome(
                test=report.nodeid, outcome=Outcome.SKIPPED, duration_ms=duration
            )
        elif report.when == "call" and report.passed and existing is not None:
            existing.duration_ms = duration

    def finish(self) -> list[TestOutcome]:
        """Every collected test, including any the run never heard back about.

        A stranded test is `failed` with its reason. It did not pass and it was certainly not
        skipped, so a run that produced one must not go green.
        """
        for nodeid in self.collected:
            if nodeid not in self.outcomes:
                self.outcomes[nodeid] = TestOutcome(
                    test=nodeid,
                    outcome=Outcome.FAILED,
                    failed_at=Where(message=runs.STRANDED),
                )
        return [self.outcomes[nodeid] for nodeid in self.collected if nodeid in self.outcomes]


def _where(report: pytest.TestReport) -> Where:
    # `location` is absent on a report for a collection failure.
    location = report.location or ("", 0, "")
    file, line = str(location[0] or ""), int(location[1] or 0)
    message = str(report.longrepr) if report.longrepr is not None else ""
    step = ""
    for candidate in message.splitlines():
        stripped = candidate.strip()
        if stripped.split(" ", 1)[0] in ("Given", "When", "Then", "And", "But"):
            step = stripped
            break
    return Where(
        file=file,
        line=line + 1,
        step=step,
        message=message.strip(),
        artefacts=list(getattr(report, "atf_artefacts", []) or []),
    )


def build_run(
    environment: str,
    root: Path,
    selection: Selection,
    outcomes: list[TestOutcome],
    started: str,
) -> Run:
    return Run(
        id=runs.new_id(),
        environment=environment,
        started=started,
        finished=runs.now(),
        source="local",
        label=runs.label_from_environment(),
        revision=runs.revision(root),
        selection=selection.as_json(),
        outcomes=outcomes,
    )
