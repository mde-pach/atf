"""One rule, made mechanical: a spec line may not contain technical vocabulary.

The layers only hold if something checks them. A spec is what a product owner or a tester reads,
and the moment a field name, a selector, a status code, a path or a CLI flag appears in one, the
layer below has leaked into it — the reader now needs to know the shape of a record or the routes
of an API to understand what the test claims. That is exactly the trade the
[phrasebook](phrasebook.py) exists to undo, and it is checkable by machine, so it ships as a check
rather than as advice.

**What counts as a spec line is a step.** Not the narrative, not a comment, and not a data table:
prose is where an author explains, and explaining is allowed to be specific.

A **table is a deliberate exception**, not an oversight. `Then the task "milk" is:` followed by a
table of fields is the whole-shape claim, and the rule exists to stop technical detail being
*embedded in a sentence a reader has to parse* — `field "owner_id"` reads as English and is not.
A table reads as data, is visually separate from the prose, and replaces the field-by-field
assertions the rule is really aimed at. Flagging it would push suites back to one claim per field,
which is the opposite of what the rule is for. A step is the claim itself.

**Every finding names a rule, and every rule can be waived.** A suite mid-migration has lines it
already knows about, and a check that lands permanently red is a check somebody turns off. A
comment above the line waives it:

```gherkin
# atf-lint: ignore field-claim — until this feature has its phrases
Then the result field "exit_code" is "0"
```

The same comment before `Feature:` waives that rule for the whole file. A waiver is a decision
someone wrote down, which is the point: the rule is still there, and so is the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# What a step line starts with. `*` is Gherkin's "same as above", and a step is a step.
_STEP_RE = re.compile(r"^\s*(Given|When|Then|And|But|\*)\s+(?P<text>\S.*)$")
_FEATURE_RE = re.compile(r"^\s*Feature:")

# `# atf-lint: ignore <rule>[, <rule>] [— anything else]`
_WAIVER_RE = re.compile(r"^\s*#\s*atf-lint:\s*ignore\s+(?P<rules>[a-z0-9-]+(?:\s*,\s*[a-z0-9-]+)*)")

# Everything between double quotes — the only place a spec puts a value.
_QUOTED_RE = re.compile(r'"([^"]*)"')

_ALL = "all"


@dataclass(frozen=True)
class Rule:
    """One kind of technical vocabulary, and why a spec is worse for having it."""

    name: str
    forbids: str
    instead: str


RULES: tuple[Rule, ...] = (
    Rule(
        "field-claim",
        "naming a field of a record",
        "a phrase — `the list \"groceries\" belongs to \"primary\"` rather than its `owner_id`",
    ),
    Rule(
        "status-code",
        "a status code",
        "what the code means here — `it is refused`, `it is not found`",
    ),
    Rule(
        "path",
        "a URL or a path into a system",
        "the thing at the end of it, named the way the catalog names it",
    ),
    Rule(
        "cli-flag",
        "a command-line flag",
        "a phrase for what the flag makes the command do",
    ),
    Rule(
        "selector",
        "a CSS or XPath selector",
        "the control's role and its accessible name — `the button \"Save\"`",
    ),
)

_BY_NAME = {rule.name: rule for rule in RULES}


def rule(name: str) -> Rule | None:
    return _BY_NAME.get(name)


@dataclass(frozen=True)
class Finding:
    """One spec line that says something only the layer below should have to know."""

    path: Path
    line: int
    rule: str
    text: str
    found: str

    @property
    def message(self) -> str:
        broken = _BY_NAME[self.rule]
        return (
            f"{self.path}:{self.line}: {self.rule}: {broken.forbids} ({self.found}). "
            f"Say {broken.instead}."
        )


# ---- the checks themselves --------------------------------------------------
#
# Each answers "what in this line is technical?" and returns the offending fragment, so the message
# can quote it rather than making a reader hunt for what was meant.


def _field_claim(line: str, quoted: list[str]) -> str:
    return 'field "…"' if ' field "' in line else ""


def _status_code(line: str, quoted: list[str]) -> str:
    for value in quoted:
        text = value.strip()
        if text.isdigit() and len(text) == 3 and 100 <= int(text) <= 599:
            return text
    return ""


def _path(line: str, quoted: list[str]) -> str:
    for value in quoted:
        if "://" in value:
            return value
        # A leading slash, and something after it: `"/tasks"` is a route, `"/"` is a separator
        # somebody wrote in prose.
        if value.startswith("/") and len(value) > 1:
            return value
    return ""


def _cli_flag(line: str, quoted: list[str]) -> str:
    for value in quoted:
        for word in value.split():
            if word.startswith("--") and len(word) > 2:
                return word
    return ""


_SELECTOR_SIGNS = ("[role=", "[data-", "::", ":nth-", ":not(", " > ")


def _selector(line: str, quoted: list[str]) -> str:
    for value in quoted:
        if value.startswith("#") or value.startswith("."):
            return value
        for sign in _SELECTOR_SIGNS:
            if sign in value:
                return value
    return ""


_CHECKS = {
    "field-claim": _field_claim,
    "status-code": _status_code,
    "path": _path,
    "cli-flag": _cli_flag,
    "selector": _selector,
}


# ---- running them ------------------------------------------------------------


def check_text(text: str, path: Path) -> list[Finding]:
    """Every finding in one feature file's text, in the order the lines run."""
    findings: list[Finding] = []
    waived_here: set[str] = set()
    file_wide: set[str] = set()
    seen_feature = False

    for number, line in enumerate(text.splitlines(), start=1):
        waived = _waived(line)
        if waived is not None:
            # Before `Feature:` a waiver is about the file; after it, about the next line.
            (file_wide if not seen_feature else waived_here).update(waived)
            continue
        if _FEATURE_RE.match(line):
            seen_feature = True
            continue

        step = _STEP_RE.match(line)
        if step is None:
            # A blank line or a heading does not carry a waiver over to the next step: a waiver
            # sits directly above what it waives, or it is about something a reader cannot see.
            if line.strip():
                waived_here = set()
            continue

        findings.extend(_findings_in(step.group("text"), path, number, file_wide | waived_here))
        waived_here = set()

    return findings


def _findings_in(text: str, path: Path, number: int, waived: set[str]) -> list[Finding]:
    if _ALL in waived:
        return []
    quoted = _QUOTED_RE.findall(text)
    found: list[Finding] = []
    for name, check in _CHECKS.items():
        if name in waived:
            continue
        offending = check(text, quoted)
        if offending:
            found.append(Finding(path=path, line=number, rule=name, text=text, found=offending))
    return found


def _waived(line: str) -> list[str] | None:
    match = _WAIVER_RE.match(line)
    if match is None:
        return None
    named = [name.strip() for name in match.group("rules").split(",") if name.strip()]
    return [name for name in named if name in _BY_NAME or name == _ALL] or [_ALL]


def check(specs_dir: Path) -> list[Finding]:
    """Every finding across a suite's features, file by file, in a stable order."""
    findings: list[Finding] = []
    for path in sorted(Path(specs_dir).rglob("*.feature")):
        findings.extend(check_text(path.read_text(encoding="utf-8"), path))
    return findings


def report(findings: list[Finding], specs_dir: Path) -> str:
    """What `atf lint` prints. Silence is not an answer when nothing was checked."""
    if not findings:
        return f"No technical vocabulary in the specs under {specs_dir}."
    lines = [finding.message for finding in findings]
    count = len(findings)
    files = len({finding.path for finding in findings})
    lines.append(
        f"\n{count} line{'' if count == 1 else 's'} in {files} file{'' if files == 1 else 's'} "
        "say something the layer below should have kept. Write a phrase for it, or waive the rule "
        "above the line with `# atf-lint: ignore <rule>` and say why."
    )
    return "\n".join(lines)
