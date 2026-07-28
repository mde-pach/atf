"""The layer between a domain sentence and a primitive claim.

ATF's generic claims read fine while a scenario is only saying whether something is there —
`Then the owner "primary" exists` needs no translation. The moment a *value* is involved they stop:
`Then the result field "exit_code" is "2"` is a struct field access spelled in English, and making a
suite generic used to mean making its specs less readable exactly where they mattered most. There
was nothing between the sentence someone means and the claim ATF can decide.

A **phrase** is that missing layer, and it is data:

```yaml
'it is refused because "{reason}"':
  - the result field "exit_code" is "2"
  - the result field "output" contains "{reason}"
```

```gherkin
Then it is refused because "not in mutable_envs"
```

The technical vocabulary now lives in one file — which is also the only place to edit when
`mutable_envs` is renamed — and the spec says what a person means.

**Three rules hold this in place.**

*A phrase expands to steps, never to another phrase.* Flat, one level, no recursion, checked when
the file loads and refused by name. This is the guard against the phrasebook becoming a badly
designed programming language, which is the documented way layered-keyword frameworks fail at
scale. A phrase that wants another phrase's meaning writes the same two lines, and two lines of
YAML are cheaper than a language with a call stack, no types and no debugger.

*An expansion runs under the keyword the phrase was said with.* A phrase is a synonym for a group
of steps of one kind — `Then it is refused` stands for claims, `When the developer seeds` stands
for actions. Letting one phrase mix them would hide a `When` inside a `Then`, which is the
readability the phrase was supposed to buy, spent.

*A phrase is not a step.* It performs nothing itself. Everything it stands for is a step some suite
already had — ATF's or the project's — so a phrasebook adds no capability, only wording, and there
is never a question of where the behaviour lives.

**Why it does not simply rewrite the feature.** Expanding before pytest-bdd parses would be less
code, and the run report would then show four primitive steps where the file shows one sentence.
The reader would be reading one thing and the cockpit reporting another. So a phrase is a real step
definition that runs its steps inside itself, and what fails is the phrase — named, alongside the
step that failed inside it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from inspect import Parameter, Signature, signature
from pathlib import Path
from typing import Any

import pytest
import yaml
from _pytest.outcomes import Failed

from .discovery import CAPTURE_RE, fill, pattern_regex
from .placeholders import PLACEHOLDER_RE, Unresolved

# pytest-bdd has no public way to run one step from inside another, and a phrase is exactly that.
# These are its internals, imported in one place so that a version which moves them breaks here,
# next to this sentence, rather than somewhere a reader would have to guess about.
from pytest_bdd.parser import Step as _Step  # isort: skip
from pytest_bdd.scenario import get_step_function as _resolve_step  # isort: skip
from pytest_bdd.scenario import parse_step_arguments as _parse_arguments  # isort: skip
from pytest_bdd.utils import get_required_args as _required_args  # isort: skip
from _pytest.fixtures import call_fixture_func as _call  # isort: skip

FILENAME = "phrasebook.yaml"

# The attribute a phrase's step function carries, so discovery can tell it from an ordinary step:
# where it came from, and what it stands for — which is what its needs are the union of.
MARKER = "__atf_phrase__"

_DEFAULT_KEYWORD = "then"

# Which keyword the phrase now running was said with, so its steps run as the same kind. pytest-bdd
# gives a step function no way to ask, so it is taken from the hook that fires immediately before.
_KEYWORD = pytest.StashKey[str]()


class PhrasebookError(Exception):
    """The phrasebook could not be read. Every problem in it, not only the first."""

    def __init__(self, problems: list[str], path: Path) -> None:
        self.problems = problems
        self.path = path
        listed = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(f"{path}: invalid phrasebook:\n{listed}")


@dataclass(frozen=True)
class Phrase:
    """One sentence, and the steps it stands for."""

    pattern: str
    expands_to: tuple[str, ...]
    captures: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return "Says in one line: " + "; ".join(self.expands_to)


def path_for(specs_dir: Path | str) -> Path:
    """Where a suite's phrasebook lives: one file, beside the features it is written for."""
    return Path(specs_dir) / FILENAME


# ---- reading one ------------------------------------------------------------


def load(path: Path) -> list[Phrase]:
    """Read and validate a phrasebook. An absent file is an empty one, not an error."""
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PhrasebookError([f"could not be read as YAML: {exc}"], path) from None
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise PhrasebookError(["the top level must be a mapping of phrase to the steps it stands for"], path)

    problems: list[str] = []
    phrases = [made for pattern, body in raw.items() if (made := _phrase(pattern, body, problems)) is not None]
    _check_flat(phrases, problems)
    if problems:
        raise PhrasebookError(problems, path)
    return phrases


def _phrase(pattern: Any, body: Any, problems: list[str]) -> Phrase | None:
    if not isinstance(pattern, str) or not pattern.strip():
        problems.append(f"{pattern!r}: a phrase is the sentence a spec will say, so it must be text")
        return None
    if isinstance(body, str):
        body = [body]
    if not isinstance(body, list) or not body:
        problems.append(f"{pattern!r}: stands for nothing — list the steps it says in one line")
        return None

    steps = tuple(str(item) for item in body)
    captures = tuple(dict.fromkeys(CAPTURE_RE.findall(pattern)))
    for text in steps:
        unknown = [name for name in CAPTURE_RE.findall(text) if name not in captures]
        if unknown:
            known = ", ".join(captures) or "none"
            problems.append(
                f"{pattern!r}: its step {text!r} uses {{{unknown[0]}}}, which the phrase does not "
                f"capture (it captures: {known})"
            )
    return Phrase(pattern=pattern, expands_to=steps, captures=captures)


def _check_flat(phrases: list[Phrase], problems: list[str]) -> None:
    """No phrase may stand for another phrase. One level, always."""
    known = [(phrase, re.compile(pattern_regex(phrase.pattern))) for phrase in phrases]
    for phrase in phrases:
        for text in phrase.expands_to:
            for other, matcher in known:
                if matcher.fullmatch(text):
                    problems.append(
                        f"{phrase.pattern!r}: its step {text!r} is the phrase {other.pattern!r}. "
                        "A phrase stands for steps, never for another phrase — write out the steps "
                        "here instead."
                    )
    return None


# ---- running one ------------------------------------------------------------


def run(request: pytest.FixtureRequest, phrase: Phrase, values: dict[str, str], keyword: str) -> None:
    """Run every step this phrase stands for, in order, under the keyword it was said with."""
    __tracebackhide__ = True
    for text in (fill(item, values) for item in phrase.expands_to):
        _run_step(request, phrase, text, keyword)


def _run_step(request: pytest.FixtureRequest, phrase: Phrase, text: str, keyword: str) -> None:
    __tracebackhide__ = True
    made = _Step(name=text, type=keyword, indent=0, line_number=0, keyword=keyword.capitalize())
    found = _resolve_step(request, made)
    if found is None:
        pytest.fail(
            f"the phrase {phrase.pattern!r} stands for {text!r}, and no {keyword} step this feature "
            "can reach is worded that way."
        )

    function = found.step_func
    parameters = signature(function).parameters
    arguments: dict[str, Any] = {
        name: value for name, value in _parse_arguments(step=made, context=found).items() if name in parameters
    }
    arguments |= {name: request.getfixturevalue(name) for name in _required_args(function) if name not in arguments}
    _resolve_placeholders(request, arguments, phrase, text)

    try:
        _call(fixturefunc=function, request=request, kwargs=arguments)
    except (AssertionError, Failed) as exc:
        pytest.fail(f"{phrase.pattern!r} says {text!r}, and that did not hold:\n{exc}")


def _resolve_placeholders(
    request: pytest.FixtureRequest, arguments: dict[str, Any], phrase: Phrase, text: str
) -> None:
    """`${...}` in a step a phrase stands for, resolved as it is in one a scenario wrote itself.

    pytest-bdd's hook does this for every step the feature file names; a step inside a phrase never
    reaches that hook, because a phrase is one step as far as pytest-bdd is concerned.
    """
    engine = request.getfixturevalue("materializer")
    for name, value in list(arguments.items()):
        if not isinstance(value, str) or PLACEHOLDER_RE.search(value) is None:
            continue
        try:
            arguments[name] = str(engine.resolve(value))
        except Unresolved as exc:
            pytest.fail(f"{phrase.pattern!r} says {text!r}: {exc}")


# ---- registering one --------------------------------------------------------


def remember_keyword(request: pytest.FixtureRequest, keyword: str) -> None:
    """Called from the plugin's `before_step_call` hook, for the phrase about to run."""
    request.node.stash[_KEYWORD] = keyword or _DEFAULT_KEYWORD


def current_keyword(request: pytest.FixtureRequest) -> str:
    return request.node.stash.get(_KEYWORD, _DEFAULT_KEYWORD)


def make_step(phrase: Phrase, source: Path) -> Any:
    """The function ATF registers for one phrase.

    pytest-bdd hands a step only the parameters its signature names, so the signature has to carry
    this phrase's captures — declared rather than written, because they are known only once the
    file has been read.
    """

    def _phrase_step(**values: Any) -> None:
        __tracebackhide__ = True
        request = values.pop("request")
        run(request, phrase, {name: str(value) for name, value in values.items()}, current_keyword(request))

    declared = Signature(
        [Parameter("request", Parameter.POSITIONAL_OR_KEYWORD)]
        + [Parameter(name, Parameter.POSITIONAL_OR_KEYWORD) for name in phrase.captures]
    )
    _phrase_step.__name__ = "phrase"
    _phrase_step.__doc__ = phrase.summary
    # `inspect.signature` reports this in preference to the real one, which is what pytest-bdd and
    # its fixture resolution both read. The body still takes `**values`, and that is what gets
    # called — the declaration only says which of them to pass.
    _phrase_step.__signature__ = declared  # ty: ignore[unresolved-attribute]
    setattr(_phrase_step, MARKER, {"file": str(source), "expands_to": list(phrase.expands_to)})
    return _phrase_step
