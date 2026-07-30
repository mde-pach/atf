"""How `atf` says things: the table, the tally, and the stderr-and-exit-2 convention."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence

from .engine.status import BLOCKED, CREATED, REFERENCE, ProvisionResult

# What `main` returns when a command refuses: a suite that is wrong, not a suite that failed.
REFUSED = 2

# The provisioning actions in the words a person reads, with a failure counted as failed whatever
# it was attempting.
FAILED, CREATED_SAID, PRESENT_SAID, FOUND, BLOCKED_SAID = (
    "failed",
    "created",
    "already present",
    "found",
    "blocked",
)


def table(rows: Iterable[Sequence[str]], indent: str = "  ") -> None:
    """Print rows with every column as wide as its widest cell, the last one ragged."""
    kept = [[str(cell) for cell in row] for row in rows]
    if not kept:
        return
    widths = [max(len(row[column]) for row in kept if column < len(row)) for column in range(len(kept[0]))]
    for row in kept:
        cells = [cell.ljust(widths[column]) if column < len(row) - 1 else cell for column, cell in enumerate(row)]
        print(indent + "  ".join(cells).rstrip())


def tally(results: list[ProvisionResult]) -> str:
    """What a provisioning pass did, counted by what it means to a person."""
    counts = dict.fromkeys((CREATED_SAID, PRESENT_SAID, FOUND, FAILED, BLOCKED_SAID), 0)
    for result in results:
        if not result.ok:
            counts[BLOCKED_SAID if result.action == BLOCKED else FAILED] += 1
        elif result.action == CREATED:
            counts[CREATED_SAID] += 1
        elif result.action == REFERENCE:
            counts[FOUND] += 1
        else:
            counts[PRESENT_SAID] += 1

    parts = [f"{count} {label}" for label, count in counts.items() if count]
    return ", ".join(parts) or "nothing to do"


def problem(*said: str) -> int:
    """Say why a command will not do what it was asked, on stderr. Returns the exit code."""
    print("\n".join(said), file=sys.stderr)
    return REFUSED
