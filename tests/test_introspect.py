"""The introspection API: what it says can be said, and what it makes of the choices someone made.

Not scenarios, deliberately. A scenario describes something a person can watch happen — a page that
answers, a command that refuses, a resource that appears. This is a pure function of a discovery and
a catalog: hand it the same suite twice and it must produce the same answer, and every interesting
case is a *different* suite rather than a different action. There is nothing to watch.

That makes a table the honest description. Each row below is one shape of suite or one set of
choices, paired with the one thing that must be true of the answer — which is also how the module
itself is written, over `GENERIC_STEPS`, `COMPARISONS` and `MARKERS`.

What a *person* can watch — `atf serve --mcp` refusing when the SDK is not installed — is a scenario,
and lives in `specs/features/cli.feature`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atf.agent.introspect import (
    FROM_ATF,
    FROM_PHRASEBOOK,
    FROM_SUITE,
    NODE_SUBJECT,
    SLOT_SUBJECT,
    STEP_SUBJECT,
    TYPE_SUBJECT,
    Row,
    Surface,
    compose,
    describe,
    field_choices,
    make_row,
    offered_steps,
    reachable,
    subject_options,
    usable,
)
from atf.engine.status import PRESENT, ResourceStatus, Statuses
from atf.spec import steps as atf_steps
from atf.spec.steps import GENERIC_STEPS

# `Test` under another name: pytest tries to collect anything called `Test*` and warns.
from atf.suite.discovery import Discovery, Spec, StepDef
from atf.suite.discovery import Test as Collected

# The feature the fixture below binds to a steps module. Named, because which feature a scenario is
# being written into is what decides whether that module's steps are reachable at all.
FEATURE = "Lists"

STEPS_FILE = str(Path(atf_steps.__file__))


def generic_steps() -> list[StepDef]:
    """ATF's own vocabulary, as discovery reports it.

    Built from `GENERIC_STEPS` rather than written out, for the same reason the module under test
    derives everything from it: a copy of the vocabulary in the tests is a copy that goes stale.
    """
    return [
        StepDef(
            keyword=one.keyword,
            pattern=one.pattern,
            params=list(one.captures),
            file=STEPS_FILE,
            docstring=one.summary,
            needs=list(one.needs),
            produces=list(one.produces),
            needs_slot=one.needs_slot,
            takes_table=one.takes_table,
        )
        for one in GENERIC_STEPS
    ]


@pytest.fixture
def found(tmp_path) -> Discovery:
    """A suite with ATF's vocabulary, one step of its own, and one phrase."""
    module = tmp_path / "specs" / "steps" / "test_lists.py"
    spec = Spec(
        id="lists::a-list-is-shared",
        feature=FEATURE,
        scenario="A list is shared",
        file=str(tmp_path / "specs" / "features" / "lists.feature"),
    )
    return Discovery(
        specs=[spec],
        tests=[
            Collected(
                id="t",
                nodeid="specs/steps/test_lists.py::test_a",
                name="test_a",
                file=str(module),
                covers=spec.id,
            )
        ],
        steps=[
            *generic_steps(),
            StepDef(
                keyword="when",
                pattern="I invite a collaborator",
                file=str(module),
                docstring="Invite someone.",
                produces=["invitation"],
            ),
            StepDef(
                keyword="then",
                pattern="the invitation was accepted",
                file=str(tmp_path / "specs" / "phrasebook.yaml"),
                expands_to=['the invitation field "state" is "accepted"'],
                needs=["invitation"],
            ),
        ],
    )


@pytest.fixture
def surface(engine, found, tmp_path) -> Surface:
    return Surface(
        env="test",
        root=tmp_path,
        specs_dir=tmp_path / "specs",
        engine=engine,
        found=found,
        status=Statuses(
            {
                "accounts.primary": ResourceStatus(
                    PRESENT, record={"id": 7, "email": "primary@example.test"}
                )
            }
        ),
    )


def wordings(surface: Surface, feature: str = FEATURE) -> dict[str, dict]:
    """Every step wording a scenario in `feature` may use, by the wording itself."""
    described = describe(surface, feature)
    return {one["pattern"]: one for group in described["steps"].values() for one in group}


# ---- what can be said here ---------------------------------------------------


def test_describe_answers_in_sections_that_do_not_depend_on_the_vocabulary(surface):
    described = describe(surface)
    assert set(described) >= {
        "comparisons",
        "features",
        "markers",
        "phrases",
        "resource_types",
        "resources",
        "steps",
    }


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (atf_steps.EXISTS, FROM_ATF),
        (atf_steps.SLOT_FIELD_IS, FROM_ATF),
        ("I invite a collaborator", FROM_SUITE),
        ("the invitation was accepted", FROM_PHRASEBOOK),
    ],
)
def test_a_step_says_whose_vocabulary_it_belongs_to(surface, pattern, expected):
    """Whose word it is decides whether someone goes looking for Python behind it."""
    assert wordings(surface)[pattern]["defined_by"] == expected


@pytest.mark.parametrize(
    ("pattern", "key", "value"),
    [
        (atf_steps.ACT, "captures", ["action", "resource_type", "name"]),
        (atf_steps.ACT, "produces", ["result"]),
        (atf_steps.SLOT_FIELD_IS, "needs_slot", True),
        (atf_steps.SHAPE_IS, "takes_table", True),
        ("I invite a collaborator", "produces", ["invitation"]),
        ("the invitation was accepted", "needs", ["invitation"]),
    ],
)
def test_a_step_carries_what_decides_whether_a_scenario_may_use_it(surface, pattern, key, value):
    assert wordings(surface)[pattern][key] == value


def test_a_step_of_the_suites_own_is_offered_only_inside_the_feature_its_module_binds(surface):
    """The alternative is a scenario that composes cleanly and reports the step missing when run."""
    assert "I invite a collaborator" in wordings(surface, FEATURE)
    assert "I invite a collaborator" not in wordings(surface, feature="")


def test_a_phrase_says_what_it_stands_for(surface):
    """A phrase has no Python behind it, so what it means is the whole of what makes it trustable.

    Asked without naming a feature, because that is the case a phrase must survive: nothing declared
    it in a module, so a feature with no module of its own can still say it.
    """
    assert describe(surface)["phrases"] == [
        {
            "pattern": "the invitation was accepted",
            "keyword": "then",
            "means": ['the invitation field "state" is "accepted"'],
            "file": str(surface.specs_dir / "phrasebook.yaml"),
        }
    ]


def test_a_resource_carries_where_it_stands_and_what_its_fields_hold(surface):
    described = {one["id"]: one for one in describe(surface)["resources"]}
    assert described["accounts.primary"]["status"] == "present"
    fields = {one["name"]: one["current"] for one in described["accounts.primary"]["fields"]}
    assert fields["email"] == "primary@example.test"
    # Absent from the environment's record, so the answer is what the catalog declares — not a
    # guess, and said to be the catalog's by the source beside it.
    assert described["projects.alpha"]["status"] == "unknown"


def test_a_resource_type_carries_the_actions_declared_on_it(surface):
    described = {one["name"]: one for one in describe(surface)["resource_types"]}
    assert "delete" in described["account"]["actions"]
    assert described["lead"]["lifecycle"] == "ephemeral"
    assert described["widget"]["mode"] == "reference"


@pytest.mark.parametrize(
    ("declared_in", "binds", "visible"),
    [
        ("elsewhere/steps.py", None, True),  # outside the specs tree: a plugin's, visible always
        ("specs/conftest.py", None, True),  # a conftest, and no module named: offered
        ("specs/conftest.py", "specs/steps/test_a.py", True),  # a conftest above the module
        ("specs/steps/test_a.py", "specs/steps/test_a.py", True),  # its own module
        ("specs/steps/test_a.py", "specs/steps/test_b.py", False),  # somebody else's module
        ("specs/steps/test_a.py", None, False),  # nothing binds this feature yet
    ],
)
def test_a_step_is_offered_only_where_pytest_would_resolve_it(tmp_path, declared_in, binds, visible):
    """Step lookup is fixture lookup, and a step offered outside its module is a scenario that
    composes cleanly and then reports the step missing when it runs.
    """
    step = StepDef(keyword="when", pattern="I do it", file=str(tmp_path / declared_in))
    module = tmp_path / binds if binds else None
    assert reachable(step, module, tmp_path / "specs") is visible


def test_a_step_the_feature_cannot_reach_is_named_rather_than_hidden(surface, found, tmp_path):
    """The fix is a choice between two files, so both are named and neither is picked."""
    elsewhere = tmp_path / "specs" / "steps" / "test_other.py"
    found.steps.append(StepDef(keyword="when", pattern="I archive it", file=str(elsewhere)))
    assert describe(surface, FEATURE)["out_of_reach"] == ["test_other.py"]


@pytest.mark.parametrize(
    ("needs", "needs_slot", "held", "produced", "offered"),
    [
        ([], False, set(), set(), True),
        (["result"], False, set(), set(), False),
        (["result"], False, {"result"}, {"result"}, True),
        ([], True, {"account"}, set(), False),  # a Given's record is not a slot to claim about
        ([], True, {"result"}, {"result"}, True),
    ],
)
def test_a_step_is_offered_only_where_the_rows_above_it_have_fed_it(needs, needs_slot, held, produced, offered):
    step = StepDef(keyword="then", pattern="whatever", needs=needs, needs_slot=needs_slot)
    row = Row(index=1, keyword="then", held=held, produced=produced)
    assert usable(step, row) is offered


def test_what_a_claim_can_be_about_is_offered_resources_first(surface):
    """The order the groups come in is the order somebody reads them, so it is worth pinning.

    An author looking for "check this field" takes the first plausible thing they see. If that is a
    step the project had to write, they conclude that assertions are something you write — and they
    are not, for anything in the catalog.

    Asserted on the options rather than on the page. `test_compose.py` used to slice the rendered
    HTML from `name="subject_2"` and compare `.index()` of one group label against another, which is
    a claim about where bytes fell in a template. The order is decided here.
    """
    row = Row(index=1, keyword="then", held={"result"}, produced={"result"})
    groups = [option.group for option in subject_options(surface, offered_steps(surface, FEATURE)["then"], row)]
    seen = list(dict.fromkeys(groups))

    assert seen[0] == "A resource", f"a resource is not offered first; the order is {seen}"
    # Whatever the suite had to write for itself — a step, or a phrase over steps that needed none —
    # comes after everything the catalog already knows. Named as the category rather than as one
    # label, because which of the two a suite has is a fact about that suite.
    written = [group for group in seen if "suite" in group]
    assert written, f"nothing the suite wrote is offered at all; the order is {seen}"
    assert seen.index("A resource") < min(seen.index(group) for group in written)
    # Every group is contiguous: the template only prints a heading when the group changes, so a
    # group appearing twice would render as two headings with the same name.
    assert len(seen) == len({*seen}), f"a group is split in two: {groups}"


# ---- these choices, and the Gherkin they mean --------------------------------


GIVEN_PRIMARY = {"keyword": "given", "resource_type": "account", "resource_name": "primary"}


@pytest.mark.parametrize(
    ("rows", "line"),
    [
        (
            [GIVEN_PRIMARY, {"keyword": "then", "subject": f"{NODE_SUBJECT}accounts.primary", "compare": "exists"}],
            '    Then the account "primary" exists',
        ),
        (
            [
                GIVEN_PRIMARY,
                {
                    "keyword": "then",
                    "subject": f"{NODE_SUBJECT}accounts.primary",
                    "aspect": "email",
                    "compare": "is",
                    "target": "primary@example.test",
                },
            ],
            '    Then the account "primary" field "email" is "primary@example.test"',
        ),
        (
            [
                GIVEN_PRIMARY,
                {"keyword": "then", "subject": f"{TYPE_SUBJECT}account", "compare": "count", "target": "2"},
            ],
            "    Then the environment has 2 account",
        ),
        (
            [
                GIVEN_PRIMARY,
                {"keyword": "when", "pattern": "I invite a collaborator"},
                {
                    "keyword": "then",
                    "subject": f"{SLOT_SUBJECT}invitation",
                    "aspect": "state",
                    "compare": "result-is",
                    "target": "sent",
                },
            ],
            '    Then the invitation field "state" is "sent"',
        ),
        (
            [
                GIVEN_PRIMARY,
                {"keyword": "when", "pattern": "I invite a collaborator"},
                {
                    "keyword": "then",
                    "subject": f"{STEP_SUBJECT}the invitation was accepted",
                    "pattern": "the invitation was accepted",
                },
            ],
            "    Then the invitation was accepted",
        ),
    ],
)
def test_four_choices_compose_the_line_they_mean(surface, rows, line):
    made = compose(surface, rows, title="A behaviour", feature=FEATURE)
    assert made.ready, made.problems
    assert line in made.gherkin.splitlines()


def test_a_repeated_keyword_is_written_as_and(surface):
    made = compose(
        surface,
        [
            GIVEN_PRIMARY,
            {"keyword": "given", "resource_type": "project", "resource_name": "alpha"},
            {"keyword": "then", "subject": f"{NODE_SUBJECT}accounts.primary", "compare": "exists"},
        ],
        title="Two resources",
        feature=FEATURE,
    )
    assert made.gherkin.splitlines()[1:3] == [
        '    Given the account "primary"',
        '    And the project "alpha"',
    ]


@pytest.mark.parametrize(
    ("rows", "title", "said"),
    [
        ([], "A behaviour", "A scenario with no steps asserts nothing"),
        ([GIVEN_PRIMARY], "A behaviour", "a scenario needs at least one Then"),
        (
            [GIVEN_PRIMARY, {"keyword": "then", "subject": f"{NODE_SUBJECT}accounts.primary", "compare": "exists"}],
            "",
            "The scenario needs a title",
        ),
        (
            [{"keyword": "given", "resource_type": "account", "resource_name": "nobody"}],
            "A behaviour",
            "the catalog declares no account called 'nobody'",
        ),
        (
            [{"keyword": "when", "pattern": "I do something nobody defined"}],
            "A behaviour",
            "no when step this feature can reach is worded",
        ),
        (
            [
                {
                    "keyword": "then",
                    "subject": f"{SLOT_SUBJECT}result",
                    "aspect": "state",
                    "compare": "result-is",
                    "target": "sent",
                }
            ],
            "A behaviour",
            "nothing above this puts result on the context",
        ),
        (
            [
                GIVEN_PRIMARY,
                {
                    "keyword": "then",
                    "pattern": atf_steps.SHAPE_IS,
                    "params": {"resource_type": "account", "name": "primary"},
                },
            ],
            "A behaviour",
            "add a field and what it holds",
        ),
        (
            [GIVEN_PRIMARY, {"keyword": "sideways", "pattern": "anything"}],
            "A behaviour",
            "a scenario is written in given, when, then",
        ),
    ],
)
def test_a_choice_that_does_not_exist_comes_back_as_the_reason_it_does_not(surface, rows, title, said):
    """The refusals are the valuable half: this is the whole of why an agent here cannot invent."""
    made = compose(surface, rows, title=title, feature=FEATURE)
    assert not made.ready
    assert any(said in problem for problem in made.problems), made.problems


def test_a_table_is_written_under_its_step_with_its_columns_aligned(surface):
    made = compose(
        surface,
        [
            GIVEN_PRIMARY,
            {
                "keyword": "then",
                "pattern": atf_steps.SHAPE_IS,
                "params": {"resource_type": "account", "name": "primary"},
                "table": [["email", "primary@example.test"], ["id", "#int"]],
            },
        ],
        title="A shape",
        feature=FEATURE,
    )
    assert made.ready, made.problems
    assert made.gherkin.splitlines()[-2:] == [
        "      | email | primary@example.test |",
        "      | id    | #int                 |",
    ]


@pytest.mark.parametrize(
    ("compare", "aspect", "subject", "target"),
    [
        ("exists", "", f"{NODE_SUBJECT}accounts.primary", ""),
        ("is", "email", f"{NODE_SUBJECT}accounts.primary", "primary@example.test"),
        ("count", "", f"{TYPE_SUBJECT}account", "2"),
    ],
)
def test_a_claim_reads_back_as_the_choices_that_wrote_it(surface, compare, aspect, subject, target):
    """A scenario written by hand has to arrive at the same four choices, or the two surfaces
    disagree about a file they both claim to describe.
    """
    offered = offered_steps(surface, FEATURE)
    chosen = {"subject": subject, "aspect": aspect, "compare": compare, "target": target}
    forward = make_row(0, "then", chosen, offered, surface.catalog)
    back = make_row(0, "then", {"pattern": forward.pattern, "params": forward.values}, offered, surface.catalog)
    assert (back.subject, back.aspect, back.compare, back.target) == (subject, aspect, compare, target)


# ---- the fields of a resource ------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "field", "current", "source"),
    [
        (
            ResourceStatus(PRESENT, record={"email": "read@example.test"}),
            "email",
            "read@example.test",
            "on the record in this environment",
        ),
        (ResourceStatus(), "email", "primary@example.test", "declared in the catalog"),
        (ResourceStatus(), "id", "", "the identity field, assigned when it is created"),
        (ResourceStatus(PRESENT, record={"done": False}), "done", "false", "on the record in this environment"),
        (
            ResourceStatus(PRESENT, record={"tags": ["a", "b"]}),
            "tags",
            '["a", "b"]',
            "on the record in this environment",
        ),
    ],
)
def test_a_field_is_offered_with_what_it_holds_and_where_that_came_from(engine, entry, field, current, source):
    """Choosing `done` while the interface says it is currently `false` is writing an assertion with
    the answer in front of you; choosing from bare names is guessing.
    """
    node = engine.nodes["accounts.primary"]
    choice = next(one for one in field_choices(node, entry) if one.name == field)
    assert (choice.current, choice.source) == (current, source)
