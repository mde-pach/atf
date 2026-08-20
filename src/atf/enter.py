"""`atf enter`: a scenario replayed to the line that stopped, and a prompt speaking its language."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import core, lives, plugin, reconcile, runs, runtime, steps
from . import phrases as phrase_reader
from .declare import declaration_of, name_of
from .environment import Ground
from .loader import Suite
from .runtime import Scope
from .steps import Sentence, StepError

PROMPT = ">>> "
#: The three words the prompt understands that are not sentences of the suite.
NEXT, KEEP, DONE = "next", "keep as", "done"


class NoFailure(Exception):
    """Raised when nothing has failed, so there is nothing to be put inside."""


@dataclass
class Session:
    """One scenario, arranged and replayed, with the prompt standing where it stopped."""

    suite: Suite
    ground: Ground
    scenario: Any
    sentences: list[Sentence] = field(default_factory=list)
    state: Scope | None = None
    at: int = 0
    #: Every sentence typed at the prompt that ran. `keep as` writes these out as a scenario.
    typed: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.scenario.name


def last_failure(root: Path, environment: str) -> str:
    """The identity of the test that just broke.

    Bare `atf enter` meaning *the last failure* is most of the ergonomic. It is the difference
    between a tool somebody remembers exists and one they reach for.
    """
    past = runs.runs_for(root, environment)
    for run in reversed(past):
        failed = [one.test for one in run.outcomes if one.outcome is runs.Outcome.FAILED]
        if failed:
            return failed[-1]
    raise NoFailure(
        f"nothing has failed in {environment}. Name a scenario to enter one that passed:\n"
        f'  atf enter "a list shows under its owner"'
    )


def find(features: list[Any], wanted: str) -> Any:
    """The scenario to enter, named by its title or by the identity history carries."""
    title = wanted.partition("::")[2] or wanted
    for feature in features:
        for scenario in feature.tests:
            if scenario.name == title:
                return scenario
    raise NoFailure(f"no scenario called {title!r}")


def open_on(
    suite: Suite, ground: Ground, features: list[Any], phrases: dict[str, Any], wanted: str
) -> Session:
    """Arrange the scenario and replay it up to the line that failed, or to the end."""
    scenario = find(features, wanted)
    expanded = phrase_reader.expand(scenario, phrases)
    sentences = [
        Sentence(keyword=line.keyword, text=line.text, line=line.number).resolve()
        for line in expanded.lines
    ]
    session = Session(suite=suite, ground=ground, scenario=scenario, sentences=sentences)
    session.state = runtime.start(Scope(suite=suite, ground=ground))
    return session


def replay(session: Session, out: Any = sys.stdout) -> None:
    """Run each sentence in turn, and stop at the first that does not hold.

    The prompt is left standing after the line that stopped, which is where `next` carries on from.
    """
    assert session.state is not None
    for index, sentence in enumerate(session.sentences):
        session.at = index + 1
        try:
            plugin._run_sentence(session.state, sentence)
        except Exception as exc:  # noqa: BLE001 - stopping here is the whole point
            print(f"    ✗ {sentence.keyword.title()} {sentence.text}", file=out)
            print(f"      {exc}", file=out)
            return
        print(f"    ✓ {sentence.keyword.title()} {sentence.text}", file=out)
    session.at = len(session.sentences)


def step(session: Session, out: Any = sys.stdout) -> bool:
    """`next` — advance one sentence and show what `it` became.

    The prompt stands one sentence further on, and `it` is whatever that sentence produced.
    """
    assert session.state is not None
    if session.at >= len(session.sentences):
        print("  the scenario is finished", file=out)
        return False
    sentence = session.sentences[session.at]
    session.at += 1
    try:
        plugin._run_sentence(session.state, sentence)
        print(f"    ✓ {sentence.keyword.title()} {sentence.text}", file=out)
    except Exception as exc:  # noqa: BLE001
        print(f"    ✗ {sentence.keyword.title()} {sentence.text}\n      {exc}", file=out)
    show_it(session, out)
    return True


def show_it(session: Session, out: Any = sys.stdout) -> None:
    assert session.state is not None
    if session.state.happened:
        print(f"      {_one_line(session.state.it())}", file=out)


def say(session: Session, typed: str, out: Any = sys.stdout) -> None:
    """Run one line typed at the prompt.

    A sentence the suite knows runs for real; a thing's name re-reads it now; `it` shows the last.
    """
    assert session.state is not None
    text = typed.strip()
    if not text:
        return

    if text == "it":
        show_it(session, out)
        return

    if text in session.suite.instances:
        _show_resource(session, text, out)
        return

    sentence = _as_sentence(text)
    if sentence is None:
        print(f"  {steps.undefined(steps.CHECK, text)}", file=out)
        return
    try:
        plugin._run_sentence(session.state, sentence)
    except Exception as exc:  # noqa: BLE001 - the prompt reports, it does not raise at you
        print(f"      {exc}", file=out)
        return
    session.typed.append(text)
    show_it(session, out)


def _as_sentence(text: str) -> Sentence | None:
    """Which keyword this line is, worked out by which registry answers it best.

    Nobody types `Then` at a prompt. The sentence is the same sentence; only the ceremony is gone —
    so the most wording wins across all three registries, exactly as it does inside one.
    """
    from .patterns import literal_length  # noqa: PLC0415

    found = [
        (keyword, step)
        for keyword in (steps.GIVEN, steps.ACT, steps.CHECK)
        if (step := steps.matching(keyword, text)) is not None
    ]
    if not found:
        return None
    keyword, _ = max(found, key=lambda one: literal_length(one[1].pattern))
    try:
        return Sentence(keyword=keyword, text=text).resolve()
    except StepError:
        return None


def _show_resource(session: Session, name: str, out: Any) -> None:
    """**Presence is asked, never remembered**, and the prompt keeps that promise.

    Reads through `core.state_of` — the same call the editor's Tests page makes for its Output tab,
    so the prompt and the dashboard never drift into two different notions of "what this shows".
    """
    (one,) = core.state_of(session.ground, [name])
    fields = ", ".join(f"{k} {v!r}" for k, v in one["fields"].items())
    print(f"      a {one['kind']} · {one['state']} · lives {one['lives']}", file=out)
    if fields:
        print(f"      {fields}", file=out)


def keep(session: Session, title: str) -> str:
    """`keep as "…"` — write what you typed out as a scenario.

    The sentences replayed so far, then the ones typed, as a `Scenario:` block.
    """
    lines = [f"Scenario: {title}"]
    for sentence in session.sentences[: session.at]:
        lines.append(f"  {sentence.keyword.title()} {sentence.text}")
    for text in session.typed:
        sentence = _as_sentence(text)
        keyword = sentence.keyword.title() if sentence else "Then"
        lines.append(f"  {keyword} {text}")
    return "\n".join(lines) + "\n"


def append(path: Path, written: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write("\n" + written)


def close(session: Session) -> None:
    """Take away whatever entering made, exactly as a run would."""
    if session.state is None:
        return
    reconcile.teardown(session.ground, reconcile.living(session.state.made, lives.THE_TEST))
    reconcile.teardown(session.ground, reconcile.living(session.state.made, lives.THE_RUN))
    runtime.finish()


def header(session: Session) -> list[str]:
    return [f"  {session.name} · arranged, replayed to the failing line", ""]


def help_lines() -> list[str]:
    return [
        "",
        "  next            run the next sentence",
        "  <a sentence>    run it for real, including one this scenario never had",
        "  <a thing>       read it from the environment now",
        '  keep as "…"     write what you typed out as a scenario',
        "  done            leave, and take away what this made",
        "",
    ]


def _one_line(value: Any) -> str:
    """What `it` is, in one line. A record is named field by field; anything else is shown."""
    if isinstance(value, dict):
        return " · ".join(f"{one} {_short(other)}" for one, other in sorted(value.items()))
    if isinstance(value, list):
        return f"{len(value)} of them"
    return _short(value)


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "…"


def graph_of(suite: Suite, ground: Ground | None, names: list[str]) -> list[str]:
    """The chain that put each of these things there — what a failure prints under the assertion.

    Every framework prints the assertion. Only ATF can print why the thing under the assertion
    existed, and naming that chain is the differentiator; naming the sentence is table stakes.
    """
    from . import graph

    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        try:
            node = suite.resource(name)
        except Exception:  # noqa: BLE001 - a name the graph does not hold contributes nothing
            continue
        chain = list(reversed(graph.closure(node)))
        for depth, one in enumerate(chain):
            label = name_of(one) or declaration_of(one).kind
            if label in seen:
                continue
            seen.add(label)
            lead = "  " + ("  " * depth) + ("" if depth == 0 else "└ ")
            standing = ""
            if ground is not None:
                state, _ = ground.find(one)
                standing = f"{state}, {lives.of(one)}"
            else:
                standing = lives.of(one)
            out.append(f"{lead}{label:<20} {standing}")
    return out
