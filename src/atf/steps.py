"""The read-and-compare steps, so that every suite stops writing them again.

ATF used to define exactly one step — `Given the {resource_type} "{name}"` — and every project
re-wrote the same family of assertions on top of it: does this exist, has it gone, is this field
that value. Those are not domain knowledge. They are a record read through an adapter ATF already
has and compared with a value the author already wrote, and the comparison is the same one `find`
makes when it decides whether a resource is already there.

Two decisions shape the whole module.

**A step resolves its resource from the catalog and reads it live.** It never consults `context`.
That is what makes an assertion independent of the action before it: `When I complete the task` can
be hand-written code hitting a real service, and the `Then` after it is still generic, because it
goes back to the backend and looks. The three parts of a test stop being entangled.

**Nothing here decides what a record contains.** The scenario names the field; ATF reads that field
and compares it with the written value. It requires no field to exist, reads nothing into a field's
name, and interprets no value. That is the same act as `natural_key: email` in the catalog — see
[the model](../../docs/explanation/the-model.md).

An ephemeral resource is the one exception to reading live, and it is forced: an ephemeral resource
is never looked up — that is what ephemeral means — so the record this scenario built is the only
one there is.

An instance a scenario asked to have to itself (`Given a fresh …`) is deliberately *not* a second
exception. It was given a natural key of its own precisely so that it can be looked up, so every
claim below reads it back the way it reads back any other resource — and `When I delete it` followed
by `Then it is gone` means what it says about the copy, not about the resource everybody shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pytest_bdd import parsers, then, when

from .adapters import Record, can_browse
from .adapters.command import CommandAdapter
from .catalog import Node, find_node, key_criteria, natural_keys
from .compare import (
    MARKERS,
    MISSING,
    Uncontainable,
    describe,
    field_matches,
    is_empty,
    matches,
    written_contains,
    written_matches,
)
from .context import RESULT, Slot, ephemeral_record
from .materializer import EPHEMERAL, Materializer, ProvisioningError, ScopeRequired
from .placeholders import Unresolved
from .records import as_records

# ---- the vocabulary --------------------------------------------------------

# ATF's own provisioning step, defined in `plugin.py` beside the factories it drives. It is listed
# here because this table is what the composer reads to know which of a step's parameters it can
# offer a real choice for, and that is as true of the Given as of the assertions.
PROVISION = 'the {resource_type} "{name}"'
PROVISION_VARIED = 'the {resource_type} "{name}" but:'

# The same resource, isolated. `the todo_list "groceries"` is the shared one — found once, left in
# place, the same list for every scenario that names it. `a fresh todo_list "groceries"` is an
# instance of that node this scenario alone holds, torn down with it, and the catalog says nothing
# about it: isolation is a thing a *scenario* needs, and the type it needs one of is often the same
# type another scenario is happy to share.
#
# Read as English rather than as a lifecycle keyword. "A fresh one" is what a person says about a
# glass, and the article is what carries the difference from "the" — the one everybody uses.
PROVISION_FRESH = 'a fresh {resource_type} "{name}"'
PROVISION_FRESH_VARIED = 'a fresh {resource_type} "{name}" but:'

EXISTS = 'the {resource_type} "{name}" exists'
GONE = 'the {resource_type} "{name}" is gone'
FIELD_IS = 'the {resource_type} "{name}" field "{field}" is "{value}"'
FIELD_IS_NOT = 'the {resource_type} "{name}" field "{field}" is not "{value}"'
FIELD_CONTAINS = 'the {resource_type} "{name}" field "{field}" contains "{value}"'
FIELD_LACKS = 'the {resource_type} "{name}" field "{field}" does not contain "{value}"'
FIELD_EMPTY = 'the {resource_type} "{name}" field "{field}" is empty'
FIELD_NOT_EMPTY = 'the {resource_type} "{name}" field "{field}" is not empty'

# How many of a type an environment holds. The one claim that is about a resource *type* rather
# than about one resource, because "nothing was created the second time" is a claim about a
# population and there is nothing to name.
COUNT = "the environment has {count:d} {resource_type}"

# Whole-shape claims. A record has a shape, and checking it a field at a time costs a line each and
# says nothing about the record as a whole. A table says the shape in one claim, and a `#marker`
# says what *kind* of thing a field must hold where the value itself is not the point — an id the
# backend assigned, a timestamp that was `now`.
SHAPE_IS = 'the {resource_type} "{name}" is:'
SLOT_SHAPE_IS = "the {slot:w} is:"

# The generic `When`. Until this existed the framework could *read* a system and never act on one:
# `find` and `create` were reachable from Gherkin, `delete` and `browse` from nothing at all, and
# every action a project needed was hand-written — including the ones the adapter already knew how
# to perform. An adapter offers mechanical verbs, the catalog names a domain action in terms of
# them, and this says the domain action.
#
# `{action:w}` is one word, because an action is a name the catalog chose. That is also what keeps
# this from swallowing a project's own `When`: `I list the projects of the account` names no
# instance in quotes, and `I run "atf seed local"` has no ` the ` in it.
ACT = 'I {action:w} the {resource_type} "{name}"'
LIST_EVERY = "I list every {resource_type}"

# Running a command, said the way a person writes one. The command line is the whole of it: a
# reader knows what `atf seed local` means and would have to be taught what a program and a list of
# arguments to append to it meant. What came back lands on `result`, so every claim already in this
# module applies to it.
RUN = 'I run "{command}"'

# The four claims about what a step produced name the slot they are about, rather than assuming the
# one called `result`. `Context` has always described every slot it holds; until these patterns
# named one, a scenario with two actions could compare neither of them with the other.
#
# `{slot:w}` is letters, numbers and underscore — no spaces, no quotes. That is what keeps these
# patterns from also matching `the todo_list "groceries" field "owner_id" is "…"`: a resource claim
# always names its instance between quotes, and a slot claim never does.
SLOT_CONTAINS = 'the {slot:w} contains the {resource_type} "{name}"'
SLOT_LACKS = 'the {slot:w} does not contain the {resource_type} "{name}"'
SLOT_FIELD_IS = 'the {slot:w} field "{field}" is "{value}"'
SLOT_FIELD_IS_NOT = 'the {slot:w} field "{field}" is not "{value}"'
SLOT_FIELD_CONTAINS = 'the {slot:w} field "{field}" contains "{value}"'
SLOT_FIELD_LACKS = 'the {slot:w} field "{field}" does not contain "{value}"'
SLOT_FIELD_EMPTY = 'the {slot:w} field "{field}" is empty'
SLOT_FIELD_NOT_EMPTY = 'the {slot:w} field "{field}" is not empty'

# A capture's parameter name is also what it means, because ATF chose both. A project's step may
# well have a parameter called `field` that means something else entirely, which is why only the
# patterns in this table are read this way.
TYPE, NAME, FIELD, VALUE, SLOT, COUNT_OF = "resource_type", "name", "field", "value", "slot", "count"
ACTION, COMMAND = "action", "command"

# How many records a count claim will read before it gives up. A listing that hits the cap is
# reported rather than counted: a number that might be the cap is not an answer.
LISTING_LIMIT = 1000


@dataclass(frozen=True)
class GenericStep:
    """One step ATF itself defines, and what its parameters mean."""

    keyword: str
    pattern: str
    summary: str
    captures: tuple[str, ...]
    # What the step reads from the context. Declared rather than read out of the source below,
    # because these reach it through `getattr` and an attribute is what source analysis can see.
    needs: tuple[str, ...] = ()
    # What it writes to the context. Declared for the same reason `needs` is: these are ATF's own
    # steps, and their decorators name a constant rather than a literal, so nothing reading the
    # source can pair a wording with what it does.
    produces: tuple[str, ...] = ()
    # Whether the step reads the slot it names, rather than a slot fixed in advance. Nothing can be
    # listed in `needs` for these — which slot they need is a choice the author has not made yet —
    # so what an interface checks is that the slot they *did* name is one the scenario holds.
    needs_slot: bool = False
    # Whether the step carries a table under it. A picker that offers one has offered a line it
    # cannot finish, so it does not offer them — they are written by hand, or in text mode.
    takes_table: bool = False


GENERIC_STEPS: tuple[GenericStep, ...] = (
    GenericStep(
        "given",
        PROVISION,
        "Make this resource exist here, and everything it depends on first.",
        (TYPE, NAME),
    ),
    GenericStep(
        "given",
        PROVISION_VARIED,
        "The same, with some of its body written differently for this scenario only.",
        (TYPE, NAME),
        takes_table=True,
    ),
    GenericStep(
        "given",
        PROVISION_FRESH,
        "Make one of these that belongs to this scenario alone, and goes when it does.",
        (TYPE, NAME),
    ),
    GenericStep(
        "given",
        PROVISION_FRESH_VARIED,
        "The same, with some of its body written differently for this scenario only.",
        (TYPE, NAME),
        takes_table=True,
    ),
    GenericStep(
        "when",
        ACT,
        "Do to this resource what its type says that action means.",
        (ACTION, TYPE, NAME),
        produces=(RESULT,),
    ),
    GenericStep(
        "when",
        RUN,
        "Run a command line, and keep what it said.",
        (COMMAND,),
        produces=(RESULT,),
    ),
    GenericStep(
        "when",
        LIST_EVERY,
        "Read back every resource of this type the environment holds.",
        (TYPE,),
        produces=(RESULT,),
    ),
    GenericStep(
        "then",
        EXISTS,
        "Read this resource back from the environment and require it to be there.",
        (TYPE, NAME),
    ),
    GenericStep(
        "then",
        GONE,
        "Read this resource back and require it to be absent — what a deletion is checked with.",
        (TYPE, NAME),
    ),
    GenericStep(
        "then",
        FIELD_IS,
        "Read this resource back and compare one of its fields with a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_IS_NOT,
        "Read this resource back and require one of its fields to differ from a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_CONTAINS,
        "Read this resource back and require one of its fields to hold a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_LACKS,
        "Read this resource back and require one of its fields not to hold a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_EMPTY,
        "Read this resource back and require one of its fields to hold nothing.",
        (TYPE, NAME, FIELD),
    ),
    GenericStep(
        "then",
        FIELD_NOT_EMPTY,
        "Read this resource back and require one of its fields to hold something.",
        (TYPE, NAME, FIELD),
    ),
    GenericStep(
        "then",
        COUNT,
        "Count what this environment holds of a resource type.",
        (COUNT_OF, TYPE),
    ),
    GenericStep(
        "then",
        SHAPE_IS,
        "Read this resource back and compare a whole table of its fields at once.",
        (TYPE, NAME),
        takes_table=True,
    ),
    GenericStep(
        "then",
        SLOT_CONTAINS,
        "Require the records a step put on the context to include this resource.",
        (SLOT, TYPE, NAME),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_LACKS,
        "Require the records a step put on the context not to include this resource.",
        (SLOT, TYPE, NAME),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_IS,
        "Compare one field of what a step put on the context with a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_IS_NOT,
        "Require one field of what a step put on the context to differ from a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_CONTAINS,
        "Require one field of what a step put on the context to hold a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_LACKS,
        "Require one field of what a step put on the context not to hold a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_EMPTY,
        "Require one field of what a step put on the context to hold nothing.",
        (SLOT, FIELD),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_NOT_EMPTY,
        "Require one field of what a step put on the context to hold something.",
        (SLOT, FIELD),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_SHAPE_IS,
        "Compare a whole table of fields against what a step put on the context.",
        (SLOT,),
        needs_slot=True,
        takes_table=True,
    ),
)

_BY_PATTERN = {step.pattern: step for step in GENERIC_STEPS}


def generic(pattern: str) -> GenericStep | None:
    """The entry for a step ATF defines, or `None` for one the project defines."""
    return _BY_PATTERN.get(pattern)


# ---- the same steps, said as a claim ----------------------------------------
#
# A pattern is how ATF matches a line; it is not how anyone thinks. What someone means is a claim
# about something: *this* resource, *that* field of it, compared *this way*, against *that*. The
# table below is the same six steps read that way round, and it is the whole vocabulary — kept
# small on purpose, because every entry is a thing ATF must be able to decide, and a comparison
# language that grows without a decision procedure behind it is a schema language nobody asked for.

RESOURCE, SLOT_OF, TYPE_OF = "resource", "slot", "type"


@dataclass(frozen=True)
class Comparison:
    """One claim an assertion can make, and the wording ATF writes for it."""

    key: str
    label: str
    pattern: str
    # What the claim is about: a resource in the catalog, a slot a step above put on the context,
    # or a whole resource type — which is what a claim about how many there are has to be about.
    subject: str
    # Whether it names a field of that subject, and what it is compared against.
    field: bool = False
    target: str = ""  # "" | "value" | "resource"
    # Which of the pattern's captures the target is written into. Every claim compared against a
    # written value uses `value`; a count writes a number, and calling that capture `value` in the
    # spec text would read as a value the resource holds rather than as how many there are.
    value_capture: str = VALUE


COMPARISONS: tuple[Comparison, ...] = (
    Comparison("exists", "exists", EXISTS, RESOURCE),
    Comparison("gone", "is gone", GONE, RESOURCE),
    Comparison("is", "is", FIELD_IS, RESOURCE, field=True, target="value"),
    Comparison("is-not", "is not", FIELD_IS_NOT, RESOURCE, field=True, target="value"),
    Comparison("holds", "contains", FIELD_CONTAINS, RESOURCE, field=True, target="value"),
    Comparison("holds-not", "does not contain", FIELD_LACKS, RESOURCE, field=True, target="value"),
    Comparison("empty", "is empty", FIELD_EMPTY, RESOURCE, field=True),
    Comparison("not-empty", "is not empty", FIELD_NOT_EMPTY, RESOURCE, field=True),
    Comparison("contains", "contains", SLOT_CONTAINS, SLOT_OF, target="resource"),
    Comparison("lacks", "does not contain", SLOT_LACKS, SLOT_OF, target="resource"),
    Comparison("result-is", "is", SLOT_FIELD_IS, SLOT_OF, field=True, target="value"),
    Comparison("result-is-not", "is not", SLOT_FIELD_IS_NOT, SLOT_OF, field=True, target="value"),
    Comparison("result-holds", "contains", SLOT_FIELD_CONTAINS, SLOT_OF, field=True, target="value"),
    Comparison("result-holds-not", "does not contain", SLOT_FIELD_LACKS, SLOT_OF, field=True, target="value"),
    Comparison("result-empty", "is empty", SLOT_FIELD_EMPTY, SLOT_OF, field=True),
    Comparison("result-not-empty", "is not empty", SLOT_FIELD_NOT_EMPTY, SLOT_OF, field=True),
    Comparison("count", "how many there are", COUNT, TYPE_OF, target="value", value_capture=COUNT_OF),
)

_BY_KEY = {item.key: item for item in COMPARISONS}
_BY_CLAIM = {item.pattern: item for item in COMPARISONS}


def comparison(key: str) -> Comparison | None:
    return _BY_KEY.get(key)


def claim_of(pattern: str) -> Comparison | None:
    """The claim a generic pattern makes, so a written scenario reads back into the same choices."""
    return _BY_CLAIM.get(pattern)


def comparisons_for(subject: str, on_field: bool) -> list[Comparison]:
    """What can be claimed about this subject — about the thing itself, or about a field of it."""
    return [
        item for item in COMPARISONS if item.subject == subject and item.field == on_field
    ]


# ---- the steps -------------------------------------------------------------


@when(parsers.parse(ACT))
def _(request: pytest.FixtureRequest, context: Any, action: str, resource_type: str, name: str) -> None:
    """Do to this resource what its type says that action means."""
    engine, node = _node(request, resource_type, name)
    known = engine.actions(resource_type)
    if action not in known:
        pytest.fail(
            f"{resource_type} declares no action {action!r} (it offers: {', '.join(known)}). "
            "Declare it under `actions:` on the type, or write a step of your own for it."
        )

    record = read(engine, node, context)
    if record is None:
        pytest.fail(f"{_absent(engine, node)} There is nothing to {action}.")

    try:
        produced = engine.act(node, record, action)
    except ProvisioningError as exc:
        pytest.fail(str(exc))
    # What an action gave back, for a scenario that wants to claim something about it. A system
    # that says nothing useful leaves the record the action was performed on, so there is always
    # something to talk about — and the claims after it read the resource back anyway.
    context.result = produced if produced is not None else record


@when(parsers.parse(RUN))
def _(request: pytest.FixtureRequest, context: Any, command: str) -> None:
    """Run a command line, and keep what it said."""
    engine: Materializer = request.getfixturevalue("materializer")
    runners = [one for one in engine.adapters.values() if isinstance(one, CommandAdapter)]
    if not runners:
        pytest.fail(
            "this step runs a command, and this environment configures no `command` system. "
            "Add one under `environments.<env>.adapters`."
        )
    if len(runners) > 1:
        pytest.fail("more than one `command` system is configured here, so ATF cannot tell which to use.")
    try:
        context.result = runners[0].run(command)
    except ValueError as exc:
        pytest.fail(str(exc))


@when(parsers.parse(LIST_EVERY))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str) -> None:
    """Read back every resource of this type the environment holds."""
    engine: Materializer = request.getfixturevalue("materializer")
    context.result = _listing(engine, resource_type, doing="list")


@then(parsers.parse(EXISTS))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str) -> None:
    """Read this resource back from the environment and require it to be there."""
    engine, node = _node(request, resource_type, name)
    if read(engine, node, context) is None:
        pytest.fail(_absent(engine, node))


@then(parsers.parse(GONE))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str) -> None:
    """Read this resource back and require it to be absent — what a deletion is checked with."""
    engine, node = _node(request, resource_type, name)
    if node["lifecycle"] == EPHEMERAL:
        pytest.fail(
            f"{node['id']} is ephemeral, so ATF never looks one up and cannot tell whether it is gone. "
            "Assert on the backend directly in a step of your own."
        )
    record = read(engine, node, context)
    if record is not None:
        pytest.fail(
            f"{node['id']} is still in {engine.env}: {node['id_field']}="
            f"{record.get(node['id_field'])!r} matches what the catalog declares."
        )


@then(parsers.parse(FIELD_IS))
def _(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str, value: str
) -> None:
    """Read this resource back and compare one of its fields with a value."""
    actual = _field(request, context, resource_type, name, field)
    if not written_matches(actual, value):
        pytest.fail(f"{resource_type} {name!r} field {field!r} is {describe(actual)}, not {describe(value)}")


@then(parsers.parse(FIELD_IS_NOT))
def _(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str, value: str
) -> None:
    """Read this resource back and require one of its fields to differ from a value."""
    actual = _field(request, context, resource_type, name, field)
    if written_matches(actual, value):
        pytest.fail(f"{resource_type} {name!r} field {field!r} is {describe(actual)}, which is what it must not be")


@then(parsers.parse(FIELD_CONTAINS))
def _(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str, value: str
) -> None:
    """Read this resource back and require one of its fields to hold a value."""
    actual = _field(request, context, resource_type, name, field)
    if not _contains(actual, value):
        pytest.fail(f"{resource_type} {name!r} field {field!r} is {describe(actual)}, which does not hold {value!r}")


@then(parsers.parse(FIELD_LACKS))
def _(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str, value: str
) -> None:
    """Read this resource back and require one of its fields not to hold a value."""
    actual = _field(request, context, resource_type, name, field)
    if _contains(actual, value):
        pytest.fail(f"{resource_type} {name!r} field {field!r} is {describe(actual)}, which holds {value!r}")


@then(parsers.parse(FIELD_EMPTY))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str) -> None:
    """Read this resource back and require one of its fields to hold nothing."""
    actual = _field(request, context, resource_type, name, field)
    if not is_empty(actual):
        pytest.fail(f"{resource_type} {name!r} field {field!r} is {describe(actual)}, not empty")


@then(parsers.parse(FIELD_NOT_EMPTY))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str) -> None:
    """Read this resource back and require one of its fields to hold something."""
    actual = _field(request, context, resource_type, name, field)
    if is_empty(actual):
        pytest.fail(f"{resource_type} {name!r} field {field!r} is {describe(actual)}, which is empty")


@then(parsers.parse(SHAPE_IS))
def _(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, datatable: Any = None
) -> None:
    """Read this resource back and compare a whole table of its fields at once."""
    engine, node = _node(request, resource_type, name)
    record = read(engine, node, context)
    if record is None:
        pytest.fail(_absent(engine, node))
    _shape(record, datatable, f"{resource_type} {name!r}", engine)


@then(parsers.parse(SLOT_SHAPE_IS))
def _(request: pytest.FixtureRequest, context: Any, slot: str, datatable: Any = None) -> None:
    """Compare a whole table of fields against what a step put on the context."""
    records = _slot(context, slot)
    if len(records) != 1:
        pytest.fail(
            f"{slot} holds {len(records)} records, and a shape needs one. "
            f'Use `the {slot} contains the <type> "<name>"` for a listing.'
        )
    _shape(records[0], datatable, slot, request.getfixturevalue("materializer"))


def _shape(record: Record, datatable: Any, subject: str, engine: Materializer) -> None:
    """Compare a whole table of field/value rows against one record.

    **The table says what must match, not what may exist.** A field the table does not mention is
    not looked at — a record carries ids, timestamps and half a dozen things a scenario has no
    opinion about, and requiring it to list them all would make every table a maintenance burden
    and every backend change a hundred red scenarios. `#absent` is how a scenario says a field must
    *not* be there, which is the only case the looser reading would otherwise lose.
    """
    __tracebackhide__ = True
    wrong: list[str] = []
    for field, written in _rows(datatable, subject):
        # `${...}` resolves here rather than in the plugin's hook: a table's cells never reach it,
        # because pytest-bdd hands them over as one `datatable` argument rather than as values.
        try:
            expected = str(engine.resolve(written))
        except Unresolved as exc:
            pytest.fail(f"{subject}: {exc}")
        actual = record.get(field, MISSING)
        if not field_matches(actual, expected):
            shown = "not there at all" if actual is MISSING else describe(actual)
            wrong.append(f"  {field}: {shown}, not {_wanted(expected)}")

    if wrong:
        pytest.fail(f"{subject} is not the shape this scenario says:\n" + "\n".join(wrong))


def _wanted(written: str) -> str:
    """What a cell asked for, said the way a failure should say it."""
    marker = written.strip()
    return f"{marker} ({MARKERS[marker]})" if marker in MARKERS else describe(written)


def _rows(datatable: Any, subject: str) -> list[tuple[str, str]]:
    """A table's rows as field/value pairs, or a refusal saying what shape one has to be."""
    if not datatable:
        pytest.fail(f"{subject}: this step needs a table of fields and what each must hold, below it.")
    pairs: list[tuple[str, str]] = []
    for row in datatable:
        cells = [str(cell) for cell in row]
        if len(cells) != 2:
            pytest.fail(
                f"{subject}: every row takes a field and what it must hold — two cells. "
                f"Got {len(cells)}: {' | '.join(cells)}"
            )
        pairs.append((cells[0].strip(), cells[1]))
    return pairs


@then(parsers.parse(COUNT))
def _(request: pytest.FixtureRequest, count: int, resource_type: str) -> None:
    """Count what this environment holds of a resource type."""
    engine: Materializer = request.getfixturevalue("materializer")
    records = _listing(engine, resource_type)
    if len(records) != count:
        plural = "" if len(records) == 1 else "s"
        pytest.fail(
            f"{engine.env} holds {len(records)} {resource_type} record{plural}, not {count}."
        )


def _listing(engine: Materializer, resource_type: str, doing: str = "count") -> list[Record]:
    """Every record of a type this environment holds, or a refusal saying why there is no answer.

    The cache goes first for the same reason a read does: the listing behind it was taken before
    this scenario's actions ran, and counting what a deletion left has to see what it left.
    """
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")

    system = str(engine.types[resource_type].get("system", ""))
    adapter = engine.adapters.get(system)
    if adapter is None:
        pytest.fail(f"no adapter for system {system!r} in {engine.env}, so there is nothing to count.")
    if not can_browse(adapter):
        pytest.fail(
            f"the {system!r} adapter cannot list what an environment holds, so ATF cannot {doing} "
            f"{resource_type}. Name the resources you mean instead, or give the adapter a "
            "`browse` — see the adapter SPI."
        )

    engine.invalidate_cache()
    try:
        records = engine.browse(resource_type, limit=LISTING_LIMIT)
    except ScopeRequired as exc:
        pytest.fail(
            f"to {doing} {resource_type} ATF needs {', '.join(exc.fields)}, because this type is "
            "listed under a parent and neither of these steps names one."
        )
    if len(records) >= LISTING_LIMIT:
        pytest.fail(
            f"the {resource_type} listing reached {LISTING_LIMIT} records, which is where ATF stops "
            "reading. A listing that might be the limit is not an answer."
        )
    return records


def _contains(actual: Any, value: str) -> bool:
    try:
        return written_contains(actual, value)
    except Uncontainable as exc:
        pytest.fail(str(exc))


@then(parsers.parse(SLOT_CONTAINS))
def _(request: pytest.FixtureRequest, context: Any, slot: str, resource_type: str, name: str) -> None:
    """Require the records a step put on the context to include this resource."""
    engine, node = _node(request, resource_type, name)
    records = _slot(context, slot)
    if not any(identifies(engine, node, record) for record in records):
        pytest.fail(f"nothing in {slot} is {node['id']}. {_looked_for(engine, node, records)}")


@then(parsers.parse(SLOT_LACKS))
def _(request: pytest.FixtureRequest, context: Any, slot: str, resource_type: str, name: str) -> None:
    """Require the records a step put on the context not to include this resource."""
    engine, node = _node(request, resource_type, name)
    records = _slot(context, slot)
    if any(identifies(engine, node, record) for record in records):
        pytest.fail(
            f"{slot} contains {node['id']}, which it must not. {_looked_for(engine, node, records)}"
        )


@then(parsers.parse(SLOT_FIELD_IS))
def _(context: Any, slot: str, field: str, value: str) -> None:
    """Compare one field of what a step put on the context with a value."""
    actual = _slot_field(context, slot, field)
    if not written_matches(actual, value):
        pytest.fail(f"{slot}'s {field!r} is {describe(actual)}, not {describe(value)}")


@then(parsers.parse(SLOT_FIELD_IS_NOT))
def _(context: Any, slot: str, field: str, value: str) -> None:
    """Require one field of what a step put on the context to differ from a value."""
    actual = _slot_field(context, slot, field)
    if written_matches(actual, value):
        pytest.fail(f"{slot}'s {field!r} is {describe(actual)}, which is what it must not be")


@then(parsers.parse(SLOT_FIELD_CONTAINS))
def _(context: Any, slot: str, field: str, value: str) -> None:
    """Require one field of what a step put on the context to hold a value."""
    actual = _slot_field(context, slot, field)
    if not _contains(actual, value):
        pytest.fail(f"{slot}'s {field!r} is {describe(actual)}, which does not hold {value!r}")


@then(parsers.parse(SLOT_FIELD_LACKS))
def _(context: Any, slot: str, field: str, value: str) -> None:
    """Require one field of what a step put on the context not to hold a value."""
    actual = _slot_field(context, slot, field)
    if _contains(actual, value):
        pytest.fail(f"{slot}'s {field!r} is {describe(actual)}, which holds {value!r}")


@then(parsers.parse(SLOT_FIELD_EMPTY))
def _(context: Any, slot: str, field: str) -> None:
    """Require one field of what a step put on the context to hold nothing."""
    actual = _slot_field(context, slot, field)
    if not is_empty(actual):
        pytest.fail(f"{slot}'s {field!r} is {describe(actual)}, not empty")


@then(parsers.parse(SLOT_FIELD_NOT_EMPTY))
def _(context: Any, slot: str, field: str) -> None:
    """Require one field of what a step put on the context to hold something."""
    actual = _slot_field(context, slot, field)
    if is_empty(actual):
        pytest.fail(f"{slot}'s {field!r} is {describe(actual)}, which is empty")


def _slot_field(context: Any, slot: str, field: str) -> Any:
    """One field of the single record a slot holds.

    A list is refused rather than guessed at: a slot holding five records has no one field, and
    picking the first would be a different assertion than the one written.
    """
    records = _slot(context, slot)
    if len(records) != 1:
        pytest.fail(
            f"{slot} holds {len(records)} records, and a field assertion needs one. "
            f'Use `the {slot} contains the <type> "<name>"` for a listing.'
        )
    record = records[0]
    if field not in record:
        carries = ", ".join(sorted(map(str, record))) or "no fields at all"
        pytest.fail(f"{slot} has no field {field!r} — it carries {carries}.")
    return record[field]


# ---- reading ---------------------------------------------------------------


def read(engine: Materializer, node: Node, context: Any) -> Record | None:
    """This resource as it is *now*, not as it was when the scenario provisioned it.

    The cache is dropped first because it is the whole point: the listing behind it was read before
    the actions ran, and an assertion after an action has to see what the action did.
    """
    if node["lifecycle"] == EPHEMERAL:
        return ephemeral_record(context, node["id"])
    engine.invalidate_cache()
    return engine.find_existing(node)


def identifies(engine: Materializer, node: Node, record: Record) -> bool:
    """Whether a record the suite was handed is this catalog node.

    Two ways to recognise one, the same two the cockpit uses when it marks an environment's records
    against the catalog: the identity it has here, or its natural key.
    """
    if not isinstance(record, dict):
        return False
    identity = engine.identity_of(node["id"])
    if identity not in (None, "") and matches(record.get(node["id_field"]), identity):
        return True
    criteria = key_criteria(node, engine.resolve)
    return bool(criteria) and all(matches(record.get(key), want) for key, want in criteria.items())


def _node(request: pytest.FixtureRequest, resource_type: str, name: str) -> tuple[Materializer, Node]:
    engine: Materializer = request.getfixturevalue("materializer")
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")
    node = find_node(engine.nodes, resource_type, name)
    if node is None:
        declared = ", ".join(
            sorted(other["name"] for other in engine.nodes.values() if other["resource"] == resource_type)
        )
        pytest.fail(
            f"the catalog declares no {resource_type} called {name!r} "
            f"(it declares: {declared or 'none of that type'})"
        )
    # Where this scenario asked for an instance of its own, that is the one every claim below is
    # about — the node as it was varied to make it, carrying the key it was given. Substituted here,
    # once, rather than in each step: a claim says which resource it is about and nothing about how
    # that resource came to be, and it should not have to.
    return engine, engine.made_fresh(node["id"]) or node


def _field(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str
) -> Any:
    engine, node = _node(request, resource_type, name)
    record = read(engine, node, context)
    if record is None:
        pytest.fail(f"{_absent(engine, node)} There is no {field!r} to read.")
    if field not in record:
        carries = ", ".join(sorted(map(str, record))) or "no fields at all"
        pytest.fail(f"{node['id']} has no field {field!r} in {engine.env} — the record carries {carries}.")
    return record[field]


def _slot(context: Any, slot: str) -> list[Record]:
    """The records one slot of the context holds, whatever shape the step that set it used.

    A slot is any attribute a step wrote. `result` is the name ATF suggests for what a `When`
    produced, and the one a suite with a single action will use — but naming the slot is what lets
    a scenario with two actions say which of them it means.
    """
    held = getattr(context, slot, _NOTHING)
    if held is _NOTHING:
        pytest.fail(
            f"nothing has put {slot!r} on the context. A step before this one has to set "
            f"`context.{slot}` to what it read.{_holding(context)}"
        )
    records = as_records(held)
    if records is None:
        pytest.fail(f"context.{slot} holds {describe(held)}, which is not a record or a list of them.")
    return records


def _holding(context: Any) -> str:
    """What the scenario *does* hold, so a mistyped slot name is one line to fix rather than a hunt."""
    slots = getattr(context, "slots", None)
    if not isinstance(slots, dict) or not slots:
        return " This scenario holds nothing at all yet."
    named = ", ".join(f"{name} ({held.summary})" for name, held in sorted(slots.items()) if isinstance(held, Slot))
    return f" It holds: {named}." if named else " This scenario holds nothing at all yet."


# ---- what a failure says ---------------------------------------------------


def _absent(engine: Materializer, node: Node) -> str:
    if node["lifecycle"] == EPHEMERAL:
        return f"this scenario has not provisioned {node['id']}, and an ephemeral resource is never looked up."
    criteria = key_criteria(node, engine.resolve)
    if not criteria:
        keys = ", ".join(natural_keys(node["config"])) or "no natural key"
        return f"{node['id']} could not be looked up in {engine.env}: {keys} could not be resolved."
    spelled = ", ".join(f"{key}={value!r}" for key, value in sorted(criteria.items()))
    return f"nothing in {engine.env} matches {node['id']} ({spelled})."


def _looked_for(engine: Materializer, node: Node, records: list[Record]) -> str:
    criteria = key_criteria(node, engine.resolve) or {}
    spelled = ", ".join(f"{key}={value!r}" for key, value in sorted(criteria.items())) or "its identity"
    carried = _shared(records)
    return (
        f"Looked for {spelled} among {len(records)} record"
        f"{'' if len(records) == 1 else 's'} carrying {carried}."
    )


def _shared(records: list[Record]) -> str:
    common: set[str] | None = None
    for record in records:
        keys = {str(key) for key in record}
        common = keys if common is None else common & keys
    return ", ".join(sorted(common or set())) or "no fields in common"


class _Nothing:
    """Distinguishes `context.result` never set from `context.result = None`."""


_NOTHING = _Nothing()
