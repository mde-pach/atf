"""The one API the command, the editor and an agent all read. There is no second way in.

**No privileged path.** The editor holds no logic of its own: every view below is a function here,
and every button is one of the operations in [commands](commands.py) — the same call, the same
arguments, the same answer. The cost is real and worth stating: a feature that would be convenient
in a browser and awkward on a command line has to be made to work on the command line first.

**No knowledge of anybody's domain.** Nothing here names a system, a type, a claim or a marker. It
reports whatever the registries contain, so a suite that registers `@redis` gets a catalogue entry,
a count in the overview and a graph node without a line of editor code changing.

The old cockpit is the counter-example this file exists to prevent: seven of its eight routers reach
into `session` and `materializer` directly, so the no-privileged-path rule was already broken and
would re-rot without one place to read from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import graph, reconcile, record, steps
from .declare import declaration_of, instance_of, is_resource, name_of, values_of
from .environment import Ground
from .loader import Suite, fixture_name
from .record import Outcome, Verdict
from .spi import Did, State

# --- Overview -------------------------------------------------------------------------------------


@dataclass
class Overview:
    """One question: can I ship. The verdict, and the four things that could contradict it."""

    environment: str
    resources: dict[str, int]
    tests: dict[str, int]
    last_run: record.Run | None
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
        """A fold of the two vocabularies, never a fifth state, and it names the reason."""
        if self.ready:
            return f"{self.environment} is ready."
        why = []
        if self.unmakeable:
            why.append(f"{len(self.unmakeable)} resources are absent and cannot be made here")
        if unreachable := self.resources.get(str(State.UNREACHABLE), 0):
            why.append(f"{unreachable} resources are unreachable")
        if failed := self.tests.get(str(Outcome.FAILED), 0):
            why.append(f"{failed} tests are failing")
        if not self.well_formed:
            why.append(f"the suite has {self.faults} faults")
        return f"{self.environment} is not ready — {' and '.join(why)}."


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
    runs = record.runs_for(root, ground.config.name)
    last = runs[-1] if runs else None
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
    scope: str
    declared: int
    states: dict[str, int]


@dataclass
class ResourceDetail:
    """One resource, in the five things the catalogue shows about it."""

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


def catalogue(ground: Ground) -> list[KindSummary]:
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
            if outcome is not None:
                states[str(outcome.state)] = states.get(str(outcome.state), 0) + 1
        declaration = declaration_of(cls)
        out.append(
            KindSummary(
                kind=kind,
                system=declaration.system,
                scope=declaration.scope,
                declared=len(mine),
                states=states,
            )
        )
    return out


def instances(ground: Ground, kind: str) -> list[dict[str, Any]]:
    """The instances of one kind, with what the environment holds for each.

    Opening a kind is the second step of the catalogue: kinds first, then the particular resources,
    then one of them. Nothing is navigated by a flat list of every resource in the suite.
    """
    cls = ground.suite.kinds.get(kind)
    if cls is None:
        known = ", ".join(sorted(ground.suite.kinds)) or "none"
        raise KeyError(f"no resource kind called {kind!r} (declared: {known})")
    mine = [node for node in ground.suite.instances.values() if type(node) is cls]
    return [
        {
            "name": name_of(node),
            "state": str(outcome.state),
            "changes": sorted(outcome.changes),
            "recognised_by": {
                key: values_of(node).get(key) for key in declaration_of(node).unique_by
            },
        }
        for node, outcome in zip(mine, reconcile.status(ground, mine), strict=True)
    ]


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
            "options": declaration.options,
            "when_absent": declaration.when_absent,
            "scope": declaration.scope,
            "depends_on": [
                name_of(entry) if is_resource(entry) else getattr(entry, "__name__", str(entry))
                for entry in declaration.depends_on
            ],
        },
        recognised_by={key: values_of(resource).get(key) for key in declaration.unique_by},
        found=found,
        would_create=body if state is State.ABSENT else None,
        would_change={
            key: {"found": (found or {}).get(key), "declared": value} for key, value in changes.items()
        },
        can_make=can,
        why_not=why,
    )


def _can_make(ground: Ground, resource: Any, state: State) -> tuple[bool, str]:
    """When a resource cannot be made, the reason is data — not a disabled button with no tooltip."""
    declaration = declaration_of(resource)
    if state is State.UNREACHABLE:
        return False, f"the {declaration.system} system is unreachable"
    if not ground.mutable:
        return False, f"{ground.config.name} is not mutable"
    if declaration.when_absent == "require":
        return False, 'it is declared `when_absent="require"`'
    if declaration.when_absent == "observe":
        return False, 'it is declared `when_absent="observe"`'
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

    The edges are the ones the model already has: a resource reaches another through `depends_on`, a
    test reaches what it names, a scenario reaches a phrase by saying its sentence.
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
            if scenario.is_phrase:
                nodes.append(Node(id=scenario.name, label=scenario.name, kind="phrase"))
                continue
            said = {word for line in scenario.lines for word in line.text.replace('"', " ").split()}
            nodes.append(
                Node(
                    id=f"{feature.path}::{scenario.name}",
                    label=scenario.name,
                    kind="test",
                    needs=sorted(said & set(suite.instances))
                    + sorted(p for p in phrases if any(phrases[p].match(li.text) for li in scenario.lines)),
                )
            )
    return nodes


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
    """One behaviour: a scenario or a pytest function, treated alike because they compile alike."""

    id: str
    label: str
    form: str
    tags: list[str]
    verdict: str
    flaky: bool = False
    arranges: list[str] = field(default_factory=list)


def tests(suite: Suite, features: list[Any], root: Path, environment: str) -> list[TestEntry]:
    """Every behaviour the suite describes, in one list, with the verdict history gives it."""
    latest: dict[str, Outcome] = {}
    for run in record.runs_for(root, environment):
        for outcome in run.outcomes:
            latest[outcome.test] = outcome.outcome
    flaky = record.flaky(root, environment)

    out: list[TestEntry] = []
    for feature in features:
        for scenario in feature.scenarios:
            if scenario.is_phrase:
                continue
            words = {w for line in scenario.lines for w in line.text.replace('"', " ").split()}
            identity = f"{feature.path.name}::{scenario.name}" if feature.path else scenario.name
            seen = next((word for test, word in latest.items() if test.endswith(scenario.name)), None)
            out.append(
                TestEntry(
                    id=identity,
                    label=scenario.name,
                    form="scenario",
                    tags=list(scenario.tags),
                    verdict=str(record.verdict([seen] if seen else [])),
                    flaky=any(test.endswith(scenario.name) for test in flaky),
                    arranges=sorted(words & set(suite.instances)),
                )
            )
    return out


# --- The composer -------------------------------------------------------------------------------


def sayable(suite: Suite) -> dict[str, list[str]]:
    """Every sentence this suite can say, grouped by keyword.

    The composer is the one view with no command behind it: it writes Gherkin somebody could have
    typed, and performs nothing. What it offers is the registry, so a claim a suite registers is
    offered without the editor knowing anything about it.
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


def activity(root: Path, environment: str) -> list[record.Run]:
    """Past runs of this environment, newest first."""
    return list(reversed(record.runs_for(root, environment)))


def environments(suite: Suite) -> list[dict[str, Any]]:
    """Every environment, what it may do, and which systems it configures."""
    return [
        {
            "name": name,
            "mutable": config.mutable,
            "systems": sorted(config.settings),
            "default": name == suite.manifest.default_env,
        }
        for name, config in sorted(suite.manifest.environments.items())
    ]


def verdict_of(entries: list[TestEntry]) -> Verdict:
    """The fold a heading is coloured by, so nothing hides inside a collapsed node."""
    words = {
        "passing": Outcome.PASSED,
        "failing": Outcome.FAILED,
        "skipped": Outcome.SKIPPED,
    }
    return record.verdict([words[entry.verdict] for entry in entries if entry.verdict in words])
