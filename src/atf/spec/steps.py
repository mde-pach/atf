"""The read-and-compare steps, so that every suite stops writing them again."""

from __future__ import annotations

from inspect import Parameter, Signature
from typing import Any, cast

import pytest
from pytest_bdd import parsers, then, when

from ..adapters import Record, Runnable, can_browse, can_run
from ..engine.materializer import Materializer, ProvisioningError, ScopeRequired
from ..model.catalog import Node
from ..model.compare import (
    MARKERS,
    MISSING,
    Uncontainable,
    describe,
    field_matches,
    is_marker,
    matches,
)
from ..model.placeholders import Unresolved
from ..model.records import as_records, shared_fields
from ..model.text import plural
from .adapters import sole
from .context import Slot, ephemeral_record
from .vocabulary import (
    ACT,
    COMPARISONS,
    COUNT,
    EXISTS,
    FIELD,
    GONE,
    LIST_EVERY,
    LISTING_LIMIT,
    NAME,
    RESOURCE,
    RUN,
    SHAPE_IS,
    SLOT,
    SLOT_CONTAINS,
    SLOT_LACKS,
    SLOT_SHAPE_IS,
    TYPE,
    VALUE,
    Comparison,
)


@when(parsers.parse(ACT))
def _(request: pytest.FixtureRequest, context: Any, action: str, resource_type: str, name: str) -> None:
    engine, node = _node(request, resource_type, name)
    known = engine.spec(resource_type).actions
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
    engine: Materializer = request.getfixturevalue("materializer")
    runner = sole(
        engine,
        can_run,
        "this step runs a command, and this environment configures no system that can run one. "
        "Add `command` under `environments.<env>.adapters`.",
        "more than one system here can run a command, so ATF cannot tell which to use.",
    )
    try:
        context.result = cast("Runnable", runner).run(command)
    except ValueError as exc:
        pytest.fail(str(exc))

@when(parsers.parse(LIST_EVERY))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str) -> None:
    engine: Materializer = request.getfixturevalue("materializer")
    context.result = _listing(engine, resource_type, doing="list")

@then(parsers.parse(EXISTS))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str) -> None:
    engine, node = _node(request, resource_type, name)
    if read(engine, node, context) is None:
        pytest.fail(_absent(engine, node))

@then(parsers.parse(GONE))
def _(request: pytest.FixtureRequest, context: Any, resource_type: str, name: str) -> None:
    engine, node = _node(request, resource_type, name)
    if node.ephemeral:
        pytest.fail(
            f"{node.id} is ephemeral, so ATF never looks one up and cannot tell whether it is gone. "
            "Assert on the backend directly in a step of your own."
        )
    record = read(engine, node, context)
    if record is not None:
        pytest.fail(
            f"{node.id} is still in {engine.env}: {node.id_field}="
            f"{record.get(node.id_field)!r} matches what the catalog declares."
        )

@then(parsers.parse(SHAPE_IS))
def _(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, datatable: Any = None
) -> None:
    engine, node = _node(request, resource_type, name)
    record = read(engine, node, context)
    if record is None:
        pytest.fail(_absent(engine, node))
    _shape(record, datatable, f"{resource_type} {name!r}", engine)

@then(parsers.parse(SLOT_SHAPE_IS))
def _(request: pytest.FixtureRequest, context: Any, slot: str, datatable: Any = None) -> None:
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
        # `${...}` resolves here, not in the plugin's hook: a table's cells never reach it, since
        # pytest-bdd hands them over as one `datatable` argument.
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
    if marker in MARKERS:
        return f"{marker} ({MARKERS[marker]})"
    # `#regex ^AC-[0-9]+$` carries its pattern, so it is not a key of the table — and a reader
    # meeting one in a failure has to be told it was a pattern.
    if is_marker(marker):
        _, _, pattern = marker.partition(" ")
        return f"text matching {pattern.strip()!r}"
    return describe(written)

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
    engine: Materializer = request.getfixturevalue("materializer")
    records = _listing(engine, resource_type)
    if len(records) != count:
        pytest.fail(f"{engine.env} holds {plural(len(records), f'{resource_type} record')}, not {count}.")

def _listing(engine: Materializer, resource_type: str, doing: str = "count") -> list[Record]:
    """Every record of a type this environment holds, or a refusal saying why there is no answer.

    The cache goes first for the same reason a read does: the listing behind it was taken before
    this scenario's actions ran, and counting what a deletion left has to see what it left.
    """
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")

    system = engine.spec(resource_type).system
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

@then(parsers.parse(SLOT_CONTAINS))
def _(request: pytest.FixtureRequest, context: Any, slot: str, resource_type: str, name: str) -> None:
    engine, node = _node(request, resource_type, name)
    records = _slot(context, slot)
    if not any(identifies(engine, node, record) for record in records):
        pytest.fail(f"nothing in {slot} is {node.id}. {_looked_for(engine, node, records)}")

@then(parsers.parse(SLOT_LACKS))
def _(request: pytest.FixtureRequest, context: Any, slot: str, resource_type: str, name: str) -> None:
    engine, node = _node(request, resource_type, name)
    records = _slot(context, slot)
    if any(identifies(engine, node, record) for record in records):
        pytest.fail(
            f"{slot} contains {node.id}, which it must not. {_looked_for(engine, node, records)}"
        )

def _held(said: str, actual: Any, item: Comparison, written: str) -> None:
    """Fail unless the claim holds, saying what the field holds and what was wanted of it."""
    __tracebackhide__ = True
    if item.holds is None:
        return
    try:
        holds = item.holds(actual, written)
    except Uncontainable as exc:
        pytest.fail(str(exc))
    if holds != item.negated:
        return
    wanted = item.otherwise.format(written=written, expected=describe(written))
    pytest.fail(f"{said} is {describe(actual)}, {wanted}")

def _claim_step(item: Comparison) -> Any:
    """The function ATF registers for one field claim, declaring the captures its pattern names."""
    about_resource = item.subject == RESOURCE

    def _step(**values: Any) -> None:
        __tracebackhide__ = True

        if about_resource:
            said = f"{values[TYPE]} {values[NAME]!r} field {values[FIELD]!r}"
            actual = _field(values["request"], values["context"], values[TYPE], values[NAME], values[FIELD])
        else:
            said = f"{values[SLOT]}'s {values[FIELD]!r}"
            actual = _slot_field(values["context"], values[SLOT], values[FIELD])
        _held(said, actual, item, values.get(VALUE, ""))

    named = ["request", "context", *([TYPE, NAME] if about_resource else [SLOT]), FIELD]
    if item.target == "value":
        named.append(VALUE)
    _step.__name__ = item.key.replace("-", "_")
    # `inspect.signature` reports this in preference to the real one, which is what pytest-bdd reads
    # to decide what to pass. The body still takes `**values`.
    _step.__signature__ = Signature(  # ty: ignore[unresolved-attribute]
        [Parameter(name, Parameter.POSITIONAL_OR_KEYWORD) for name in named]
    )
    return _step

for _claim in COMPARISONS:
    if _claim.field:
        then(parsers.parse(_claim.pattern))(_claim_step(_claim))

def _slot_field(context: Any, slot: str, field: str) -> Any:
    """One field of the single record a slot holds.

    Fails when the slot holds anything but one record: five records have no one field, and the first
    of them is a different assertion from the one written.
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

def read(engine: Materializer, node: Node, context: Any) -> Record | None:
    """This resource as it is *now*, not as it was when the scenario provisioned it.

    The cache is dropped first: the listing behind it was read before the actions ran, and an
    assertion after an action has to see what the action did.
    """
    if node.ephemeral:
        return ephemeral_record(context, node.id)
    engine.invalidate_cache()
    return engine.find_existing(node)

def identifies(engine: Materializer, node: Node, record: Record) -> bool:
    """Whether a record the suite was handed is this catalog node.

    Two ways to recognise one, the same two the cockpit uses when it marks an environment's records
    against the catalog: the identity it has here, or its natural key.
    """
    if not isinstance(record, dict):
        return False
    identity = engine.identity_of(node.id)
    if identity not in (None, "") and matches(record.get(node.id_field), identity):
        return True
    criteria = node.key_criteria(engine.resolve)
    return bool(criteria) and all(matches(record.get(key), want) for key, want in criteria.items())

def _node(request: pytest.FixtureRequest, resource_type: str, name: str) -> tuple[Materializer, Node]:
    engine: Materializer = request.getfixturevalue("materializer")
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")
    node = engine.catalog.find(resource_type, name)
    if node is None:
        declared = ", ".join(
            sorted(other.name for other in engine.nodes.values() if other.resource == resource_type)
        )
        pytest.fail(
            f"the catalog declares no {resource_type} called {name!r} "
            f"(it declares: {declared or 'none of that type'})"
        )
    # Where this scenario asked for an instance of its own, that is the one every claim below is
    # about — the node as it was varied to make it, carrying the key it was given. Substituted here,
    # once: a claim says which resource it is about and nothing about how that resource came to be.
    return engine, engine.made_fresh(node.id) or node

def _field(
    request: pytest.FixtureRequest, context: Any, resource_type: str, name: str, field: str
) -> Any:
    engine, node = _node(request, resource_type, name)
    record = read(engine, node, context)
    if record is None:
        pytest.fail(f"{_absent(engine, node)} There is no {field!r} to read.")
    if field not in record:
        carries = ", ".join(sorted(map(str, record))) or "no fields at all"
        pytest.fail(f"{node.id} has no field {field!r} in {engine.env} — the record carries {carries}.")
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
    """What the scenario *does* hold, for a failure about a slot name nothing put there."""
    slots = getattr(context, "slots", None)
    if not isinstance(slots, dict) or not slots:
        return " This scenario holds nothing at all yet."
    named = ", ".join(f"{name} ({held.summary})" for name, held in sorted(slots.items()) if isinstance(held, Slot))
    return f" It holds: {named}." if named else " This scenario holds nothing at all yet."

def _absent(engine: Materializer, node: Node) -> str:
    if node.ephemeral:
        return f"this scenario has not provisioned {node.id}, and an ephemeral resource is never looked up."
    criteria = node.key_criteria(engine.resolve)
    if not criteria:
        keys = ", ".join(node.natural_keys) or "no natural key"
        return f"{node.id} could not be looked up in {engine.env}: {keys} could not be resolved."
    spelled = ", ".join(f"{key}={value!r}" for key, value in sorted(criteria.items()))
    return f"nothing in {engine.env} matches {node.id} ({spelled})."

def _looked_for(engine: Materializer, node: Node, records: list[Record]) -> str:
    criteria = node.key_criteria(engine.resolve) or {}
    spelled = ", ".join(f"{key}={value!r}" for key, value in sorted(criteria.items())) or "its identity"
    carried = ", ".join(shared_fields(records)) or "no fields in common"
    return (
        f"Looked for {spelled} among {len(records)} record"
        f"{'' if len(records) == 1 else 's'} carrying {carried}."
    )

class _Nothing:
    """Distinguishes `context.result` never set from `context.result = None`."""

_NOTHING = _Nothing()
