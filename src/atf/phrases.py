"""`@phrase`: vocabulary written in Gherkin, expanded at collection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .feature import Feature, Line, Scenario
from .patterns import CAPTURE_RE, literal_length, pattern_regex


class PhraseError(Exception):
    """Raised when a phrase cannot be expanded: a cycle, or two phrases with the same wording."""


@dataclass
class Phrase:
    """One phrase: what it reads as, and the sentences it stands for."""

    pattern: str
    lines: list[Line] = field(default_factory=list)
    where: str = ""

    @property
    def holes(self) -> tuple[str, ...]:
        return tuple(CAPTURE_RE.findall(self.pattern))

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(f"^{pattern_regex(self.pattern)}$")

    def match(self, sentence: str) -> dict[str, str] | None:
        """The values this sentence fills the holes with, or `None` where it says a different phrase.

        **A phrase with no holes matches with an empty dict**, and `{}` is falsy — so every caller
        compares against `None`. Reading this as a boolean is how "0 scenarios say it" gets printed
        about a phrase every scenario says.
        """
        found = self.regex.match(sentence.strip())
        return dict(zip(self.holes, found.groups(), strict=False)) if found else None


def collect(features: list[Feature]) -> dict[str, Phrase]:
    """Every `@phrase` in the suite, keyed by its wording. One flat namespace."""
    out: dict[str, Phrase] = {}
    for feature in features:
        for scenario in feature.scenarios:
            if not scenario.is_phrase:
                continue
            if scenario.name in out:
                raise PhraseError(
                    f"two phrases are written {scenario.name!r}: {out[scenario.name].where} and {scenario.where}"
                )
            out[scenario.name] = Phrase(pattern=scenario.name, lines=list(scenario.lines), where=scenario.where)
    return out


def matching(phrases: dict[str, Phrase], sentence: str) -> tuple[Phrase, dict[str, str]] | None:
    """The phrase a sentence says, with its holes filled. The most wording wins, as for a step."""
    hits = [(phrase, values) for phrase in phrases.values() if (values := phrase.match(sentence)) is not None]
    if not hits:
        return None
    return max(hits, key=lambda hit: literal_length(hit[0].pattern))


def expand(scenario: Scenario, phrases: dict[str, Phrase]) -> Scenario:
    """A scenario with every phrase it says replaced by the sentences that phrase stands for.

    A phrase's own sentences may say phrases, so this recurses. A phrase that reaches itself raises
    `PhraseError` with the way round.
    """
    expanded = Scenario(
        name=scenario.name,
        tags=list(scenario.tags),
        path=scenario.path,
        number=scenario.number,
        rule=scenario.rule,
        feature=scenario.feature,
    )
    expanded.lines = _expand_lines(scenario.lines, phrases, ())
    return expanded


def _expand_lines(lines: list[Line], phrases: dict[str, Phrase], trail: tuple[str, ...]) -> list[Line]:
    out: list[Line] = []
    for line in lines:
        hit = matching(phrases, line.text)
        if hit is None:
            out.append(line)
            continue
        phrase, values = hit
        if phrase.pattern in trail:
            way_round = " -> ".join([*trail, phrase.pattern])
            raise PhraseError(f"a phrase cannot say itself: {way_round}")
        inner = [
            Line(keyword=step.keyword, text=_fill(step.text, values), number=line.number, written=step.written)
            for step in phrase.lines
        ]
        out.extend(_expand_lines(inner, phrases, (*trail, phrase.pattern)))
    return out


def _fill(text: str, values: dict[str, str]) -> str:
    return CAPTURE_RE.sub(lambda hole: values.get(hole.group(1), hole.group(0)), text)
