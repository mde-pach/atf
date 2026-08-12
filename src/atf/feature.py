"""Reading a `.feature` file into scenarios, phrases and sentences, and refusing three shapes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .steps import CONTINUATIONS, KEYWORDS

TAG = re.compile(r"@([\w-]+)")

SCENARIO_WORD = "Scenario:"
PHRASE_WORD = "Phrase:"
#: Written by somebody arriving from Cucumber. Each is refused by name, with what to write instead.
REFUSED = ("Scenario Outline:", "Scenario Template:", "Examples:", "Scenarios:", "Background:", "Example:")


class FeatureError(Exception):
    """Raised when a feature file cannot be read as one. Always names the file and the line."""


@dataclass
class Line:
    """One sentence, with its keyword already resolved through any `And`.

    `keyword` is what runs the sentence; `written` is the word the author typed, which is what the
    editor and the rendered spec read back.
    """

    keyword: str
    text: str
    number: int
    written: str = ""

    @property
    def said(self) -> str:
        return self.written or self.keyword.title()


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
    #: Whether this block is vocabulary. Set by the word `Phrase:`, and by nothing else.
    is_phrase: bool = False
    #: Free text between the title and the first sentence. Read by anything that renders a
    #: scenario, and never by anything that runs one.
    description: str = ""

    @property
    def where(self) -> str:
        return f"{self.path}:{self.number}" if self.path else self.name


@dataclass
class Feature:
    """One file: the scenarios in it, and the phrases it teaches."""

    name: str = ""
    path: Path | None = None
    scenarios: list[Scenario] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    #: Free text between the title and the first Scenario or Phrase. What a feature file is *for*
    #: is prose, and refusing to let somebody write it would be refusing the point of the format.
    description: str = ""

    @property
    def phrases(self) -> list[Scenario]:
        return [one for one in self.scenarios if one.is_phrase]

    @property
    def tests(self) -> list[Scenario]:
        return [one for one in self.scenarios if not one.is_phrase]


def _refusal(word: str, where: str) -> str:
    """Why a Gherkin feature is not here, and the one concept that covers it."""
    if word == "Background:":
        return (
            f"{where}: Background is not in this language.\n"
            f"  It degrades the graph — every scenario in the file drags that resource's whole\n"
            f"  closure whether it wanted it or not — and every rendering of a scenario loses it.\n"
            f"  Write the setup as a named situation, and say it where it is used:\n"
            f"      Phrase: a busy account\n"
            f'        Given the owner "primary"\n'
            f'        And the list "groceries"\n'
            f"\n"
            f"      Scenario: the index shows every list\n"
            f"        Given a busy account"
        )
    return (
        f"{where}: {word} is not in this language.\n"
        f"  A phrase runs one scenario over several inputs, and each case reads as a sentence\n"
        f"  rather than a cell decoded against a header row three lines up:\n"
        f'      Phrase: rejecting the address "{{address}}"\n'
        f'        When I add the address "{{address}}"\n'
        f"        Then it failed\n"
        f"\n"
        f"      Scenario: badly formed addresses are refused\n"
        f'        Given rejecting the address ""\n'
        f'        And rejecting the address "not-an-email"'
    )


def read(path: Path) -> Feature:
    """Parse one feature file, or say which line stopped it."""
    feature = Feature(path=path)
    scenario: Scenario | None = None
    rule = ""
    tags: list[str] = []
    keyword = ""
    described: list[str] = []

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
            scenario, keyword, described = None, "", []
            continue

        if line.startswith("Rule:"):
            rule = line[len("Rule:") :].strip()
            scenario, keyword, described = None, "", []
            continue

        refused = next((word for word in REFUSED if line.startswith(word)), "")
        if refused:
            raise FeatureError(_refusal(refused, f"{path}:{number}"))

        if line.startswith("|"):
            raise FeatureError(
                f"{path}:{number}: a table. There are no tables in this language — "
                f"write each case as a sentence, under a phrase."
            )

        started = next((word for word in (SCENARIO_WORD, PHRASE_WORD) if line.startswith(word)), "")
        if started:
            scenario = Scenario(
                name=line[len(started) :].strip(),
                tags=tags,
                path=path,
                number=number,
                rule=rule,
                feature=feature.name,
                is_phrase=started == PHRASE_WORD,
            )
            feature.scenarios.append(scenario)
            if described and not feature.description:
                feature.description = "\n".join(described)
            tags, keyword, described = [], "", []
            continue

        word, _, rest = line.partition(" ")
        lowered = word.lower()
        if lowered in KEYWORDS:
            keyword = lowered
        elif lowered in CONTINUATIONS:
            if not keyword:
                raise FeatureError(f"{path}:{number}: {word!r} continues a keyword, and none came before it")
        elif not keyword:
            # Free text, before anything has been said. Gherkin calls it a description, and what a
            # feature file is *for* is prose — refusing it would be refusing the point of the format.
            described.append(line)
            if scenario is not None:
                scenario.description = "\n".join(described)
            continue
        else:
            raise FeatureError(
                f"{path}:{number}: {line!r} starts with {word!r}; a sentence starts with "
                f"Given, When, Then, And or But"
            )

        sentence = Line(keyword=keyword, text=rest.strip(), number=number, written=word)
        if scenario is None:
            raise FeatureError(f"{path}:{number}: a sentence outside any Scenario or Phrase")
        scenario.lines.append(sentence)

    return feature


def read_all(specs: Path) -> list[Feature]:
    """Every feature in the suite, in a stable order."""
    if not specs.is_dir():
        return []
    return [read(path) for path in sorted(specs.rglob("*.feature"))]
