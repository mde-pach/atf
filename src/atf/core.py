"""The one API the command, the editor and an agent all read."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import footprint, graph, lives, reconcile, runs, steps
from .declare import declaration_of, instance_of, is_resource, name_of, values_of
from .environment import Ground
from .loader import Suite, fixture_name
from .runs import Outcome, Verdict
from .spi import Did, State

# --- Overview -------------------------------------------------------------------------------------


@dataclass
class Overview:
    """One question: can I ship. The verdict, and the four things that could contradict it."""

    environment: str
    resources: dict[str, int]
    tests: dict[str, int]
    last_run: runs.Run | None
    well_formed: bool
    faults: int = 0
    unmakeable: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """Absent is not unready **while every absent one can be made.** That is the whole rule."""
        return (
            not self.unmakeable
            and not self.resources.get(str(State.UNREACHABLE), 0)
            and not self.tests.get(str(Outcome.FAILED), 0)
            and self.well_formed
        )

    @property
    def sentence(self) -> str:
        """One sentence: ready, or not ready and what is at fault."""
        if self.ready:
            return f"{self.environment} is ready."
        why = []
        if self.unmakeable:
            why.append(f"{_many(len(self.unmakeable), 'resource')} absent and cannot be made here")
        if unreachable := self.resources.get(str(State.UNREACHABLE), 0):
            why.append(f"{_many(unreachable, 'resource')} unreachable")
        if failed := self.tests.get(str(Outcome.FAILED), 0):
            why.append(f"{_many(failed, 'test')} failing")
        if not self.well_formed:
            why.append(f"the suite has {self.faults} faults")
        return f"{self.environment} is not ready — {' and '.join(why)}."


def _many(count: int, thing: str) -> str:
    """`1 resource is`, `2 resources are` — the sentence has to read."""
    return f"{count} {thing} is" if count == 1 else f"{count} {thing}s are"


def overview(ground: Ground, root: Path, faults: int = 0) -> Overview:
    """The four numbers, from the two vocabularies and nothing else."""
    outcomes = reconcile.status(ground, list(ground.suite.instances.values()))
    counts = {
        str(word): sum(1 for outcome in outcomes if outcome.state is word)
        for word in (State.PRESENT, State.ABSENT, State.UNREACHABLE)
    }
    unmakeable = [
        outcome.name
        for outcome in outcomes
        if outcome.state is State.ABSENT and outcome.did is Did.LEFT_ALONE
    ]
    past = runs.runs_for(root, ground.config.name)
    last = past[-1] if past else None
    tests = last.counts if last else {}
    return Overview(
        environment=ground.config.name,
        resources=counts,
        tests={str(word): count for word, count in tests.items()},
        last_run=last,
        well_formed=faults == 0,
        faults=faults,
        unmakeable=unmakeable,
    )


# --- Catalogue ------------------------------------------------------------------------------------


@dataclass
class KindSummary:
    """One declared kind, and what the environment holds for its instances."""

    kind: str
    system: str
    owner: str
    declared: int
    states: dict[str, int]


@dataclass
class ResourceDetail:
    """One resource, in the five things resources shows about it."""

    name: str
    kind: str
    system: str
    environment: str
    state: str
    declaration: dict[str, Any]
    recognised_by: dict[str, Any]
    found: dict[str, Any] | None
    would_create: dict[str, Any] | None
    would_change: dict[str, Any]
    can_make: bool
    why_not: str = ""


def resources(ground: Ground) -> list[KindSummary]:
    """Every declared kind, navigated by kind first — not one flat list of instances."""
    outcomes = {
        outcome.resource: outcome
        for outcome in reconcile.status(ground, list(ground.suite.instances.values()))
    }
    out: list[KindSummary] = []
    for kind, cls in sorted(ground.suite.kinds.items()):
        mine = [node for node in ground.suite.instances.values() if type(node) is cls]
        states: dict[str, int] = {}
        for node in mine:
            outcome = outcomes.get(node)
            if outcome is None:
                continue
            # Not a fourth `State` — the state is still exactly `present`. "Drifted" is this view's
            # own word for a present resource whose found values would be changed to match declared.
            key = "drifted" if outcome.state is State.PRESENT and outcome.changes else str(outcome.state)
            states[key] = states.get(key, 0) + 1
        declaration = declaration_of(cls)
        out.append(
            KindSummary(
                kind=kind,
                system=declaration.system,
                owner=declaration.owner,
                declared=len(mine),
                states=states,
            )
        )
    return out


def instances(ground: Ground, kind: str) -> list[dict[str, Any]]:
    """The instances of one kind, with what the environment holds for each.

    Opening a kind is the second step of resources: kinds first, then the particular resources, then
    one of them. Nothing is navigated by a flat list of every resource in the suite.
    """
    cls = ground.suite.kinds.get(kind)
    if cls is None:
        known = ", ".join(sorted(ground.suite.kinds)) or "none"
        raise KeyError(f"no resource kind called {kind!r} (declared: {known})")
    mine = [node for node in ground.suite.instances.values() if type(node) is cls]
    out = []
    for node, outcome in zip(mine, reconcile.status(ground, mine), strict=True):
        can_make, _ = _can_make(ground, node, outcome.state)
        out.append(
            {
                "name": name_of(node),
                "state": str(outcome.state),
                "changes": sorted(outcome.changes),
                "recognised_by": {
                    key: values_of(node).get(key) for key in declaration_of(node).key
                },
                "lives": lives.of(node),
                #: Absent, and nothing stops ATF making it — what a scoped Provision action needs to
                #: decide whether to offer itself. `closure_size` is what's beside it, once it does:
                #: everything else provisioning it would provision too, not counting itself.
                "can_provision": outcome.state == State.ABSENT and can_make,
                "closure_size": len(graph.closure(node)) - 1,
            }
        )
    return out


@dataclass
class Browsed:
    """What the environment holds for a kind, beyond what the suite declared.

    `browsable` and `why` distinguish the two ways this can come back empty: a system with no
    `browse()` at all, and one that has it but found nothing left over once the declared instances
    are matched off.
    """

    browsable: bool
    why: str = ""
    records: list[dict[str, Any]] = field(default_factory=list)


def undeclared(ground: Ground, kind: str) -> Browsed:
    """What `browse()` finds for this kind that no declared instance's key matches.

    Answers *"what's out there that the suite doesn't know about"* — read-only, never a write. Needs
    one declared instance to call `browse()` through, since it is a method of the resource, not the
    kind; a kind with none declared has nothing to browse from yet.
    """
    cls = ground.suite.kinds.get(kind)
    if cls is None:
        known = ", ".join(sorted(ground.suite.kinds)) or "none"
        raise KeyError(f"no resource kind called {kind!r} (declared: {known})")
    mine = [node for node in ground.suite.instances.values() if type(node) is cls]
    if not mine:
        return Browsed(browsable=False, why=f"declare a {fixture_name(kind)} first — browse looks through one")
    declaration = declaration_of(cls)
    try:
        found = reconcile.browse(ground, mine[0])
    except reconcile.ProvisionError as exc:
        return Browsed(browsable=False, why=str(exc))
    keys = declaration.key
    known = {tuple(values_of(node).get(k) for k in keys) for node in mine} if keys else set()
    leftover = [record for record in found if not keys or tuple(record.get(k) for k in keys) not in known]
    return Browsed(
        browsable=True,
        records=[
            {
                "label": " · ".join(str(record[k]) for k in keys if k in record) or "no identity",
                "fields": {k: v for k, v in record.items() if not str(k).startswith("_")},
            }
            for record in leftover
        ],
    )


def detail(ground: Ground, name: str) -> ResourceDetail:
    """One resource, including what would be sent to create it and what would be changed.

    Neither is a preview this assembles. The create body is what the adapter's `create` would
    receive; the change set is the diff ATF computed and would hand to `update`.
    """
    resource = ground.suite.resource(name)
    declaration = declaration_of(resource)
    state, found = ground.find(resource)

    body = {
        field_name: (
            {"resource": name_of(value), "record": ground.find(value)[1]}
            if is_resource(value)
            else value
        )
        for field_name, value in values_of(resource).items()
    }
    changes = reconcile.diff(resource, found) if found else {}
    can, why = _can_make(ground, resource, state)

    return ResourceDetail(
        name=name,
        kind=declaration.kind,
        system=declaration.system,
        environment=ground.config.name,
        state=str(state),
        declaration={
            "fields": {k: str(v) for k, v in declaration.fields.items()},
            # `at` is whichever system's own setting, where it has one — not every system does.
            "at": getattr(type(resource), "at", ""),
            "owner": ground.owner_of(resource),
            "lives": lives.of(resource),
            "needs": {
                name: (need.kind.__name__ if need.kind else getattr(need.resolver, "__name__", "?"))
                for name, need in declaration.needs.items()
            },
        },
        recognised_by={key: values_of(resource).get(key) for key in declaration.key},
        found=found,
        would_create=body if state is State.ABSENT else None,
        would_change={
            key: {"found": (found or {}).get(key), "declared": value} for key, value in changes.items()
        },
        can_make=can,
        why_not=why,
    )


def state_of(ground: Ground, names: list[str]) -> list[dict[str, Any]]:
    """What `atf enter` would show for each of these resources: presence, lifetime, and fields.

    **Presence is asked, never remembered** — the same call `atf enter`'s prompt makes, so a claim
    opened from a failing test's Output tab sees exactly what typing that resource's name there would
    have shown.
    """
    out: list[dict[str, Any]] = []
    for name in names:
        node = ground.suite.resource(name)
        state, found = ground.find(node)
        declaration = declaration_of(node)
        out.append(
            {
                "name": name,
                "kind": fixture_name(declaration.kind),
                "state": str(state),
                "lives": lives.of(node),
                "fields": {k: v for k, v in sorted((found or {}).items()) if not k.startswith("_")},
            }
        )
    return out


def _can_make(ground: Ground, resource: Any, state: State) -> tuple[bool, str]:
    """Whether ATF may make this here, and what stops it. One word, asked at two levels."""
    declaration = declaration_of(resource)
    if state is State.UNREACHABLE:
        return False, f"the {declaration.system} system is unreachable"
    if ground.owner_of(resource) == "them":
        return False, f"{ground.config.name} does not own it — ATF only looks"
    return True, ""


# --- The graph ------------------------------------------------------------------------------------


@dataclass
class Node:
    """One node of the spine: a resource, a test or a phrase, and the edges leaving it."""

    id: str
    label: str
    kind: str
    needs: list[str] = field(default_factory=list)


def spine(suite: Suite, features: list[Any], phrases: dict[str, Any]) -> list[Node]:
    """Every resource, test and phrase, reachable by moving along an edge.

    The edges are the ones the model already has: a thing reaches another through the `needs()` at
    its field, a test reaches what it names, a scenario reaches a phrase by saying its sentence.
    """
    nodes = [
        Node(
            id=name_of(node),
            label=f"{declaration_of(node).kind} {name_of(node)}",
            kind="resource",
            needs=[name_of(parent) for parent in graph.parents(node)],
        )
        for node in suite.instances.values()
    ]
    for feature in features:
        for scenario in feature.scenarios:
            nodes.append(
                Node(
                    id=scenario.name if scenario.is_phrase else f"{feature.path}::{scenario.name}",
                    label=scenario.name,
                    kind="phrase" if scenario.is_phrase else "test",
                    needs=_reached(scenario, suite, phrases),
                )
            )
    return nodes


def _reached(scenario: Any, suite: Suite, phrases: dict[str, Any]) -> list[str]:
    """What one scenario or phrase reaches: the resources it touches, and the phrases it says."""
    nested = sorted(
        name
        for name, phrase in phrases.items()
        if name != scenario.name
        and any(phrase.match(line.text) is not None for line in scenario.lines)
    )
    return footprint.arranged(suite, footprint.of_scenario(suite, scenario, phrases)) + nested


@dataclass
class Neighbourhood:
    """One node and every edge touching it, which is how the graph is moved through."""

    id: str
    label: str
    kind: str
    sentence: str
    needs: list[Node] = field(default_factory=list)
    needed_by: list[Node] = field(default_factory=list)


def around(suite: Suite, features: list[Any], phrases: dict[str, Any], id: str) -> Neighbourhood:
    """One node of the spine, with what it reaches and what reaches it."""
    nodes = spine(suite, features, phrases)
    here = next((node for node in nodes if node.id == id), None)
    if here is None:
        raise KeyError(id)
    by_id = {node.id: node for node in nodes}
    return Neighbourhood(
        id=here.id,
        label=here.label,
        kind=here.kind,
        sentence=in_words(suite, id) if here.kind == "resource" else "",
        needs=[by_id[name] for name in here.needs if name in by_id],
        needed_by=[node for node in nodes if id in node.needs],
    )


def in_words(suite: Suite, name: str) -> str:
    """Small lineage said in a sentence, which is what the view prefers before it draws."""
    chain = [name_of(node) for node in graph.closure(suite.resource(name))]
    if len(chain) == 1:
        return f"{name} needs nothing."
    if len(chain) == 2:
        return f"{chain[1]} needs {chain[0]}."
    steps_back = ", which needs ".join(reversed(chain))
    return f"{steps_back}."


# --- Tests ----------------------------------------------------------------------------------------


@dataclass
class TestEntry:
    """One behaviour, in either form: a scenario or a pytest function."""

    id: str
    label: str
    form: str
    tags: list[str]
    verdict: str
    flaky: bool = False
    arranges: list[str] = field(default_factory=list)
    #: What this behaviour is for, in one line — a scenario's own free text, or a function's
    #: docstring. Empty where nobody wrote one; nothing invents a description that isn't there.
    description: str = ""


def tests(
    suite: Suite, features: list[Any], root: Path, environment: str, phrases: dict[str, Any] | None = None
) -> list[TestEntry]:
    """Every behaviour the suite describes, in one list, with the verdict history gives it.

    A scenario and a pytest function appear the same way. `form` says which one you are looking at
    and nothing else treats them differently.
    """
    said = phrases or {}
    latest: dict[str, Outcome] = {}
    for run in runs.runs_for(root, environment):
        for outcome in run.outcomes:
            latest[outcome.test] = outcome.outcome
    flaky = runs.flaky(root, environment)

    def entry(
        identity: str, label: str, form: str, tags: list[str], arranges: list[str], description: str
    ) -> TestEntry:
        seen = latest.get(identity)
        return TestEntry(
            id=identity,
            label=label,
            form=form,
            tags=tags,
            verdict=str(runs.verdict([seen] if seen else [])),
            flaky=identity in flaky,
            arranges=arranges,
            description=description,
        )

    out: list[TestEntry] = []
    for feature in features:
        for scenario in feature.scenarios:
            if scenario.is_phrase:
                continue
            reach = footprint.arranged(suite, footprint.of_scenario(suite, scenario, said))
            identity = (
                runs.identity(feature.path, scenario.name, root) if feature.path else scenario.name
            )
            out.append(
                entry(identity, scenario.name, "scenario", list(scenario.tags), reach, scenario.description)
            )
    for path, name, asks, description in _functions(suite):
        reach = footprint.arranged(suite, footprint.of_function(suite, asks))
        out.append(entry(runs.identity(path, name, root), name, "function", [], reach, description))
    return out


def _functions(suite: Suite) -> list[tuple[Path, str, list[str], str]]:
    """Every Python test in the suite, with the things it asks for by name and its docstring.

    These are the library surface, and what `atf plan` counts under `python tests`.
    """
    import ast

    found: list[tuple[Path, str, list[str], str]] = []
    for path in suite.library:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
                asks = [one.arg for one in node.args.args]
                said = (ast.get_docstring(node) or "").strip().splitlines()
                found.append((path, node.name, asks, said[0] if said else ""))
    return found


@dataclass
class TestDetail:
    """One test opened: what it says, what it asks for, and what history says about it."""

    id: str
    label: str
    form: str
    tags: list[str] = field(default_factory=list)
    verdict: str = "never run"
    flaky: bool = False
    where: str = ""
    #: The file this test is written in, and the line its `Scenario:`/`Phrase:` starts on — empty
    #: and `0` for a Python test, which is source ATF reads but does not offer to rewrite.
    path: str = ""
    number: int = 0
    lines: list[tuple[str, str]] = field(default_factory=list)
    arranges: list[str] = field(default_factory=list)
    last: Any = None
    before: list[str] = field(default_factory=list)


def detail_of_test(
    suite: Suite,
    features: list[Any],
    root: Path,
    environment: str,
    id: str,
    phrases: dict[str, Any] | None = None,
) -> TestDetail:
    """One test, its sentences, and its outcomes newest first. `KeyError` where there is no such test."""
    listed = next((one for one in tests(suite, features, root, environment, phrases) if one.id == id), None)
    if listed is None:
        raise KeyError(id)

    lines: list[tuple[str, str]] = []
    where = ""
    path = ""
    number = 0
    for feature in features:
        if feature.path is None:
            continue
        for scenario in feature.scenarios:
            if scenario.is_phrase or runs.identity(feature.path, scenario.name, root) != id:
                continue
            lines = [(line.keyword.title(), line.text) for line in scenario.lines]
            where = f"{feature.path.name}:{scenario.number}"
            path = str(feature.path)
            number = scenario.number

    outcomes = [
        outcome
        for run in runs.runs_for(root, environment)
        for outcome in run.outcomes
        if outcome.test == listed.id
    ]
    return TestDetail(
        id=listed.id,
        label=listed.label,
        form=listed.form,
        tags=listed.tags,
        verdict=listed.verdict,
        flaky=listed.flaky,
        where=where,
        path=path,
        number=number,
        lines=lines,
        arranges=listed.arranges,
        last=outcomes[-1] if outcomes else None,
        before=[str(one.outcome) for one in reversed(outcomes[:-1])],
    )


# --- Editing a test's own source -------------------------------------------------------------------
#
# A test written as Gherkin is a block of lines in a file somebody can open and change directly —
# not something only a picker composes. These read and write exactly that block, real bytes, with
# the same safety a save has always needed: written, re-parsed, and rolled back if the result
# doesn't hold together as a suite ATF can still read.


def _scenario_range(path: Path, number: int) -> tuple[int, int]:
    """The 1-indexed, inclusive line range one scenario occupies, trailing blank lines trimmed."""
    from . import feature as feature_module

    read = feature_module.read(path)
    later = sorted(one.number for one in read.scenarios if one.number > number)
    lines = path.read_text(encoding="utf-8").splitlines()
    end = (later[0] - 1) if later else len(lines)
    while end > number and not lines[end - 1].strip():
        end -= 1
    return number, end


def scenario_text(path: Path, number: int) -> str:
    """One scenario's own lines, exactly as written — for opening in an editor."""
    start, end = _scenario_range(path, number)
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start - 1 : end]) + "\n"


def write_scenario(path: Path, number: int, text: str) -> None:
    """Replace one scenario's lines in place. `FeatureError` if the result no longer parses.

    The file is written, then re-read through the real parser; a suite that no longer reads is not
    saved — the original bytes come back first, so an edit can never leave a file half-written.
    """
    from . import feature as feature_module
    from .feature import FeatureError

    original = path.read_text(encoding="utf-8")
    start, end = _scenario_range(path, number)
    lines = original.splitlines()
    candidate = "\n".join([*lines[: start - 1], *text.rstrip("\n").split("\n"), *lines[end:]]) + "\n"
    path.write_text(candidate, encoding="utf-8")
    try:
        feature_module.read(path)
    except FeatureError:
        path.write_text(original, encoding="utf-8")
        raise


# --- The composer -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Offer:
    """One sentence that can be said at this point, and why it is on offer."""

    keyword: str
    sentence: str
    why: str = ""


def offers(
    ground: Ground,
    phrases: dict[str, Any],
    so_far: list[tuple[str, str]],
) -> list[Offer]:
    """What can be said *next*, given what has been said above.

    Three rules, all read from the registries and the graph:

    - a `Given` for any resource the suite declares, by name or by kind, and only while nothing
      above it has acted;
    - a `When` only where the adapter can perform it — `list every` needs `browse`;
    - a `Then` only once something above it has produced what the claim reads.

    Ordering the steps differently re-answers the offer.
    """
    suite = ground.suite
    arranged = {name for keyword, text in so_far if keyword == "given" for name in _named(text, suite)}
    acted = any(keyword in ("when", "then") for keyword, _ in so_far)

    out: list[Offer] = []
    if not acted:
        for name, node in sorted(suite.instances.items()):
            kind = fixture_name(declaration_of(node).kind)
            out.append(Offer("Given", f'the {kind} "{name}"', "declared by this suite"))
        for kind in sorted(suite.kinds):
            out.append(Offer("Given", f"a {fixture_name(kind)}", "resolution can build one"))

    for name in sorted(arranged):
        node = suite.instances[name]
        declaration = declaration_of(node)
        kind = fixture_name(declaration.kind)
        for field_name in sorted(values_of(node)):
            if not is_resource(values_of(node)[field_name]):
                out.append(
                    Offer(
                        "When",
                        f'the {kind} "{name}" {field_name} becomes ""',
                        "it is arranged above, and ATF owns this environment",
                    )
                )
        if ground.can(node, "browse"):
            out.append(Offer("When", f"I list every {kind}", "the adapter browses"))
        out.append(Offer("Then", f'the {kind} "{name}" exists', "it is arranged above"))
        for field_name in sorted(values_of(node)):
            if not is_resource(values_of(node)[field_name]):
                out.append(
                    Offer("Then", f'the {kind} "{name}" {field_name} is ""', "it is arranged above")
                )

    if "shell" in ground.drivers:
        out.append(Offer("When", 'I run ""', "this environment configures a shell"))
    if acted:
        out.append(Offer("Then", "its exit code is 0", "something happened above"))
        out.append(Offer("Then", 'it mentions ""', "something happened above"))

    for pattern in sorted(phrases):
        keyword = _phrase_keyword(phrases[pattern])
        if keyword == "Given" and acted:
            continue
        out.append(Offer(keyword, pattern, "a phrase this suite teaches"))
    return out


def _named(text: str, suite: Suite) -> list[str]:
    return [word.strip('"') for word in text.split() if word.strip('"') in suite.instances]


def _phrase_keyword(phrase: Any) -> str:
    """A phrase is offered under the verb its own body uses, undistinguished from a built-in."""
    keywords = {line.keyword for line in getattr(phrase, "lines", [])}
    if keywords == {"given"}:
        return "Given"
    if keywords == {"then"}:
        return "Then"
    return "When" if "when" in keywords else "Then"


def why_no_when(ground: Ground, suite: Suite) -> list[str]:
    """Systems that contribute no `When`, and why — one with neither `act` nor `browse`."""
    quiet: list[str] = []
    for kind, cls in sorted(suite.kinds.items()):
        node = next((one for one in suite.instances.values() if type(one) is cls), None)
        if node is None:
            continue
        if not ground.can(node, "act") and not ground.can(node, "browse"):
            quiet.append(f"{kind}: its adapter implements neither `act` nor `browse`")
    return quiet


def sayable() -> dict[str, list[str]]:
    """Every sentence this process's suite can say, grouped by keyword.

    A process ever loads one suite, so the registry `@act`/`@check` filled at import time already
    is that suite's — nothing here needs to be told which one. The composer is the one view with
    no command behind it: it writes Gherkin somebody could have typed, and performs nothing.
    """
    offered: dict[str, list[str]] = {keyword: [] for keyword in steps.KEYWORDS}
    for step in steps.REGISTRY:
        offered.setdefault(step.keyword, []).append(step.pattern)
    for keyword in offered:
        offered[keyword] = sorted(set(offered[keyword]))
    return offered


def subjects(suite: Suite) -> dict[str, list[str]]:
    """What a sentence's `{kind}` and `{name}` can be filled with, from the declarations."""
    return {
        fixture_name(kind): sorted(
            instance_of(node).name
            for node in suite.instances.values()
            if type(node) is cls
        )
        for kind, cls in suite.kinds.items()
    }


# --- Activity and environments --------------------------------------------------------------------


def activity(root: Path, environment: str) -> list[runs.Run]:
    """Past runs of this environment, newest first."""
    return list(reversed(runs.runs_for(root, environment)))


def environments(suite: Suite) -> list[dict[str, Any]]:
    """Every environment, who owns what is in it, and which systems it configures."""
    return [
        {
            "name": name,
            "owner": config.owner,
            "mutable": config.mutable,
            "systems": sorted(config.settings),
            "default": name == suite.manifest.default_env,
        }
        for name, config in suite.manifest.environments.items()
    ]


def verdict_of(entries: list[TestEntry]) -> Verdict:
    """The fold a heading is coloured by, so nothing hides inside a collapsed node."""
    words = {
        "passing": Outcome.PASSED,
        "failing": Outcome.FAILED,
        "skipped": Outcome.SKIPPED,
    }
    return runs.verdict([words[entry.verdict] for entry in entries if entry.verdict in words])
