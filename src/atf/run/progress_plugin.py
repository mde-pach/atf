"""Reports a pytest run as it happens, one event per phase. Loaded with `-p` by both launchers.

Every hook swallows its own errors, because observing a run must never fail one. The pytest-bdd
hooks live on a plugin object of their own, registered only when pytest-bdd is importable: pytest
rejects a plugin declaring hooks no installed plugin specifies.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from .events import (
    COLLECTED,
    DETAIL_CHARS,
    FAILED,
    PASSED,
    RESULT,
    SKIPPED,
    START,
    STEP,
    STEP_ERROR_CHARS,
    emit,
)


def pytest_collection_finish(session: Any) -> None:
    """What is going to run, after `-k` and `-m` have had their say."""
    emit({"event": COLLECTED, "nodeids": [item.nodeid for item in session.items]})


def pytest_runtest_logstart(nodeid: str, location: Any) -> None:
    emit({"event": START, "nodeid": nodeid, "at": time.time()})


def pytest_runtest_logreport(report: Any) -> None:
    emit(
        {
            "event": RESULT,
            "nodeid": report.nodeid,
            "phase": report.when,
            "outcome": report.outcome,
            "duration": getattr(report, "duration", 0.0),
            "detail": str(report.longrepr)[-DETAIL_CHARS:] if report.longrepr else "",
            "at": time.time(),
        }
    )


def _step(request: Any, step: Any, state: str, error: str = "") -> None:
    with contextlib.suppress(Exception):  # observing a run must never fail one
        emit(
            {
                "event": STEP,
                "nodeid": request.node.nodeid,
                "keyword": str(getattr(step, "keyword", "") or "").strip(),
                "text": str(getattr(step, "name", "") or ""),
                "state": state,
                "error": error[:STEP_ERROR_CHARS],
            }
        )


def _skip_rest(request: Any, scenario: Any, failed: Any) -> None:
    """A failed step abandons the scenario; report what it never got to."""
    try:
        steps = list(getattr(scenario, "steps", []))
        remaining = steps[steps.index(failed) + 1 :]
    except Exception:  # noqa: BLE001 - observing a run must never fail one
        return
    for step in remaining:
        _step(request, step, SKIPPED)


class _Steps:
    """Gherkin step outcomes. Registered only when pytest-bdd is installed."""

    def pytest_bdd_after_step(
        self, request: Any, feature: Any, scenario: Any, step: Any, step_func: Any, step_func_args: Any
    ) -> None:
        _step(request, step, PASSED)

    def pytest_bdd_step_error(
        self,
        request: Any,
        feature: Any,
        scenario: Any,
        step: Any,
        step_func: Any,
        step_func_args: Any,
        exception: BaseException,
    ) -> None:
        _step(request, step, FAILED, f"{type(exception).__name__}: {exception}".strip())
        _skip_rest(request, scenario, step)

    def pytest_bdd_step_func_lookup_error(
        self, request: Any, feature: Any, scenario: Any, step: Any, exception: BaseException
    ) -> None:
        _step(request, step, FAILED, "no step definition matches this step")
        _skip_rest(request, scenario, step)


def pytest_configure(config: Any) -> None:
    try:
        __import__("pytest_bdd")
    except Exception:  # noqa: BLE001 - a suite without pytest-bdd still reports its tests
        return
    config.pluginmanager.register(_Steps(), "atf_progress_steps")
