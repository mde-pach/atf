"""Break ATF in one place, and require the scenario that watches that place to go red.

Every mutation is applied to a copy of `src/`, so a death here leaves the working tree alone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    """One break, and the scenario whose job it is to notice."""

    what: str
    module: str
    find: str
    replace: str
    caught_by: str
    """The scenario, as pytest names it. A title carries spaces, and `-k` cannot hold one."""


MUTATIONS = (
    Mutation(
        what="teardown order",
        module="graph.py",
        find="    return list(reversed(order(nodes)))",
        replace="    return list(order(nodes))",
        caught_by="tests/specs/lifetimes.feature::teardown removes a child before the parent it hangs off",
    ),
    Mutation(
        what="function scope ends with the test",
        module="plugin.py",
        find='reconcile.teardown(state.ground, reconcile.scoped(state.made, "function"))',
        replace="pass",
        caught_by="tests/specs/lifetimes.feature::a resource scoped to one test is gone when the run ends",
    ),
    Mutation(
        what="the mutable gate",
        module="commands.py",
        find="        if not ground.mutable and not dry_run:",
        replace="        if False:",
        caught_by="tests/specs/making-resources.feature::an environment that may not be changed makes nothing",
    ),
    Mutation(
        what="two of a kind in scope",
        module="plugin.py",
        find="            if len(candidates) > 1:",
        replace="            if False:",
        caught_by="tests/specs/refusing.feature::two of a kind in scope is refused before any test body runs",
    ),
    Mutation(
        what="what breaks if this does",
        module="core.py",
        find="        needed_by=[node for node in nodes if id in node.needs],",
        replace="        needed_by=[],",
        caught_by="tests/specs/the-editor.feature::"
        "what breaks if a resource does is on the resource, not in a separate report",
    ),
    Mutation(
        what="lineage laid out to be drawn",
        module="core.py",
        find='        layers=_layers(suite, id, by_id) if here.kind == "resource" else [],',
        replace="        layers=[],",
        caught_by="tests/specs/the-editor.feature::"
        "a node many things stand on is drawn, and the sentence becomes the caption",
    ),
    Mutation(
        what="the negative half of the field family",
        module="claims.py",
        find="    if actual is not MISSING and compare.written_matches(actual, written):",
        replace="    if False:",
        caught_by="tests/specs/refusing.feature::"
        "a claim that does not hold turns the run red and says what it wanted",
    ),
    Mutation(
        what="a check the suite registered",
        module="commands.py",
        find="    for one in CHECKS:",
        replace="    for one in []:",
        caught_by="tests/specs/reading.feature::check exits 1 on its findings, because they are its answer",
    ),
    Mutation(
        what="--absent-only",
        module="commands.py",
        find="    shown = [o for o in report.outcomes if not absent_only or o.state is not State.PRESENT]",
        replace="    shown = list(report.outcomes)",
        caught_by="tests/specs/reading.feature::status can be asked for only what is not there",
    ),
    Mutation(
        what="the report registry",
        module="reports.py",
        find="        REGISTRY[name] = Format(name=name, write=write, read=read)",
        replace="        pass",
        caught_by="tests/specs/the-record.feature::"
        "a format the suite registered is a format --report accepts",
    ),
    Mutation(
        what="a field a declared action writes",
        module="reconcile.py",
        find="    return {field for action in declaration_of(resource).actions.values() for field in action.values}",
        replace="    return set()",
        caught_by="tests/specs/making-resources.feature::"
        "a field a declared action writes is not reverted by the next pass",
    ),
)


def mutate(mutation: Mutation, into: Path) -> Path:
    """Copy the source, apply the mutation to the copy, and answer where the copy is."""
    source = into / "src"
    shutil.copytree(REPO / "src", source)
    path = source / "atf" / mutation.module
    original = path.read_text(encoding="utf-8")
    if mutation.find not in original:
        raise SystemExit(f"{mutation.module}: the mutation target moved — update {Path(__file__).name}")
    path.write_text(original.replace(mutation.find, mutation.replace), encoding="utf-8")
    return source


def run(scenario: str, source: Path) -> subprocess.CompletedProcess[str]:
    """Run one named scenario against one copy of ATF.

    `PYTHONPATH` is inherited by every `atf` the scenarios shell out to, so the mutated copy is the
    one under test all the way down.
    """
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", scenario],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(source)},
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def check(mutation: Mutation) -> str | None:
    """The complaint this mutation earned, or `None` where the suite caught it."""
    with tempfile.TemporaryDirectory() as workspace:
        result = run(mutation.caught_by, mutate(mutation, Path(workspace)))
    if "no tests ran" in result.stdout or "not found" in result.stdout + result.stderr:
        return f"{mutation.caught_by} names no scenario, so nothing was checked"
    if result.returncode == 0:
        return f"the suite stayed green with {mutation.what} broken"
    return None


def main() -> int:
    shutil.rmtree(REPO / ".workspaces", ignore_errors=True)
    failures = 0
    for mutation in MUTATIONS:
        complaint = check(mutation)
        print(f"{'not caught' if complaint else 'caught'}: {mutation.what}" + (f" — {complaint}" if complaint else ""))
        failures += complaint is not None
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
