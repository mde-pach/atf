"""`atf explain`: one page about a thing, kind, system, scenario, phrase or file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import footprint, graph, lives, plan, reconcile, runs
from .declare import declaration_of, instance_of, name_of, values_of
from .environment import Ground
from .loader import Suite, fixture_name
from .spi import State

#: What a thing turned out to be. Never shown as a word; it decides which page is printed.
RESOURCE, KIND, SYSTEM, TEST, PHRASE, FILE = "resource", "kind", "system", "test", "phrase", "file"


@dataclass
class Subject:
    """What was pointed at, once it has been recognised."""

    what: str
    name: str
    #: Every test that reaches it. This is what `--select` narrows a run to.
    tests: list[str] = field(default_factory=list)
    #: Every declared thing it reaches, or that reaches it.
    resources: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


class Unknown(Exception):
    """Raised when nothing in the suite answers to what was pointed at."""


def find(suite: Suite, features: list[Any], phrases: dict[str, Any], pointed_at: str) -> str:
    """Which kind of thing this is. Checked most specific first, so a name beats a substring."""
    if pointed_at in suite.instances:
        return RESOURCE
    if pointed_at in suite.kinds or any(fixture_name(one) == pointed_at for one in suite.kinds):
        return KIND
    if any(declaration_of(one).system == pointed_at for one in suite.kinds.values()):
        return SYSTEM
    if pointed_at in phrases:
        return PHRASE
    for feature in features:
        for scenario in feature.tests:
            if scenario.name == pointed_at:
                return TEST
    if Path(pointed_at).exists():
        return FILE
    raise Unknown(_near(suite, features, phrases, pointed_at))


def _near(suite: Suite, features: list[Any], phrases: dict[str, Any], pointed_at: str) -> str:
    """What was nearly meant. A good compiler answers an unknown name with the ones it knows."""
    everything = (
        [(one, "a thing") for one in suite.instances]
        + [(fixture_name(one), "a kind") for one in suite.kinds]
        + [(one, "a phrase") for one in phrases]
        + [(one.name, "a scenario") for feature in features for one in feature.tests]
    )
    import difflib  # noqa: PLC0415 - a near miss is what an unknown name most wants answered

    lowered = pointed_at.lower()
    near = [f"{one}  ({what})" for one, what in everything if lowered in one.lower()]
    if not near:
        close = difflib.get_close_matches(pointed_at, [one for one, _ in everything], n=5, cutoff=0.6)
        kinds = dict(everything)
        near = [f"{one}  ({kinds.get(one, '')})" for one in close]
    if near:
        return f"nothing is called {pointed_at!r}. Did you mean:\n  " + "\n  ".join(near[:5])
    return f"nothing in this suite is called {pointed_at!r}"


# --- A declared thing ---------------------------------------------------------------------------


def a_resource(
    suite: Suite, features: list[Any], phrases: dict[str, Any], ground: Ground | None, root: Path, name: str
) -> Subject:
    """One thing: what it is, what it needs, what needs it, where it stands, and what it breaks."""
    node = suite.resource(name)
    declaration = declaration_of(node)
    record = instance_of(node)
    everything = list(suite.instances.values())

    recognised = declaration.key
    by = ", ".join(f"{one} {values_of(node).get(one)!r}" for one in recognised)
    out = [
        f"  {name} · a {fixture_name(declaration.kind)} · {declaration.system}"
        + (f" · known by {by}" if by else ""),
        f"  declared in {_where(declaration)}",
        "",
    ]

    needs = [name_of(one) or declaration_of(one).kind for one in graph.parents(node)]
    for field_name in sorted(record.resolved):
        need = declaration.need_for(field_name)
        called = need.kind.__name__ if need and need.kind else getattr(
            getattr(need, "resolver", None), "__name__", "?"
        )
        needs.append(f"{field_name} ← {called}")
    out.append(f"  needs      {', '.join(needs) or 'nothing'}")

    dependent = graph.dependents(node, everything)
    tests = _tests_reaching(suite, features, phrases, {name})
    out.append(
        f"  needed by  {len(tests)} scenarios, {len(dependent)} things"
    )
    out.append(f"  lives      {lives.of(node)} — {lives.why(lives.of(node), node)}")

    if ground is not None:
        state, _ = ground.find(node)
        out.append(f"  standing   {state} in {ground.config.name}")

    unfolded = plan.resolved(suite, name)
    if unfolded:
        out.append("")
        out.append("  to produce one")
        out += [f"    {one}" for one in unfolded]

    if tests:
        out.append("")
        out.append("  if it changes")
        out += [f"    {one}" for one in tests]

    return Subject(
        what=RESOURCE,
        name=name,
        tests=tests,
        resources=[name_of(one) for one in dependent],
        lines=out,
    )


def _where(declaration: Any) -> str:
    import sys

    module = sys.modules.get(declaration.module)
    return str(getattr(module, "__file__", None) or declaration.module)


# --- A scenario --------------------------------------------------------------------------------


def a_test(
    suite: Suite, features: list[Any], phrases: dict[str, Any], root: Path, environment: str, title: str
) -> Subject:
    """One scenario: what history says about it, and the chain that puts its things there."""
    scenario = next(
        (one for feature in features for one in feature.tests if one.name == title), None
    )
    if scenario is None:
        raise Unknown(f"no scenario called {title!r}")
    identity = runs.identity(scenario.path, scenario.name, root) if scenario.path else title

    seen = [
        (run, outcome)
        for run in runs.runs_for(root, environment)
        for outcome in run.outcomes
        if outcome.test == identity
    ]
    out = [f"  {title}", f"  {scenario.where}", ""]
    out += _history(seen)

    reach = footprint.of_scenario(suite, scenario, phrases)
    names = [one for one in suite.instances if one in reach.touches]
    if names:
        chain = " → ".join(
            [one for one in names]
            + sorted({declaration_of(suite.resource(one)).system for one in names})
        )
        out.append("")
        out.append(f"  it needs   {chain}")
    return Subject(what=TEST, name=title, tests=[identity], resources=names, lines=out)


def _history(seen: list[tuple[Any, Any]]) -> list[str]:
    """How a verdict is said: *failing since 4 runs ago, passed 61 times before that*.

    A verdict is not a fourth vocabulary beside outcomes. It is history, folded, at the moment
    something prints it — which is here, and nowhere else.
    """
    if not seen:
        return ["  never run"]
    latest = seen[-1]
    turned = 0
    for index in range(len(seen) - 1, 0, -1):
        if seen[index][1].outcome is not seen[index - 1][1].outcome:
            turned = len(seen) - index
            break
    before = len(seen) - turned
    out = []
    if turned:
        out.append(f"  {latest[1].outcome} since {turned} runs ago · {seen[0][1].outcome} {before} times before that")
        turn = seen[len(seen) - turned]
        was = seen[len(seen) - turned - 1]
        if turn[0].revision or was[0].revision:
            out.append(f"  turned between {was[0].revision or was[0].id} and {turn[0].revision or turn[0].id}")
    else:
        out.append(f"  {latest[1].outcome} for all {len(seen)} runs it has had")
    if latest[1].failed_at is not None and latest[1].failed_at.step:
        out.append(f"  {latest[1].failed_at.step}")
    return out


# --- A kind, a system, a phrase, a file ----------------------------------------------------------


def a_kind(suite: Suite, features: list[Any], phrases: dict[str, Any], pointed_at: str) -> Subject:
    cls = suite.kinds.get(pointed_at) or next(
        one for name, one in suite.kinds.items() if fixture_name(name) == pointed_at
    )
    declaration = declaration_of(cls)
    mine = [name for name, node in suite.instances.items() if type(node) is cls]
    tests = _tests_reaching(suite, features, phrases, set(mine))
    out = [
        f"  {declaration.kind} · {declaration.system}",
        f"  declared in {_where(declaration)}",
        "",
        f"  fields     {', '.join(declaration.fields) or 'none'}",
        f"  resolves   {', '.join(declaration.needs) or 'nothing'}",
        f"  owner      {declaration.owner}",
        "",
        f"  {len(mine)} declared",
    ]
    out += [f"    {one}" for one in sorted(mine)]
    if tests:
        out.append("")
        out.append(f"  {len(tests)} scenarios reach one")
        out += [f"    {one}" for one in tests]
    return Subject(what=KIND, name=pointed_at, tests=tests, resources=mine, lines=out)


def a_system(suite: Suite, features: list[Any], phrases: dict[str, Any], pointed_at: str) -> Subject:
    from . import steps as registry

    kinds = [name for name, cls in suite.kinds.items() if declaration_of(cls).system == pointed_at]
    mine = [
        name
        for name, node in suite.instances.items()
        if declaration_of(node).system == pointed_at
    ]
    tests = _tests_reaching(suite, features, phrases, set(mine))
    words = [str(one) for one in registry.REGISTRY if pointed_at.split(".")[0] in one.module]
    out = [
        f"  {pointed_at}",
        "",
        f"  kinds      {', '.join(sorted(kinds)) or 'none'}",
        f"  things     {len(mine)}",
    ]
    if words:
        out.append("")
        out.append("  the words it brings")
        out += [f"    {one}" for one in sorted(words)]
    if tests:
        out.append("")
        out.append(f"  {len(tests)} scenarios use it")
        out += [f"    {one}" for one in tests]
    return Subject(what=SYSTEM, name=pointed_at, tests=tests, resources=mine, lines=out)


def a_phrase(suite: Suite, features: list[Any], phrases: dict[str, Any], pointed_at: str) -> Subject:
    """One phrase: what it stands for, and every scenario that reaches it.

    Reached, not merely said: every scenario is expanded first, so a phrase said by a phrase counts.
    """
    from . import phrases as phrase_reader  # noqa: PLC0415

    said = phrases[pointed_at]
    tests = []
    for feature in features:
        for one in feature.tests:
            try:
                lines = phrase_reader.expand(one, {k: v for k, v in phrases.items() if k != pointed_at}).lines
            except phrase_reader.PhraseError:
                lines = one.lines
            if any(said.match(line.text) is not None for line in lines):
                tests.append(one.name)
    out = [
        f"  {pointed_at}",
        f"  taught at {said.where}",
        "",
        "  it stands for",
    ]
    out += [f"    {line.said} {line.text}" for line in said.lines]
    out.append("")
    out.append(f"  {len(tests)} scenarios say it")
    out += [f"    {one}" for one in tests]
    return Subject(what=PHRASE, name=pointed_at, tests=tests, lines=out)


def a_file(suite: Suite, features: list[Any], phrases: dict[str, Any], pointed_at: str) -> Subject:
    """A file: the scenarios in it, or the things a module declares and what they break."""
    path = Path(pointed_at).resolve()
    if path.suffix == ".feature":
        tests = [
            one.name
            for feature in features
            if feature.path and feature.path.resolve() == path
            for one in feature.tests
        ]
        out = [f"  {pointed_at}", "", f"  {len(tests)} scenarios"] + [f"    {one}" for one in tests]
        return Subject(what=FILE, name=pointed_at, tests=tests, lines=out)

    import sys

    kinds = {
        name
        for name, cls in suite.kinds.items()
        if (module := sys.modules.get(declaration_of(cls).module)) is not None
        and getattr(module, "__file__", None)
        and Path(str(module.__file__)).resolve() == path
    }
    mine = [name for name, node in suite.instances.items() if declaration_of(node).kind in kinds]
    tests = _tests_reaching(suite, features, phrases, set(mine))
    out = [
        f"  {pointed_at}",
        "",
        f"  declares   {', '.join(sorted(kinds)) or 'nothing'}",
        f"  things     {', '.join(sorted(mine)) or 'none'}",
        "",
        f"  {len(tests)} scenarios would be touched by a change here",
    ]
    out += [f"    {one}" for one in tests]
    return Subject(what=FILE, name=pointed_at, tests=tests, resources=mine, lines=out)


# --- Shared ------------------------------------------------------------------------------------


def _tests_reaching(
    suite: Suite, features: list[Any], phrases: dict[str, Any], names: set[str]
) -> list[str]:
    """Which scenarios reach any of these things, widened along lineage."""
    if not names:
        return []
    everything = list(suite.instances.values())
    widened = set(names)
    for name in names:
        for other in graph.dependents(suite.resource(name), everything):
            widened.add(name_of(other))
    out: list[str] = []
    for feature in features:
        for scenario in feature.tests:
            if footprint.of_scenario(suite, scenario, phrases).touches & widened:
                out.append(scenario.name)
    return sorted(out)


def about(
    suite: Suite,
    features: list[Any],
    phrases: dict[str, Any],
    ground: Ground | None,
    root: Path,
    environment: str,
    pointed_at: str,
) -> Subject:
    """The one entry point. Recognise what was pointed at, then print that thing's page."""
    what = find(suite, features, phrases, pointed_at)
    if what == RESOURCE:
        return a_resource(suite, features, phrases, ground, root, pointed_at)
    if what == KIND:
        return a_kind(suite, features, phrases, pointed_at)
    if what == SYSTEM:
        return a_system(suite, features, phrases, pointed_at)
    if what == PHRASE:
        return a_phrase(suite, features, phrases, pointed_at)
    if what == TEST:
        return a_test(suite, features, phrases, root, environment, pointed_at)
    return a_file(suite, features, phrases, pointed_at)


def loose(suite: Suite, features: list[Any], phrases: dict[str, Any]) -> dict[str, list[str]]:
    """What nothing asks for. Not a command any more — a section of `atf explain` with no argument."""
    from . import steps as registry

    reached: set[str] = set()
    said: set[str] = set()
    for feature in features:
        for scenario in feature.scenarios:
            reached |= footprint.of_scenario(suite, scenario, phrases).touches
            said |= {line.text for line in scenario.lines}

    things = [name_of(one) for one in graph.unused(suite.instances.values()) if name_of(one) not in reached]
    loose_phrases = [
        pattern
        for pattern, one in phrases.items()
        if not any(one.match(text) is not None for text in said)
    ]
    sentences = [
        (line.keyword, line.text)
        for feature in features
        for scenario in feature.scenarios
        for line in scenario.lines
    ]
    hit = {registry.matching(keyword, text) for keyword, text in sentences}
    loose_steps = [str(one) for one in registry.REGISTRY if one not in hit]
    return {"things": sorted(things), "phrases": sorted(loose_phrases), "words": sorted(loose_steps)}


def standing(ground: Ground, suite: Suite) -> dict[str, str]:
    """Where each thing stands here, for the summary `explain` with no argument prints."""
    return {
        one.name: str(one.state)
        for one in reconcile.status(ground, list(suite.instances.values()))
    }


def summary(
    suite: Suite,
    features: list[Any],
    phrases: dict[str, Any],
    ground: Ground | None,
    root: Path,
    environment: str,
) -> list[str]:
    """`atf explain` with nothing to explain: the shape of the suite, and where to point next."""
    unused = loose(suite, features, phrases)
    out = [
        f"  {sum(len(feature.tests) for feature in features)} scenarios · "
        f"{len(suite.instances)} things · {len(suite.kinds)} kinds · {len(phrases)} phrases",
        "",
        "  point at any of them:",
        "    atf explain groceries",
        '    atf explain "a list shows under its owner"',
        "    atf explain sql",
        "",
    ]
    if ground is not None:
        counts: dict[str, int] = {}
        for state in standing(ground, suite).values():
            counts[state] = counts.get(state, 0) + 1
        out.append(
            f"  {environment}: "
            + " · ".join(f"{count} {state}" for state, count in sorted(counts.items()))
        )
    for what, names in sorted(unused.items()):
        if names:
            out.append(f"  {len(names)} {what} nothing asks for: {', '.join(names[:5])}")
    return out


def state_of(ground: Ground, node: Any) -> State:
    return ground.find(node)[0]
