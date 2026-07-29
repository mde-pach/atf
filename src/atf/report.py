"""A run, said in the shape other tools already read.

`atf run --json` exists so that a run is usable by something that is not a person: a CI gate, a
dashboard, a bot that comments on a pull request. The temptation is to invent a shape — ATF's own
result model is right there, and dumping it is one line.

That would be wrong, and the reason is the whole point of the flag. A format nobody else reads is
a format every consumer has to be taught, which means the gate gets written once, by hand, per
project. **CTRF** (the Common Test Report Format) is the interchange format the tooling around test
runs has settled on, and emitting it is what makes a run mean something to software ATF has never
heard of.

So this module is a translation and nothing more. It decides nothing, drops nothing, and holds no
opinion the result model does not already hold — which is also why it is a pure function over a
`RunRecord` and unit-tested as one.

**The one judgement in it is what an outcome is called.** CTRF's statuses are `passed`, `failed`,
`skipped`, `pending` and `other`, and ATF's are `passed`, `failed`, `skipped` and `error`. An error
is a test that never got to run its body — a fixture raised, a resource could not be provisioned —
and calling that `failed` is the honest reading: the suite did not go green, and a gate that treats
"it broke before it started" as anything softer is a gate that lets a broken suite through.
"""

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
    # message beside the detail rather than being dropped for want of a home.
    if result.failed_step is not None:
        step = result.failed_step
        entry["message"] = f"{step.keyword} {step.text}".strip()
    if result.detail:
        entry["trace"] = result.detail
    return entry


def _ms(seconds: float) -> int:
    """CTRF counts in milliseconds; ATF counts in seconds. Timestamps are epoch either way."""
    return int(round(float(seconds or 0.0) * 1000))
