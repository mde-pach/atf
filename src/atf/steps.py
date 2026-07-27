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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from pytest_bdd import parsers, then

from .adapters import Record
from .catalog import Node, find_node, key_criteria, natural_keys
from .compare import describe, matches, written_matches
from .context import RESULT, ephemeral_record
from .materializer import EPHEMERAL, Materializer

# ---- the vocabulary --------------------------------------------------------

# ATF's own provisioning step, defined in `plugin.py` beside the factories it drives. It is listed
# here because this table is what the composer reads to know which of a step's parameters it can
# offer a real choice for, and that is as true of the Given as of the assertions.
PROVISION = 'the {resource_type} "{name}"'

EXISTS = 'the {resource_type} "{name}" exists'
GONE = 'the {resource_type} "{name}" is gone'
FIELD_IS = 'the {resource_type} "{name}" field "{field}" is "{value}"'
FIELD_IS_NOT = 'the {resource_type} "{name}" field "{field}" is not "{value}"'
RESULT_CONTAINS = 'the result contains the {resource_type} "{name}"'
RESULT_LACKS = 'the result does not contain the {resource_type} "{name}"'
RESULT_FIELD_IS = 'the result field "{field}" is "{value}"'
RESULT_FIELD_IS_NOT = 'the result field "{field}" is not "{value}"'

# A capture's parameter name is also what it means, because ATF chose both. A project's step may
# well have a parameter called `field` that means something else entirely, which is why only the
# patterns in this table are read this way.
TYPE, NAME, FIELD, VALUE = "resource_type", "name", "field", "value"


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


GENERIC_STEPS: tuple[GenericStep, ...] = (
    GenericStep(
        "given",
        PROVISION,
        "Make this resource exist here, and everything it depends on first.",
        (TYPE, NAME),
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
        RESULT_CONTAINS,
        "Require the records the last step produced to include this resource.",
        (TYPE, NAME),
        needs=(RESULT,),
    ),
    GenericStep(
        "then",
        RESULT_LACKS,
        "Require the records the last step produced not to include this resource.",
        (TYPE, NAME),
        needs=(RESULT,),
    ),
    GenericStep(
        "then",
        RESULT_FIELD_IS,
        "Compare one field of what the last step produced with a value.",
        (FIELD, VALUE),
        needs=(RESULT,),
    ),
    GenericStep(
        "then",
        RESULT_FIELD_IS_NOT,
        "Require one field of what the last step produced to differ from a value.",
        (FIELD, VALUE),
        needs=(RESULT,),
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

RESOURCE, RESULT_OF = "resource", "result"


@dataclass(frozen=True)
class Comparison:
    """One claim an assertion can make, and the wording ATF writes for it."""

    key: str
    label: str
    pattern: str
    # What the claim is about: a resource in the catalog, or what the step before produced.
    subject: str
    # Whether it names a field of that subject, and what it is compared against.
    field: bool = False
    target: str = ""  # "" | "value" | "resource"


COMPARISONS: tuple[Comparison, ...] = (
    Comparison("exists", "exists", EXISTS, RESOURCE),
    Comparison("gone", "is gone", GONE, RESOURCE),
    Comparison("is", "is", FIELD_IS, RESOURCE, field=True, target="value"),
    Comparison("is-not", "is not", FIELD_IS_NOT, RESOURCE, field=True, target="value"),
    Comparison("contains", "contains", RESULT_CONTAINS, RESULT_OF, target="resource"),
    Comparison("lacks", "does not contain", RESULT_LACKS, RESULT_OF, target="resource"),
    Comparison("result-is", "is", RESULT_FIELD_IS, RESULT_OF, field=True, target="value"),
    Comparison("result-is-not", "is not", RESULT_FIELD_IS_NOT, RESULT_OF, field=True, target="value"),
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


@then(parsers.parse(RESULT_CONTAINS))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str) -> None:
    """Require the records the last step produced to include this resource."""
    engine, node = _node(request, resource_type, name)
    records = _result(context)
    if not any(identifies(engine, node, record) for record in records):
        pytest.fail(f"nothing in the result is {node['id']}. {_looked_for(engine, node, records)}")


@then(parsers.parse(RESULT_LACKS))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str) -> None:
    """Require the records the last step produced not to include this resource."""
    engine, node = _node(request, resource_type, name)
    records = _result(context)
    if any(identifies(engine, node, record) for record in records):
        pytest.fail(
            f"the result contains {node['id']}, which it must not. {_looked_for(engine, node, records)}"
        )


@then(parsers.parse(RESULT_FIELD_IS))
def _(context: Any, field: str, value: str) -> None:
    """Compare one field of what the last step produced with a value."""
    actual = _result_field(context, field)
    if not written_matches(actual, value):
        pytest.fail(f"the result's {field!r} is {describe(actual)}, not {describe(value)}")


@then(parsers.parse(RESULT_FIELD_IS_NOT))
def _(context: Any, field: str, value: str) -> None:
    """Require one field of what the last step produced to differ from a value."""
    actual = _result_field(context, field)
    if written_matches(actual, value):
        pytest.fail(f"the result's {field!r} is {describe(actual)}, which is what it must not be")


def _result_field(context: Any, field: str) -> Any:
    """One field of the single record a step produced.

    A list is refused rather than guessed at: "the result" of a step that returned five records has
    no one field, and picking the first would be a different assertion than the one written.
    """
    records = _result(context)
    if len(records) != 1:
        pytest.fail(
            f"the result holds {len(records)} records, and a field assertion needs one. "
            'Use `the result contains the <type> "<name>"` for a listing.'
        )
    record = records[0]
    if field not in record:
        carries = ", ".join(sorted(map(str, record))) or "no fields at all"
        pytest.fail(f"the result has no field {field!r} — it carries {carries}.")
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
    return engine, node


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


def _result(context: Any) -> list[Record]:
    """The records the step before this one produced, whatever shape it produced them in.

    `result` is the one attribute of the context ATF itself names, so that an assertion over a
    step's output is possible without the framework having to be told the shape in advance.
    """
    held = getattr(context, RESULT, _NOTHING)
    if held is _NOTHING:
        pytest.fail(
            "nothing has produced a result yet. A step before this one has to set `context.result` "
            "to what it read — that is the name ATF knows a step's output by."
        )
    if isinstance(held, dict):
        return [cast("Record", held)]
    if isinstance(held, list):
        return [cast("Record", item) for item in held if isinstance(item, dict)]
    pytest.fail(f"context.result holds {describe(held)}, which is not a record or a list of them.")


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
