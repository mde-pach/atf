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
        caught_by="atf/lifetimes.feature::teardown removes a child before the parent it hangs off",
    ),
    Mutation(
        what="something a scenario changes lives for the test",
        module="lives.py",
        find="    if record.ephemeral or (record.name and record.name in mutated):\n        return THE_TEST",
        replace="    if record.ephemeral:\n        return THE_TEST",
        caught_by="atf/lifetimes.feature::something a scenario changes is gone when the test ends",
    ),
    Mutation(
        what="something resolved lives for the run",
        module="lives.py",
        find="    if record.factorised:\n        return THE_RUN",
        replace="    if False:\n        return THE_RUN",
        caught_by="atf/lifetimes.feature::something resolved rather than declared is gone when the run ends",
    ),
    Mutation(
        what="nothing outlives what it depends on",
        module="lives.py",
        find="    spans = [_own(node, written) for node in graph.closure(resource)]",
        replace="    spans = [_own(resource, written)]",
        caught_by="atf/lifetimes.feature::nothing outlives what it depends on, and says which one",
    ),
    Mutation(
        what="an environment ATF does not own is not written to",
        module="commands.py",
        find="        if not reading.ground.mutable:",
        replace="        if False:",
        caught_by="atf/planning.feature::an environment ATF does not own makes nothing",
    ),
    Mutation(
        what="two of a kind in scope",
        module="plugin.py",
        find="            if len(candidates) > 1:",
        replace="            if False:",
        caught_by="atf/refusing.feature::two of a kind in scope is refused before any test body runs",
    ),
    Mutation(
        what="arranging after acting",
        module="steps.py",
        find="        elif sentence.keyword == GIVEN and acted is not None:",
        replace="        elif False:",
        caught_by="atf/refusing.feature::a scenario that arranges after it has acted is refused before anything runs",
    ),
    Mutation(
        what="an Examples table is refused",
        module="feature.py",
        find="        if refused:\n            raise FeatureError(_refusal(refused, f\"{path}:{number}\"))",
        replace="        if False:\n            raise FeatureError(_refusal(refused, f\"{path}:{number}\"))",
        caught_by="atf/refusing.feature::an Examples table is refused, and the phrase that covers it is written out",
    ),
    Mutation(
        what="a field the class never declared",
        module="declare.py",
        find="    if unknown:",
        replace="    if False:",
        caught_by="atf/refusing.feature::a field the class never declared is refused where it is written",
    ),
    Mutation(
        what="a sentence nobody taught",
        module="steps.py",
        find="        if step is None:\n            raise StepError(undefined(self.keyword, self.text))",
        replace="        if step is None:\n            return self",
        caught_by="atf/refusing.feature::a sentence nobody taught names the nearest ones ATF does know",
    ),
    Mutation(
        what="quoting carries the type",
        module="literals.py",
        find="    return False\n\n\ndef _mismatch",
        replace="    return str(actual) == str(wanted)\n\n\ndef _mismatch",
        caught_by="atf/refusing.feature::a number compared with quoted text says which two words fix it",
    ),
    Mutation(
        what="a failure prints the chain",
        module="plugin.py",
        find="            if drawn:\n                out += [\"\", *drawn]",
        replace="            if False:\n                out += [\"\", *drawn]",
        caught_by="atf/refusing.feature::a failure prints the chain that put the thing under it there",
    ),
    Mutation(
        what="every failure names the command that investigates it",
        module="plugin.py",
        find="        out += [\"\", f'  → atf enter \"{self.scenario.name}\"']",
        replace="        out += [\"\"]",
        caught_by="atf/refusing.feature::every failure ends with the command that investigates it, by name",
    ),
    Mutation(
        what="drift is reported against the declaration",
        module="reconcile.py",
        find="    return {**changed, **parent_changes(resource, found)}",
        replace="    return parent_changes(resource, found)",
        caught_by="atf/planning.feature::drift is reported against the declaration",
    ),
    Mutation(
        what="reconciliation writes the declared value back",
        module="reconcile.py",
        find="            record=_apply(ground, resource, found, changes),",
        replace="            record=found,",
        caught_by="atf/planning.feature::applying again writes the declared value back",
    ),
    Mutation(
        what="a thing the environment owns is not made",
        module="reconcile.py",
        find='    if ground.owner_of(resource) == "them":\n        return Reconciliation(',
        replace='    if False:\n        return Reconciliation(',
        caught_by="atf/planning.feature::a thing the environment owns is named, not made",
    ),
    Mutation(
        what="the python tests are counted",
        module="plan.py",
        find='        out.append(f"  {plan.python_tests} python tests using atf resources        ← not in the spec")',
        replace='        pass',
        caught_by="atf/planning.feature::the python tests are counted, next to the thing they are a hole in",
    ),
    Mutation(
        what="lint gates",
        module="commands.py",
        find="        code=OK if built.sound else FAILED,",
        replace="        code=OK,",
        caught_by="atf/planning.feature::a suite with something wrong in it gates, and says every fault at once",
    ),
    Mutation(
        what="a shard index outside the run",
        module="entry.py",
        find="    if not 1 <= one <= many:",
        replace="    if False:",
        caught_by="atf/scheduling.feature::a shard index outside the run never starts",
    ),
    Mutation(
        what="a shuffled run records its seed",
        module="entry.py",
        find='        lines[0] += f"   seed {selection.seed}"',
        replace="        pass",
        caught_by="atf/scheduling.feature::a shuffled run records the seed it ran in",
    ),
    Mutation(
        what="a run told not to make anything",
        module="runtime.py",
        find="        if no_make():\n            return self._require_present(resource)",
        replace="        if False:\n            return self._require_present(resource)",
        caught_by="atf/the-command.feature::a run told not to make anything fails on what is missing",
    ),
    Mutation(
        what="failed reselects what failed",
        module="plugin.py",
        find="    if SELECTION.failed and item.nodeid not in SELECTION.failed_ids:",
        replace="    if False:",
        caught_by="atf/the-command.feature::failed reselects what failed, and nothing once it passes",
    ),
    Mutation(
        what="init refuses to overwrite",
        module="scaffold.py",
        find="    if manifest.exists() and not force:",
        replace="    if False:",
        caught_by="atf/the-command.feature::init refuses to overwrite what is already there",
    ),
    Mutation(
        what="a report is written",
        module="entry.py",
        find="    written = [str(reports.write(argument, finished)) for argument in flags[\"report\"]]",
        replace="    written = []",
        caught_by="atf/the-record.feature::a report is written where a pipeline will collect it",
    ),
    Mutation(
        what="a format the suite taught",
        module="reports.py",
        find="    known = REGISTRY.get(name)",
        replace="    known = REGISTRY.get(\"ctrf\")",
        caught_by="atf/the-record.feature::a format the suite taught is a format --report accepts",
    ),
    Mutation(
        what="a claim is drafted into a scenario that promises none",
        module="accept.py",
        find="    if not claims:\n        return 0",
        replace="    return 0\n    if not claims:\n        return 0",
        caught_by="atf/the-vocabulary.feature::"
        "a scenario that promises nothing has its claims drafted back into it",
    ),
    Mutation(
        what="a phrase stands for the sentences under it",
        module="phrases.py",
        find="        hit = matching(phrases, line.text)",
        replace="        hit = None",
        caught_by="atf/the-vocabulary.feature::a phrase stands for the sentences under it, and phrases nest",
    ),
    Mutation(
        what="the contract every system holds",
        module="conformance.py",
        find="            for one in verify(ground, example):",
        replace="            for one in []:",
        caught_by="atf/the-vocabulary.feature::"
        "the contract every system holds is a feature file, run like everything else",
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
