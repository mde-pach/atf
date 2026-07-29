"""Whether a feature file is well-formed — the shape of it, never the words in it.

This used to check the *vocabulary*: a spec line naming a field, a status code, a path, a flag or a
selector was reported as the layer below leaking into the layer above. That rule is real, and it is
the reason the [phrasebook](phrasebook.py) exists. It is also not checkable, and shipping it as a
check was a mistake worth writing down rather than quietly reversing.

The reason is that it inferred **meaning** from **syntax**. A quoted `/products/42` is a route
leaking out of an adapter in one suite and the domain's own value in another — a redirect target, a
CMS slug, a router rule. `503` is an implementation detail here and the entire subject matter of a
monitoring product. There is no amount of tuning that separates the two, because the difference is
what the system under test *is*, and a linter cannot know that. What such a rule produces is false
positives on correct specs, one waiver comment per line, and a check that means nothing.

So what is left is what a machine can actually decide: **is this file the thing it claims to be?**
Every rule below is a fact about the file that is wrong in every domain — a step above the first
scenario, an outline with no examples, a row with the wrong number of cells, two scenarios that
generate one test name. Nothing here has an opinion about what a suite is testing.

**No waivers, and there is nothing to waive.** The old rules needed them because they were
sometimes wrong. These are not sometimes wrong: a `Scenario Outline:` with no `Examples:` never
runs, whoever wrote it and whatever they meant. A rule that needs an escape hatch is a rule that
should not have been mechanical in the first place, which is the whole lesson here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# The keywords, and what each one starts. Read as text rather than through a Gherkin library
# because `atf lint` has to work in a checkout with nothing configured — the same seam
# `atf docs` holds.
_STEP_RE = re.compile(r"^\s*(?P<keyword>Given|When|Then|And|But|\*)\s+(?P<text>\S.*)$")
_FEATURE_RE = re.compile(r"^\s*Feature:(?P<title>.*)$")
_RULE_RE = re.compile(r"^\s*Rule:(?P<title>.*)$")
_SCENARIO_RE = re.compile(r"^\s*(?P<keyword>Scenario Outline|Scenario Template|Scenario|Example):(?P<title>.*)$")
_BACKGROUND_RE = re.compile(r"^\s*Background:")
_EXAMPLES_RE = re.compile(r"^\s*(Examples|Scenarios):")
_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
# A cell ends at the next pipe that is not escaped. Gherkin writes a literal pipe inside a cell as
# `\|`, and this suite's own features are full of them — they carry whole feature files in a cell.
_CELL_RE = re.compile(r"(?<!\\)\|")

# `<name>` in a step, which an Examples column has to supply.
_PLACEHOLDER_RE = re.compile(r"<([^<>]+)>")

# A keyword that continues the step above it, so there has to be one.
_CONTINUATIONS = frozenset({"And", "But", "*"})

_OUTLINES = frozenset({"Scenario Outline", "Scenario Template"})


@dataclass(frozen=True)
class Rule:
    """One way a feature file can be malformed, and what to do about it."""

    name: str
    means: str
    fix: str


RULES: tuple[Rule, ...] = (
    Rule(
        "no-feature",
        "this file declares no `Feature:`",
        "add one — a `.feature` with no feature in it is collected and contributes nothing",
    ),
    Rule(
        "two-features",
        "a second `Feature:` in one file",
        "split it: everything after the first is silently ignored by every Gherkin reader there is",
    ),
    Rule(
        "untitled",
        "a keyword with nothing after the colon",
        "name it — the title is what the cockpit lists, what a run reports and what `-k` matches",
    ),
    Rule(
        "stray-step",
        "a step before any `Scenario:` or `Background:`",
        "put it under one — nothing will run it where it is",
    ),
    Rule(
        "dangling-and",
        "an `And` or a `But` with no step above it to continue",
        "say which keyword it is: `Given`, `When` or `Then`",
    ),
    Rule(
        "empty-scenario",
        "a scenario with no steps",
        "give it steps, or delete it — it passes without asserting anything",
    ),
    Rule(
        "outline-without-examples",
        "a `Scenario Outline:` with no `Examples:` under it",
        "add the table — an outline with no rows runs zero times",
    ),
    Rule(
        "ragged-table",
        "a table whose rows do not all have the same number of cells",
        "line the columns up — the short rows lose their last values",
    ),
    Rule(
        "unknown-placeholder",
        "a `<placeholder>` no `Examples:` column supplies",
        "add the column, or correct the spelling — it reaches the step with its angle brackets on",
    ),
    Rule(
        "duplicate-scenario",
        "two scenarios in one feature with the same title",
        "rename one — they generate a single test name and only one of them runs",
    ),
)

_BY_NAME = {rule.name: rule for rule in RULES}


def rule(name: str) -> Rule | None:
    return _BY_NAME.get(name)


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the shape of a feature file."""

    path: Path
    line: int
    rule: str
    found: str = ""

    @property
    def message(self) -> str:
        broken = _BY_NAME[self.rule]
        found = f" ({self.found})" if self.found else ""
        return f"{self.path}:{self.line}: {self.rule}: {broken.means}{found}. {broken.fix.capitalize()}."


# ---- reading one file --------------------------------------------------------


@dataclass
class _Scenario:
    """One scenario as the reader walks it, and what has to be true by the time it ends."""

    line: int
    title: str
    outline: bool
    steps: int = 0
    # What the steps reach for, and what the Examples table supplies. A name in the first and not
    # the second arrives at the step with its angle brackets still on it.
    placeholders: set[str] = field(default_factory=set)
    columns: set[str] = field(default_factory=set)
    examples: bool = False


def check_text(text: str, path: Path) -> list[Finding]:
    """Every finding in one feature file, in the order the lines run."""
    found: list[Finding] = []
    features = 0
    titles: Counter[str] = Counter()
    current: _Scenario | None = None
    in_examples = False
    table_width: int | None = None
    steps_since_keyword = 0

    def close(scenario: _Scenario | None) -> None:
        if scenario is None:
            return
        if scenario.steps == 0:
            found.append(Finding(path, scenario.line, "empty-scenario", scenario.title))
        if scenario.outline and not scenario.examples:
            found.append(Finding(path, scenario.line, "outline-without-examples", scenario.title))
        for name in sorted(scenario.placeholders - scenario.columns):
            found.append(Finding(path, scenario.line, "unknown-placeholder", f"<{name}>"))

    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if _ROW_RE.match(line) is not None:
            # A well-formed row opens and closes with a pipe, so the pieces either side are empty.
            cells = [cell.strip() for cell in _CELL_RE.split(line.strip())[1:-1]]
            if table_width is None:
                # The first row of any table sets the width the rest are held to, and the first row
                # of an `Examples:` table is also the names its scenario may reach for.
                table_width = len(cells)
                if in_examples and current is not None:
                    current.columns.update(cells)
            elif len(cells) != table_width:
                found.append(Finding(path, number, "ragged-table", f"{len(cells)} cells, not {table_width}"))
            continue
        table_width = None

        if (feature := _FEATURE_RE.match(line)) is not None:
            features += 1
            if features > 1:
                found.append(Finding(path, number, "two-features", feature.group("title").strip()))
            if not feature.group("title").strip():
                found.append(Finding(path, number, "untitled", "Feature:"))
            close(current)
            current, in_examples, steps_since_keyword = None, False, 0
            continue

        if (grouped := _RULE_RE.match(line)) is not None:
            if not grouped.group("title").strip():
                found.append(Finding(path, number, "untitled", "Rule:"))
            close(current)
            current, in_examples, steps_since_keyword = None, False, 0
            continue

        if _BACKGROUND_RE.match(line) is not None:
            close(current)
            current, in_examples, steps_since_keyword = None, False, 0
            continue

        if (scenario := _SCENARIO_RE.match(line)) is not None:
            close(current)
            title = scenario.group("title").strip()
            if not title:
                found.append(Finding(path, number, "untitled", f"{scenario.group('keyword')}:"))
            else:
                titles[title] += 1
                if titles[title] == 2:
                    found.append(Finding(path, number, "duplicate-scenario", title))
            current = _Scenario(line=number, title=title, outline=scenario.group("keyword") in _OUTLINES)
            in_examples, steps_since_keyword = False, 0
            continue

        if _EXAMPLES_RE.match(line) is not None:
            in_examples = True
            if current is not None:
                current.examples = True
            continue

        if (step := _STEP_RE.match(line)) is not None:
            in_examples = False
            if current is None and steps_since_keyword == 0 and not _under_background(text, number):
                found.append(Finding(path, number, "stray-step", step.group("text")[:60]))
            if step.group("keyword") in _CONTINUATIONS and steps_since_keyword == 0:
                found.append(Finding(path, number, "dangling-and", step.group("keyword")))
            steps_since_keyword += 1
            if current is not None:
                current.steps += 1
                current.placeholders.update(_PLACEHOLDER_RE.findall(step.group("text")))
            continue

    close(current)
    if features == 0:
        found.append(Finding(path, 1, "no-feature"))
    return sorted(found, key=lambda one: (one.line, one.rule))


def _under_background(text: str, number: int) -> bool:
    """Whether the step on line `number` sits under a `Background:` rather than nowhere at all.

    A background's steps belong to every scenario in the feature, so they are not stray — and the
    walk above forgets which of the two it is in, because everything else it decides is the same
    for both.
    """
    for line in reversed(text.splitlines()[: number - 1]):
        if _BACKGROUND_RE.match(line):
            return True
        if _SCENARIO_RE.match(line) or _FEATURE_RE.match(line) or _RULE_RE.match(line):
            return False
    return False


def check(specs_dir: Path) -> list[Finding]:
    """Every finding across a suite's features, file by file, in a stable order."""
    findings: list[Finding] = []
    for path in sorted(Path(specs_dir).rglob("*.feature")):
        findings.extend(check_text(path.read_text(encoding="utf-8"), path))
    return findings


def report(findings: list[Finding], specs_dir: Path) -> str:
    """What `atf lint` prints. Silence is not an answer when nothing was checked."""
    if not findings:
        return f"Every feature under {specs_dir} is well formed."
    lines = [finding.message for finding in findings]
    count = len(findings)
    files = len({finding.path for finding in findings})
    lines.append(
        f"\n{count} problem{'' if count == 1 else 's'} in "
        f"{files} file{'' if files == 1 else 's'}. Each is a fact about the file rather than a "
        "matter of taste, so there is nothing to waive — fix it, or the run does something other "
        "than what the file says."
    )
    return "\n".join(lines)
