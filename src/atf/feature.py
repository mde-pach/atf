"""Reading a `.feature` file into scenarios and sentences."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .steps import CONTINUATIONS, KEYWORDS

TAG = re.compile(r"@([\w-]+)")
OUTLINE_HOLE = re.compile(r"<([^>]+)>")

SCENARIO_WORDS = ("Scenario Outline:", "Scenario Template:", "Scenario:", "Example:")


class FeatureError(Exception):
    """Raised when a feature file cannot be read as one. Always names the file and the line."""


@dataclass
class Line:
    """One sentence, with its keyword already resolved through any `And`.

    `keyword` is what runs the sentence; `written` is the word the author typed, which is what
    `atf docs` and the editor read back.
    """

    keyword: str
    text: str
    number: int
    written: str = ""

    @property
    def said(self) -> str:
        return self.written or self.keyword.title()

    def filled(self, values: dict[str, str]) -> Line:
        """This sentence with its `<placeholders>` replaced by one row of an `Examples` table."""
        text = OUTLINE_HOLE.sub(lambda hole: values.get(hole.group(1), hole.group(0)), self.text)
        return Line(keyword=self.keyword, text=text, number=self.number, written=self.written)


@dataclass
class Scenario:
    """One scenario, which is also the shape a phrase has."""

    name: str
    lines: list[Line] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    path: Path | None = None
    number: int = 0
    rule: str = ""
    feature: str = ""

    @property
    def is_phrase(self) -> bool:
        return "phrase" in self.tags

    @property
    def where(self) -> str:
        return f"{self.path}:{self.number}" if self.path else self.name

    def filled(self, values: dict[str, str]) -> Scenario:
        name = OUTLINE_HOLE.sub(lambda hole: values.get(hole.group(1), hole.group(0)), self.name)
        return Scenario(
            name=name,
            lines=[line.filled(values) for line in self.lines],
            tags=list(self.tags),
            path=self.path,
            number=self.number,
            rule=self.rule,
            feature=self.feature,
        )


@dataclass
class Feature:
    """One file: its scenarios, and the background every one of them starts with."""

    name: str = ""
    path: Path | None = None
    background: list[Line] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def read(path: Path) -> Feature:
    """Parse one feature file, or say which line stopped it."""
    feature = Feature(path=path)
    scenario: Scenario | None = None
    rule = ""
    tags: list[str] = []
    keyword = ""
    in_background = False
    outline_of: Scenario | None = None
    header: list[str] = []

    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("@"):
            tags += TAG.findall(line)
            continue

        if line.startswith("Feature:"):
            feature.name = line[len("Feature:") :].strip()
            feature.tags, tags = tags, []
            scenario, outline_of, in_background, keyword = None, None, False, ""
            continue

        if line.startswith("Rule:"):
            rule = line[len("Rule:") :].strip()
            scenario, outline_of, in_background, keyword = None, None, False, ""
            continue

        if line.startswith("Background:"):
            in_background, scenario, outline_of, keyword = True, None, None, ""
            continue

        started = next((word for word in SCENARIO_WORDS if line.startswith(word)), "")
        if started:
            scenario = Scenario(
                name=line[len(started) :].strip(),
                tags=tags,
                path=path,
                number=number,
                rule=rule,
                feature=feature.name,
            )
            # A phrase is vocabulary, not a test, so it does not inherit the background a test gets.
            if not scenario.is_phrase:
                scenario.lines.extend(
                    Line(keyword=step.keyword, text=step.text, number=step.number, written=step.written)
                    for step in feature.background
                )
            # An outline is a template, not a test. It is held here and one scenario per `Examples`
            # row is appended instead, so nothing collects a scenario with `<holes>` still in it.
            outline_of = scenario if started.startswith(("Scenario Outline", "Scenario Template")) else None
            if outline_of is None:
                feature.scenarios.append(scenario)
            tags, in_background, keyword, header = [], False, "", []
            continue

        if line.startswith(("Examples:", "Scenarios:")):
            if outline_of is None:
                raise FeatureError(f"{path}:{number}: Examples with no Scenario Outline above it")
            header = []
            continue

        if line.startswith("|"):
            row = [cell.strip() for cell in line.strip("|").split("|")]
            if outline_of is None:
                raise FeatureError(
                    f"{path}:{number}: a table, and the only table in the language is Examples "
                    f"under a Scenario Outline. Write it as several sentences."
                )
            if not header:
                header = row
                continue
            feature.scenarios.append(outline_of.filled(dict(zip(header, row, strict=False))))
            continue

        word, _, rest = line.partition(" ")
        lowered = word.lower()
        if lowered in KEYWORDS:
            keyword = lowered
        elif lowered in CONTINUATIONS:
            if not keyword:
                raise FeatureError(f"{path}:{number}: {word!r} continues a keyword, and none came before it")
        else:
            raise FeatureError(
                f"{path}:{number}: {line!r} starts with {word!r}; a sentence starts with "
                f"Given, When, Then, And or But"
            )

        sentence = Line(keyword=keyword, text=rest.strip(), number=number, written=word)
        if in_background:
            feature.background.append(sentence)
        elif scenario is not None:
            scenario.lines.append(sentence)
        else:
            raise FeatureError(f"{path}:{number}: a sentence outside any scenario")

    return feature


def read_all(specs: Path) -> list[Feature]:
    """Every feature under the specs directory, in a stable order."""
    if not specs.is_dir():
        return []
    return [read(path) for path in sorted(specs.rglob("*.feature"))]
