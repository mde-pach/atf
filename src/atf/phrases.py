"""`@phrase` — vocabulary written in Gherkin, expanded before anything runs.

A phrase is a tagged scenario, never collected as a test. Saying its name in another scenario splices
its sentences in.

```gherkin
@phrase
Scenario: the output contains "{words}"
  Then the result field "output" contains "{words}"
```

It spans all three verbs, and **phrases may nest**. One flat namespace anywhere under the specs
directory, so a phrase is shareable between suites as an ordinary Python package.

**Expansion happens at collection, not while a scenario runs.** That is not a preference: ATF
decides at collection which resource each parameter resolves to, and a phrase that expanded later
would hide the sentences that decision is read from — so every scenario using one would go
unchecked. Phase 0 of MIGRATION.md sets out why.
"""

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

    A phrase's own sentences may say phrases, so this recurses — and a phrase that reaches itself is
    a cycle, reported with the way round rather than as a stack overflow.
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
