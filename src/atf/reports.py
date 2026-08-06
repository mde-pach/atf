"""A run written out in a named format. ATF holds a registry; each name owns a writer.

```sh
atf run --report ctrf:out.json --report ctrf:artifacts/nightly.json
```

The argument is `format:destination`. The flag repeats; each occurrence writes one file.

**`ctrf` is the only format ATF ships**, and it is registered by name like any other, so a team may
replace it. JUnit XML, Allure and anything else a pipeline reads are formats a team registers. A page
showing `--report junit:…` is showing a registered format, not a shipped one.

The cost of a registry is that a format is a public surface: a report ATF writes today must keep its
shape tomorrow. ATF pins that promise to CTRF's own specification rather than to a format of its own
naming.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .record import Outcome, Run, TestOutcome, Where

Writer = Callable[[Run, Path], None]
Reader = Callable[[Path], Run]


class ReportError(Exception):
    """Raised when a format is not registered, or a file is not in the format it was read as."""


@dataclass(frozen=True)
class Format:
    """One registered format: what writes it, and what reads it back when it can be read back."""

    name: str
    write: Writer
    read: Reader | None = None


REGISTRY: dict[str, Format] = {}


def report(name: str, *, read: Reader | None = None) -> Callable[[Writer], Writer]:
    """Register a report format."""

    def decorate(write: Writer) -> Writer:
        REGISTRY[name] = Format(name=name, write=write, read=read)
        return write

    return decorate


def formats() -> list[str]:
    return sorted(REGISTRY)


def parse(argument: str) -> tuple[Format, Path]:
    """`format:destination` — the shape `--report` takes."""
    name, separator, destination = argument.partition(":")
    if not separator or not destination:
        raise ReportError(f"--report takes format:path, and it was given {argument!r}")
    known = REGISTRY.get(name)
    if known is None:
        raise ReportError(f"no report format called {name!r} (registered: {', '.join(formats())})")
    return known, Path(destination)


def write(argument: str, run: Run) -> Path:
    known, destination = parse(argument)
    destination.parent.mkdir(parents=True, exist_ok=True)
    known.write(run, destination)
    return destination


def read(path: Path, name: str = "ctrf") -> Run:
    known = REGISTRY.get(name)
    if known is None or known.read is None:
        raise ReportError(f"the {name!r} format cannot be read back")
    return known.read(path)


# --- CTRF --------------------------------------------------------------------------------------
#
# The Common Test Report Format. One format both ways is what makes a CI run and a local run
# interchangeable in history.

_STATUS = {Outcome.PASSED: "passed", Outcome.FAILED: "failed", Outcome.SKIPPED: "skipped"}
_BACK = {"passed": Outcome.PASSED, "failed": Outcome.FAILED, "skipped": Outcome.SKIPPED}


def _epoch(when: str) -> int:
    try:
        return int(datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").timestamp())
    except ValueError:
        return 0


def _read_ctrf(path: Path) -> Run:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"{path}: not readable as CTRF: {exc}") from exc
    results = raw.get("results") if isinstance(raw, dict) else None
    if not isinstance(results, dict) or not isinstance(results.get("tests"), list):
        raise ReportError(f"{path}: no results.tests, so this is not a CTRF report")

    outcomes: list[TestOutcome] = []
    for entry in results["tests"]:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ReportError(f"{path}: a test entry with no name")
        word = _BACK.get(str(entry.get("status", "")), Outcome.FAILED)
        message = str(entry.get("message", ""))
        outcomes.append(
            TestOutcome(
                test=str(entry["name"]),
                outcome=word,
                duration_ms=int(entry.get("duration", 0) or 0),
                failed_at=Where(
                    file=str(entry.get("filePath", "")),
                    line=int(entry.get("line", 0) or 0),
                    message=message,
                )
                if word is Outcome.FAILED
                else None,
            )
        )
    return Run(id="", environment="", started="", outcomes=outcomes)


@report("ctrf", read=_read_ctrf)
def _write_ctrf(run: Run, destination: Path) -> None:
    counts = run.counts
    document = {
        "results": {
            "tool": {"name": "atf"},
            "summary": {
                "tests": len(run.outcomes),
                "passed": counts[Outcome.PASSED],
                "failed": counts[Outcome.FAILED],
                "pending": 0,
                "skipped": counts[Outcome.SKIPPED],
                "other": 0,
                "start": _epoch(run.started),
                "stop": _epoch(run.finished),
            },
            "tests": [
                {
                    "name": outcome.test,
                    "status": _STATUS[outcome.outcome],
                    "duration": outcome.duration_ms,
                    **(
                        {
                            "message": outcome.failed_at.message,
                            "filePath": outcome.failed_at.file,
                            "line": outcome.failed_at.line,
                        }
                        if outcome.failed_at is not None
                        else {}
                    ),
                }
                for outcome in run.outcomes
            ],
        }
    }
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
