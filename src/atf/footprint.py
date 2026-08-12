"""What one test touches: what it reads, what it writes, what it cannot see. The one answer to that."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import graph, lives, steps
from . import phrases as phrase_reader
from .declare import name_of
from .feature import Scenario
from .loader import Suite, fixture_name
from .steps import OPAQUE, READS, WRITES, Sentence, StepError

#: What a Python test body does to what its fixtures name. A signature says what is asked for and
#: nothing about what the lines below it do.
A_TEST_BODY = "a Python test body"


@dataclass(frozen=True)
class Footprint:
    """One test's reach: what it reads, what it writes, and the sentences the graph cannot follow."""

    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    #: Sentences whose effect is not declared. Each is quoted as it was written.
    opaque: tuple[str, ...] = ()
    #: Set when the test could not be read at all, carrying what stopped it.
    unreadable: str = ""

    @property
    def touches(self) -> frozenset[str]:
        """Every resource this test reaches, whichever way it reaches it."""
        return self.reads | self.writes

    @property
    def sealed(self) -> bool:
        """Whether every sentence in this test has an effect the graph can follow."""
        return not self.opaque and not self.unreadable

    @property
    def why_not_sealed(self) -> str:
        """What stops this test from being placed against another, in one line."""
        if self.unreadable:
            return f"it cannot be read: {self.unreadable.splitlines()[0]}"
        if self.opaque:
            return f'"{self.opaque[0]}" has an effect nothing declares'
        return ""

    def conflicts_with(self, other: Footprint) -> bool:
        """Whether these two could interfere, so that one must finish before the other starts.

        Two tests that only read the same resources never conflict. An unsealed footprint conflicts
        with itself and is placed apart from the sealed ones by `schedule`.
        """
        if not self.sealed or not other.sealed:
            return True
        return bool(self.writes & other.touches or other.writes & self.touches)


# --- Reading one test -----------------------------------------------------------------------------


def _outlives_the_run(node: Any, spans: dict[str, str] | None) -> bool:
    """Whether this resource is still there after the run, so asking for it is not writing it.

    `spans={}` is the first pass, taken before any span is known: the spans are read off what the
    suite writes, so this answer cannot depend on them yet.
    """
    if spans == {}:
        return True
    if spans:
        return spans.get(name_of(node), lives.FOREVER) == lives.FOREVER
    return lives.of(node) == lives.FOREVER


def of_sentences(
    suite: Suite, sentences: list[Sentence], spans: dict[str, str] | None = None
) -> Footprint:
    """The footprint of a resolved list of sentences, in the order they are said."""
    reads: set[str] = set()
    writes: set[str] = set()
    opaque: list[str] = []
    named_last: list[str] = []

    for sentence in sentences:
        step = sentence.step
        if step is None:
            opaque.append(sentence.text)
            continue
        subjects = _subjects(suite, sentence) or (named_last if step.touch == WRITES else [])
        if step.touch == OPAQUE:
            opaque.append(sentence.text)
        for name in subjects:
            for node in graph.closure(suite.resource(name)):
                reads.add(name_of(node))
                # Anything that does not outlive the run is made for this test and taken away
                # again, so a test that asks for one is a test that writes it.
                if not _outlives_the_run(node, spans):
                    writes.add(name_of(node))
            if step.touch == WRITES:
                writes.add(name)
        reads |= _whole_kind(suite, sentence, step)
        if subjects:
            named_last = list(subjects)

    return Footprint(reads=frozenset(reads), writes=frozenset(writes), opaque=tuple(opaque))


def _subjects(suite: Suite, sentence: Sentence) -> list[str]:
    """Which declared resources this sentence names, read off the holes its step filled.

    A hole's value is compared against the declared names, so a resource named in a claim's text is
    only a subject where the step captured it.
    """
    return [
        value
        for value in sentence.values.values()
        if isinstance(value, str) and value in suite.instances
    ]


def _lineage(suite: Suite, name: str) -> set[str]:
    """A resource and everything it needs, by name. Reaching one reaches all of them."""
    return {name_of(node) for node in graph.closure(suite.resource(name))}


def _whole_kind(suite: Suite, sentence: Sentence, step: steps.Step) -> set[str]:
    """Every instance of a kind a sentence names without naming one of them.

    `When I list every todo_list` and `Then the environment has 2 todo_list` reach the set.
    """
    if step.touch != READS:
        return set()
    kind = sentence.values.get("kind", "")
    if not kind or _subjects(suite, sentence):
        return set()
    cls = next((one for name, one in suite.kinds.items() if fixture_name(name) == kind), None)
    if cls is None:
        return set()
    return {name for name, node in suite.instances.items() if type(node) is cls}


def of_scenario(
    suite: Suite, scenario: Scenario, phrases: dict[str, Any], spans: dict[str, str] | None = None
) -> Footprint:
    """The footprint of one scenario, with its phrases expanded and its sentences bound to steps."""
    try:
        expanded = phrase_reader.expand(scenario, phrases)
        sentences = [
            Sentence(keyword=line.keyword, text=line.text, line=line.number).resolve()
            for line in expanded.lines
        ]
    except (StepError, phrase_reader.PhraseError) as exc:
        return Footprint(unreadable=str(exc))
    return of_sentences(suite, sentences, spans)


def of_function(
    suite: Suite, asked: list[str] | set[str], spans: dict[str, str] | None = None
) -> Footprint:
    """The footprint of a Python test, from the resources it asks for by name."""
    reads: set[str] = set()
    writes: set[str] = set()
    for name in asked:
        if name not in suite.instances:
            continue
        for node in graph.closure(suite.resource(name)):
            reads.add(name_of(node))
            if not _outlives_the_run(node, spans):
                writes.add(name_of(node))
    return Footprint(reads=frozenset(reads), writes=frozenset(writes), opaque=(A_TEST_BODY,))


def arranged(suite: Suite, footprint: Footprint) -> list[str]:
    """The resources a footprint reaches, in declaration order."""
    return [name for name in suite.instances if name in footprint.touches]


# --- Laying out a run -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    """A run laid out: sets that can go at once, and the tests that go alone."""

    #: Each entry is a set of test identities that must stay together, and no two entries interfere.
    parallel: tuple[tuple[str, ...], ...] = ()
    #: Tests with an effect nothing declares. They run one at a time, with nothing else in flight.
    serial: tuple[str, ...] = ()
    #: Test identity to the one line saying what put it in `serial`.
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def width(self) -> int:
        """How many sets can be in flight at once."""
        return len(self.parallel)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "parallel": sum(len(group) for group in self.parallel),
            "serial": len(self.serial),
            "groups": len(self.parallel),
        }


def schedule(footprints: dict[str, Footprint]) -> Schedule:
    """Lay out a run so that two tests in different parallel sets cannot interfere.

    A test whose footprint is not sealed goes to `serial`, which runs with nothing beside it. The
    rest are grouped by the resources they write: any two tests where one writes what the other
    touches land in the same set.
    """
    sealed = {name: one for name, one in footprints.items() if one.sealed}
    serial = tuple(sorted(name for name in footprints if name not in sealed))
    reasons = {name: footprints[name].why_not_sealed for name in serial}

    home: dict[str, str] = {name: name for name in sealed}

    def root(name: str) -> str:
        while home[name] != name:
            home[name] = home[home[name]]
            name = home[name]
        return name

    def join(one: str, other: str) -> None:
        first, second = root(one), root(other)
        if first != second:
            home[second] = first

    touching: dict[str, list[str]] = {}
    for name, one in sealed.items():
        for resource in one.touches:
            touching.setdefault(resource, []).append(name)

    for resource, tests in touching.items():
        writers = [name for name in tests if resource in sealed[name].writes]
        if not writers:
            continue
        for other in tests[1:]:
            join(tests[0], other)

    grouped: dict[str, list[str]] = {}
    for name in sorted(sealed):
        grouped.setdefault(root(name), []).append(name)

    return Schedule(
        parallel=tuple(tuple(group) for _, group in sorted(grouped.items())),
        serial=serial,
        reasons=reasons,
    )


def shard(laid_out: Schedule, index: int, total: int) -> list[str]:
    """The tests belonging to one shard of a run, with no conflict set split across two.

    Sets are dealt out largest first, each to whichever shard is holding the fewest tests. A test
    that runs alone is its own set here: shards are separate runs, and what they must not do is
    take half of one set each.
    """
    if not 1 <= index <= total:
        raise ValueError(f"shard {index}/{total}: the index runs from 1 to {total}")
    sets = [*laid_out.parallel, *([one] for one in laid_out.serial)]
    buckets: list[list[str]] = [[] for _ in range(total)]
    for group in sorted(sets, key=len, reverse=True):
        if not group:
            continue
        smallest = min(range(total), key=lambda slot: (len(buckets[slot]), slot))
        buckets[smallest].extend(group)
    return sorted(buckets[index - 1])
