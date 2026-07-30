"""What a suite says about itself: its scenarios, tests, fixtures and steps."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...spec.patterns import ANY_KEYWORD, GIVEN, PROVISION


@dataclass
class Step:
    keyword: str
    text: str
    resources: list[str] = field(default_factory=list)
    # The rows written under the step, if it carries a table. `Given the workspace "bare" but:` says
    # nothing at all without them, so anything rendering a step back out — the cockpit, and now
    # [`atf docs`](docs.py) — was showing half a sentence. Empty for the steps that take no table,
    # which is most of them.
    table: list[list[str]] = field(default_factory=list)

@dataclass
class Spec:
    id: str
    feature: str
    scenario: str
    # The `Rule:` this scenario sits under, if the feature groups its scenarios that way. Gherkin's
    # keyword for Example Mapping's middle card: a business rule, with the examples that show it.
    # Empty for a feature that does not use them, which is most.
    rule: str = ""
    narrative: str = ""
    file: str = ""
    line: int = 0
    steps: list[Step] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    skipped: bool = False
    test_ids: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)

@dataclass
class Question:
    """Something nobody could answer, written down beside the rule it is about.

    Written as a comment, `# ? …`, under the `Rule:` it belongs to, or under the feature where there
    is none.
    """

    ask: str
    feature: str = ""
    rule: str = ""
    file: str = ""
    line: int = 0

@dataclass
class Test:
    id: str
    nodeid: str
    name: str
    params: str = ""
    file: str = ""
    covers: str = ""
    resources: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    skipped: bool = False

@dataclass
class Fixture:
    name: str
    doc: str = ""
    scope: str = "function"
    used_by: list[str] = field(default_factory=list)
    generated: bool = False

@dataclass
class StepDef:
    """One step definition the project registers — the vocabulary a scenario may be written in.

    `pattern` is the parser's raw expression exactly as the author wrote it, so it is both what a
    picker shows and what a composed step's wording is built from.

    `needs` and `produces` are what the step reads from and writes to the per-scenario context, read
    out of its source: they are what lets a surface offer only the steps a scenario can use.
    """

    keyword: str
    pattern: str
    params: list[str] = field(default_factory=list)
    file: str = ""
    docstring: str = ""
    needs: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    # Whether the step reads the slot its own wording names. Nothing can be listed in `needs` for
    # one of these: which slot it needs is a choice whoever composes it has not made yet.
    needs_slot: bool = False
    # Whether the step carries a table under it, which a picker cannot compose.
    takes_table: bool = False
    # For a [phrase](phrasebook.py), the steps it stands for. Empty for an ordinary step. A phrase
    # needs and produces whatever they do, so this is where those are read from.
    expands_to: list[str] = field(default_factory=list)

    @property
    def phrase(self) -> bool:
        return bool(self.expands_to)

@dataclass
class Discovery:
    """Everything a suite says about itself, with the joins between the six lists made once.

    A page render asks these questions per scenario and per resource, so they are answered from an
    index built when discovery finishes — a scan per question is O(specs x tests) a page.
    """

    specs: list[Spec] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    tests: list[Test] = field(default_factory=list)
    fixtures: list[Fixture] = field(default_factory=list)
    steps: list[StepDef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.index()

    def index(self) -> None:
        """Build the lookups. Called again by `discover`, which fills the lists in as it goes."""
        self._specs = {spec.id: spec for spec in self.specs}
        self._tests = {test.id: test for test in self.tests}
        self._fixtures = {fixture.name: fixture for fixture in self.fixtures}
        self._tests_by_spec: dict[str, list[Test]] = {}
        self._tests_by_resource: dict[str, list[Test]] = {}
        self._specs_by_resource: dict[str, list[Spec]] = {}
        for test in self.tests:
            self._tests_by_spec.setdefault(test.covers, []).append(test)
            for node_id in test.resources:
                self._tests_by_resource.setdefault(node_id, []).append(test)
        for spec in self.specs:
            for node_id in spec.resources:
                self._specs_by_resource.setdefault(node_id, []).append(spec)

    def steps_for(self, keyword: str) -> list[StepDef]:
        """The definitions a picker for one keyword should offer.

        A `@step` registered without a type matches any keyword, so it is offered under all three.
        ATF's generic provisioning step is offered as `given` only: `When the account "primary"` is
        legal Gherkin but never what anyone means, and a composer that offers it twice teaches the
        wrong model.
        """
        wanted = keyword.lower()
        offered = [step for step in self.steps if step.keyword in {wanted, ANY_KEYWORD}]
        if wanted == GIVEN:
            return offered
        return [step for step in offered if step.pattern != PROVISION]

    def spec(self, spec_id: str) -> Spec | None:
        return self._specs.get(spec_id)

    def test(self, test_id: str) -> Test | None:
        return self._tests.get(test_id)

    def fixture(self, name: str) -> Fixture | None:
        return self._fixtures.get(name)

    def tests_for_spec(self, spec_id: str) -> list[Test]:
        return self._tests_by_spec.get(spec_id, [])

    def tests_for_resource(self, node_id: str) -> list[Test]:
        return self._tests_by_resource.get(node_id, [])

    def specs_for_resource(self, node_id: str) -> list[Spec]:
        return self._specs_by_resource.get(node_id, [])

    def scenario_names(self) -> dict[str, str]:
        """`{nodeid: the scenario it runs, with its Examples row}` — a run's rows, named."""
        named: dict[str, str] = {}
        for test in self.tests:
            spec = self.spec(test.covers) if test.covers else None
            if spec is None or not spec.scenario:
                continue
            named[test.nodeid] = f"{spec.scenario} [{test.params}]" if test.params else spec.scenario
        return named

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "untitled"
