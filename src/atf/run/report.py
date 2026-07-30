"""A run, said in the shape other tools already read."""

from __future__ import annotations

from typing import Any

from .runner import ERROR, FAILED, PASSED, SKIPPED, RunRecord

# What ATF's outcomes are called in CTRF. `error` becomes `failed` — see the module docstring.
STATUS = {PASSED: "passed", FAILED: "failed", SKIPPED: "skipped", ERROR: "failed"}

TOOL = "atf"
SPEC_VERSION = "0.0.0"


def as_ctrf(record: RunRecord) -> dict[str, Any]:
    """One run as a CTRF document, ready to be written as JSON."""
    tests = [_test(nodeid, record) for nodeid in sorted(record.results)]
    counts = record.counts
    return {
        "reportFormat": "CTRF",
        "specVersion": SPEC_VERSION,
        "results": {
            "tool": {"name": TOOL},
            "summary": {
                "tests": len(tests),
                "passed": counts[PASSED],
                "failed": counts[FAILED] + counts[ERROR],
                "pending": 0,
                "skipped": counts[SKIPPED],
                "other": 0,
                "start": _ms(record.started_at),
                "stop": _ms(record.finished_at),
            },
            "environment": {"testEnvironment": record.env},
            "tests": tests,
        },
    }


def _test(nodeid: str, record: RunRecord) -> dict[str, Any]:
    result = record.results[nodeid]
    entry: dict[str, Any] = {
        "name": nodeid,
        "status": STATUS.get(result.outcome, "other"),
        "duration": _ms(result.duration),
    }
    # The Gherkin step a scenario stopped on, which is the useful unit of failure for a BDD suite
    # and the thing a person reading CI wants first. CTRF has no field for it, so it goes in the
    # message beside the detail, where CTRF has no field of its own for one.
    if result.failed_step is not None:
        step = result.failed_step
        entry["message"] = f"{step.keyword} {step.text}".strip()
    if result.detail:
        entry["trace"] = result.detail
    return entry


def _ms(seconds: float) -> int:
    """CTRF counts in milliseconds; ATF counts in seconds. Timestamps are epoch either way."""
    return int(round(float(seconds or 0.0) * 1000))
