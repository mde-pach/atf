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

**A step is read as the line it was written as.** YAML would rather it were something else — a colon
and a space start a mapping, so `contains "registered: env, now"` loads as a dict, and `"flag: true"`
comes back holding a boolean. Both are sentences. They are read from the document tree rather than
from loaded values, which takes that footgun away instead of asking every author to know about it.

**A step that takes a table carries its rows, written as YAML writes a mapping.** A step that takes
one ends with a colon, and so does a mapping key, so the two fit together with nothing invented:

```yaml
'the account is set up the way a new customer should be':
  - the account "primary" is:
      plan: free
      trial_ends_at: "#datetime"
```

Which is also what tells a table from the colon trap above: a table step's value is another
*mapping*, and a sentence YAML found structure in has a scalar. One quoting rule is unavoidable and
is checked at load — `#` starts a comment in YAML, so a marker has to be quoted.

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

from ..model.placeholders import PLACEHOLDER_RE, Unresolved
from .patterns import CAPTURE_RE, fill, pattern_regex

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

# What pytest-bdd calls the rows under a step, and therefore what a step declares to receive them.
DATATABLE = "datatable"

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
class Line:
    """One step a phrase stands for: the line, and the rows under it where it takes a table.

    A step that takes a table is written in YAML the way YAML writes a mapping, because a step that
    takes one ends with a colon and so does a mapping key:

    ```yaml
    'the account is set up the way a new customer's should be':
      - the account "primary" is:
          plan: free
          seats: 1
    ```

    No new format: that list item is an ordinary one-key mapping, and ATF hands the rows to the step
    as the table it was expecting.
    """

    text: str
    rows: tuple[tuple[str, str], ...] = ()

    @property
    def datatable(self) -> list[list[str]] | None:
        """The rows as pytest-bdd hands a table over, or nothing where there is no table."""
        return [[field, value] for field, value in self.rows] if self.rows else None


@dataclass(frozen=True)
class Phrase:
    """One sentence, and the steps it stands for."""

    pattern: str
    expands_to: tuple[Line, ...]
    captures: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return "Says in one line: " + "; ".join(line.text for line in self.expands_to)


def path_for(specs_dir: Path | str) -> Path:
    """Where a suite's phrasebook lives: one file, beside the features it is written for."""
    return Path(specs_dir) / FILENAME


# ---- reading one ------------------------------------------------------------


def load(path: Path) -> list[Phrase]:
    """Read and validate a phrasebook. An absent file is an empty one, not an error."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise PhrasebookError([f"could not be read as YAML: {exc}"], path) from None
    if root is None:
        return []
    if not isinstance(root, yaml.MappingNode):
        raise PhrasebookError(["the top level must be a mapping of phrase to the steps it stands for"], path)

    problems: list[str] = []
    phrases = [
        made
        for key, value in root.value
        if (made := _phrase(_text(key, text), _steps(value, text, problems), problems)) is not None
    ]
    _check_flat(phrases, problems)
    if problems:
        raise PhrasebookError(problems, path)
    return phrases


def _steps(node: yaml.Node, source: str, problems: list[str]) -> list[Line] | None:
    """The steps a phrase stands for, as the *text* they were written as.

    Read from the document tree rather than from loaded values, because a step is a line of English
    and YAML would rather it were something else. `contains "registered: env, now"` is a mapping to
    YAML — a colon and a space start one — and `contains "flag: true"` would come back holding a
    boolean. Both are sentences, and both are recovered here exactly as they were typed.

    The alternative was to refuse them and make every author quote a line they had no reason to
    think was special. This is that footgun taken away rather than labelled.
    """
    if isinstance(node, yaml.ScalarNode):
        return [Line(text=_text(node, source))]
    if isinstance(node, yaml.MappingNode):
        return [_line(node, source, problems)]
    if isinstance(node, yaml.SequenceNode):
        return [_line(item, source, problems) for item in node.value]
    return None


def _line(node: yaml.Node, source: str, problems: list[str]) -> Line:
    """One step: a line on its own, or a line with the rows a table step needs.

    The two are told apart by what the value is, and the distinction is exactly the one that
    matters. A step ending in a colon is a mapping key whose value is *another mapping* — the rows.
    A step that merely happens to contain a colon is a mapping key whose value is a scalar, which is
    YAML having found structure in a sentence, and is recovered from the source as it always was.
    """
    if isinstance(node, yaml.MappingNode) and len(node.value) == 1:
        key, value = node.value[0]
        if isinstance(value, yaml.MappingNode):
            # The colon is the step's, not YAML's: `the account "primary" is:` is how the step is
            # worded, and YAML ate it on the way in.
            return Line(text=f"{_text(key, source)}:", rows=_rows(value, source, problems))
    return Line(text=_text(node, source))


def _rows(node: yaml.MappingNode, source: str, problems: list[str]) -> tuple[tuple[str, str], ...]:
    """The rows of a table, as a step reads them: a field and what it must hold.

    A value YAML read as nothing is almost always a marker somebody did not quote — `plan: #str` is
    a key with a comment after it, not a key holding `#str`. Saying so is worth the check, because
    the claim would otherwise pass for the wrong reason.
    """
    rows: list[tuple[str, str]] = []
    for key, value in node.value:
        field = _text(key, source)
        if isinstance(value, yaml.ScalarNode) and value.tag.endswith(":null"):
            problems.append(
                f"the row {field!r} holds nothing. A `#` starts a comment in YAML, so a marker has "
                f'to be quoted: `{field}: "#str"`.'
            )
            continue
        rows.append((field, _text(value, source)))
    return tuple(rows)


def _text(node: yaml.Node, source: str) -> str:
    """One node as the line a person wrote.

    A scalar is taken as YAML read it, so quoting still works and still means what it means.
    Anything else — which is always YAML having found structure in a sentence — is taken back from
    the source between the marks the parser left.

    The first line of it, because a step is one line and a node's end mark runs on to the next
    token: past the blank lines and the comment that follow it.
    """
    if isinstance(node, yaml.ScalarNode):
        return str(node.value)
    raw = source[node.start_mark.index : node.end_mark.index]
    return raw.split("\n", 1)[0].strip()


def _phrase(pattern: str, steps: list[Line] | None, problems: list[str]) -> Phrase | None:
    if not pattern.strip():
        problems.append("a phrase is the sentence a spec will say, so it must be text")
        return None
    if not steps:
        problems.append(f"{pattern!r}: stands for nothing — list the steps it says in one line")
        return None

    captures = tuple(dict.fromkeys(CAPTURE_RE.findall(pattern)))
    for line in steps:
        # A capture is checked wherever the phrase writes one, in the line and in the rows alike:
        # a table cell reaching for `{plan}` the sentence never took would fail at run time with a
        # brace still in it, which is a worse way to find out.
        written = [line.text, *(cell for row in line.rows for cell in row)]
        unknown = [name for text in written for name in CAPTURE_RE.findall(text) if name not in captures]
        if unknown:
            known = ", ".join(captures) or "none"
            problems.append(
                f"{pattern!r}: its step {line.text!r} uses {{{unknown[0]}}}, which the phrase does "
                f"not capture (it captures: {known})"
            )
    return Phrase(pattern=pattern, expands_to=tuple(steps), captures=captures)


def _check_flat(phrases: list[Phrase], problems: list[str]) -> None:
    """No phrase may stand for another phrase. One level, always."""
    known = [(phrase, re.compile(pattern_regex(phrase.pattern))) for phrase in phrases]
    for phrase in phrases:
        for line in phrase.expands_to:
            for other, matcher in known:
                if matcher.fullmatch(line.text):
                    problems.append(
                        f"{phrase.pattern!r}: its step {line.text!r} is the phrase {other.pattern!r}. "
                        "A phrase stands for steps, never for another phrase — write out the steps "
                        "here instead."
                    )
    return None


# ---- running one ------------------------------------------------------------


def run(request: pytest.FixtureRequest, phrase: Phrase, values: dict[str, str], keyword: str) -> None:
    """Run every step this phrase stands for, in order, under the keyword it was said with."""
    __tracebackhide__ = True
    for line in phrase.expands_to:
        _run_step(request, phrase, _filled(line, values), keyword)


def _filled(line: Line, values: dict[str, str]) -> Line:
    """The line with the sentence's captures written into it — its text and its rows alike."""
    return Line(
        text=fill(line.text, values),
        rows=tuple((fill(field, values), fill(value, values)) for field, value in line.rows),
    )


def _run_step(request: pytest.FixtureRequest, phrase: Phrase, line: Line, keyword: str) -> None:
    __tracebackhide__ = True
    text = line.text
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
    # The table, last: a step that takes one declares `datatable` with a default, so it is never a
    # required argument and nothing above would have passed it. `${...}` in a cell is left alone —
    # a table step resolves its own cells, because pytest-bdd hands them over as one argument and
    # they never reach the hook that resolves everything else.
    if DATATABLE in parameters:
        arguments[DATATABLE] = line.datatable

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
    setattr(_phrase_step, MARKER, {"file": str(source), "expands_to": [line.text for line in phrase.expands_to]})
    return _phrase_step
