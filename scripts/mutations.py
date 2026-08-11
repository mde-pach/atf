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

# pytest's own exit codes. A scenario here shells out to `atf run`, whose whole output is captured
# into the result the scenario claims on and printed again when it goes red — so the outer verdict
# is read from the exit code, and never by looking for a summary line in the output.
NO_TESTS_COLLECTED = 5
USAGE_ERROR = 4


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
        find='reconcile.teardown(state.ground, reconcile.scoped(state.made, "function"), undone)',
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
        what="--absent-only",
        module="commands.py",
        find="    shown = [o for o in report.outcomes if not absent_only or o.state is not State.PRESENT]",
        replace="    shown = list(report.outcomes)",
        caught_by="tests/specs/reading.feature::status can be asked for only what is not there",
    ),
    Mutation(
        what="the environment in a link",
        module="editor.py",
        find='    return f"{href}{\'&\' if \'?\' in href else \'?\'}env={urllib.parse.quote(HERE[0])}"',
        replace="    return href",
        caught_by="tests/specs/the-editor.feature::"
        "the environment survives moving to another view",
    ),
    Mutation(
        what="the composer re-answering",
        module="editor.py",
        find="    offered = editor.composer(written)",
        replace="    offered = editor.composer([])",
        caught_by="tests/specs/the-editor.feature::"
        "taking a step in the composer re-answers what can be said next",
    ),
    Mutation(
        what="a pytest function in the tests list",
        module="core.py",
        find='        out.append(entry(runs.identity(path, name, root), name, "function", [], reach))',
        replace="        pass",
        caught_by="tests/specs/the-editor.feature::"
        "a scenario and a pytest function are listed the same way",
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
        what="arranging after acting",
        module="steps.py",
        find="        elif sentence.keyword == GIVEN and acted is not None:",
        replace="        elif False:",
        caught_by="tests/specs/refusing.feature::"
        "a scenario that arranges after it has acted is refused before anything runs",
    ),
    Mutation(
        what="drift reporting a record that moved",
        module="commands.py",
        find="        if outcome.state is State.PRESENT and outcome.changes",
        replace="        if False",
        caught_by="tests/specs/reconciling.feature::"
        "a record changed by hand is reported against its declaration",
    ),
    Mutation(
        what="drift gating when asked",
        module="commands.py",
        find="        code=FAILED if (strict and moved) else OK,",
        replace="        code=OK,",
        caught_by="tests/specs/reconciling.feature::drift gates only when it is asked to",
    ),
    Mutation(
        what="the contract standing in for the resource it is asked about",
        module="conformance.py",
        find='        patch[field] = f"{value}-{MARK}"',
        replace="        patch[field] = value",
        caught_by="tests/specs/reconciling.feature::"
        "what the contract wrote is gone, and the resource it stood in for is untouched",
    ),
    Mutation(
        what="a shard index outside the run",
        module="entry.py",
        find="    if not 1 <= one <= many:",
        replace="    if False:",
        caught_by="tests/specs/scheduling.feature::a shard index outside the run never starts",
    ),
    Mutation(
        what="the seed a shuffled run recorded",
        module="entry.py",
        find='        lines[0] += f"   seed {selection.seed}"',
        replace="        pass",
        caught_by="tests/specs/scheduling.feature::a shuffled run records the seed it ran in",
    ),
    Mutation(
        what="naming what forced a test to run alone",
        module="footprint.py",
        find="        return f'\"{self.opaque[0]}\" has an effect nothing declares'",
        replace='        return "it runs alone"',
        caught_by="tests/specs/scheduling.feature::"
        "a sentence whose effect nothing declares is named as what forced a test to go alone",
    ),
    Mutation(
        what="adopt naming a system that cannot say what it holds",
        module="adopt.py",
        find="        raise AdoptError(",
        replace='        return "", []\n        raise AdoptError(',
        caught_by="tests/specs/adopting.feature::"
        "a system that cannot say what it holds is named, and nothing is written",
    ),
    Mutation(
        what="adopt refusing to overwrite a declaration",
        module="commands.py",
        find="    return any(isinstance(node, ast.ClassDef) for node in ast.walk(tree))",
        replace="    return False",
        caught_by="tests/specs/adopting.feature::"
        "adopt refuses to overwrite a file that already declares something",
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
    named_nothing = result.returncode == NO_TESTS_COLLECTED or (
        result.returncode == USAGE_ERROR and "not found" in result.stdout + result.stderr
    )
    if named_nothing:
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
