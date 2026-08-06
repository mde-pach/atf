"""The step registry: a sentence, the function that runs it, and what that function asks for."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from typing_extensions import override

from .patterns import CAPTURE_RE, literal_length, pattern_regex

GIVEN, WHEN, THEN = "given", "when", "then"
KEYWORDS = (GIVEN, WHEN, THEN)

# `And` and `But` continue whatever keyword came before them, which is Gherkin's own rule.
CONTINUATIONS = ("and", "but", "*")


class StepError(Exception):
    """Raised when a sentence cannot be matched, or a step cannot be registered."""


@dataclass(frozen=True)
class Step:
    """One registered sentence: what it reads as, what runs it, and what it asks for."""

    keyword: str
    pattern: str
    function: Callable[..., Any]
    target: str = ""
    module: str = ""

    @property
    def placeholders(self) -> tuple[str, ...]:
        """The `{name}` holes a sentence fills."""
        return tuple(CAPTURE_RE.findall(self.pattern))

    @property
    def parameters(self) -> tuple[str, ...]:
        """What this step asks the framework for: its signature, minus the holes.

        A scenario's fixture closure does not contain these; this registry is what answers it.
        """
        holes = set(self.placeholders)
        return tuple(
            name
            for name in inspect.signature(self.function).parameters
            if name not in holes and name != "request"
        )

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(f"^{pattern_regex(self.pattern)}$")

    def match(self, sentence: str) -> dict[str, str] | None:
        """The values this sentence fills the holes with, or nothing when it is a different step."""
        found = self.regex.match(sentence.strip())
        if found is None:
            return None
        return dict(zip(self.placeholders, found.groups(), strict=False))

    @property
    def written_at(self) -> str:
        """Where this step is written, for a message about two of them claiming one sentence."""
        return f"{self.module}.{getattr(self.function, '__qualname__', '?')}"

    @override
    def __str__(self) -> str:
        return f"{self.keyword.title()} {self.pattern}"


REGISTRY: list[Step] = []


def register(keyword: str, pattern: str, target: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        step = Step(
            keyword=keyword,
            pattern=pattern,
            function=function,
            target=target,
            module=getattr(function, "__module__", ""),
        )
        clash = next((s for s in REGISTRY if s.keyword == keyword and s.pattern == pattern), None)
        if clash is not None and clash.function is not function:
            # Compared by module and name, so re-importing one steps module is a reload.
            if clash.written_at != step.written_at:
                raise StepError(
                    f"two steps are written {keyword.title()} {pattern!r}: "
                    f"{clash.written_at} and {step.written_at}"
                )
            REGISTRY.remove(clash)
        REGISTRY.append(step)
        return function

    return decorate


def given(pattern: str, *, target: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A sentence that arranges. `target` names the fixture its return value is bound to."""
    return register(GIVEN, pattern, target)


def when(pattern: str, *, target: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A sentence that acts."""
    return register(WHEN, pattern, target)


def then(pattern: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A sentence that claims."""
    return register(THEN, pattern)


def matching(keyword: str, sentence: str) -> Step | None:
    """The step a line means. The most specific wins, which is the one with the most wording.

    Two steps can both match `the owner "primary"` — a general one and one written for owners. The
    reader meant the more particular of them, so wording is what decides, not registration order.
    """
    candidates = [
        step for step in REGISTRY if step.keyword == keyword and step.match(sentence) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda step: literal_length(step.pattern))


def undefined(keyword: str, sentence: str) -> str:
    """What to say about a sentence nothing answers to — with the nearest ones ATF does know."""
    near = sorted(
        (step for step in REGISTRY if step.keyword == keyword),
        key=lambda step: -_overlap(step.pattern, sentence),
    )[:3]
    known = "\n    ".join(str(step) for step in near) or "nothing at all"
    return f"no step is written for {keyword.title()} {sentence!r}.\n  The nearest ATF knows:\n    {known}"


def _overlap(pattern: str, sentence: str) -> int:
    words = set(re.findall(r"[a-z]+", CAPTURE_RE.sub("", pattern).lower()))
    return len(words & set(re.findall(r"[a-z]+", sentence.lower())))


@dataclass
class Sentence:
    """One line of a scenario, after its keyword has been resolved through any `And`."""

    keyword: str
    text: str
    line: int = 0
    step: Step | None = None
    values: dict[str, str] = field(default_factory=dict)

    def resolve(self) -> Sentence:
        """Bind this line to the step that answers it, or say what is missing."""
        step = matching(self.keyword, self.text)
        if step is None:
            raise StepError(undefined(self.keyword, self.text))
        self.step = step
        self.values = step.match(self.text) or {}
        return self

    @property
    def requests(self) -> tuple[str, ...]:
        """What running this line will ask the framework for."""
        return self.step.parameters if self.step else ()
