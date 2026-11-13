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


def line_values(template: Line, real: Line) -> dict[str, str] | None:
    """What `real` fills one of a phrase's own lines' holes with.

    `None` where it says something else, including a line whose hole-free wording disagrees with
    the phrase's own: a phrase line can hard-code a value with no hole at all (`Then its exit code
    is 2`), and a raw line asking the same step for a *different* value is not a match on that
    alone — matching a phrase means saying what its body says, not just asking the same steps.
    """
    if template.keyword != real.keyword:
        return None
    found = re.match(f"^{pattern_regex(template.text)}$", real.text.strip())
    if found is None:
        return None
    holes = CAPTURE_RE.findall(template.text)
    return dict(zip(holes, found.groups(), strict=False))


def matches_window(phrase: Phrase, window: list[Line]) -> dict[str, str] | None:
    """The values this run of raw lines fills `phrase`'s holes with.

    Only where it says exactly what the phrase's own body says — line for line, wording and all.
    `None` where it says something else, or is not even the same number of lines.
    """
    if len(window) != len(phrase.lines):
        return None
    values: dict[str, str] = {}
    for template, real in zip(phrase.lines, window, strict=True):
        found = line_values(template, real)
        if found is None:
            return None
        values.update(found)
    return values


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
