"""One step under construction: what was chosen, what it means, and what it will write."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...model.catalog import Catalog
from ...model.text import plural
from ...spec.patterns import GIVEN, THEN, fill
from ...spec.steps import (
    FIELD,
    NAME,
    SLOT,
    SLOT_OF,
    TYPE,
    TYPE_OF,
    claim_of,
    comparison,
    generic,
)
from ...suite.discovery import Discovery, StepDef
from .surface import (
    NODE_SUBJECT,
    SLOT_SUBJECT,
    STEP_SUBJECT,
    TYPE_SUBJECT,
    Surface,
)


@dataclass
class Row:
    """One step under construction: a resource to name, or a step definition to instantiate."""

    index: int
    keyword: str
    resource_type: str = ""
    resource_name: str = ""
    pattern: str = ""
    values: dict[str, str] = field(default_factory=dict)
    definition: StepDef | None = None
    node_id: str = ""
    # A Then said the way someone thinks it: what it is about, what of it, how, and against what.
    # Kept beside `pattern`/`values`: each is derived from the other, so a scenario written by hand
    # reads back into the same four choices.
    subject: str = ""
    aspect: str = ""
    compare: str = ""
    target: str = ""
    # What the context holds by the time this row runs, so the row can say whether its step fits.
    held: set[str] = field(default_factory=set)
    # The subset of that a *step* put there. A `Given` also holds its record, but a claim about a
    # resource re-reads it live and a claim about a slot does not — so offering the slot would be
    # offering the worse of two ways to say the same thing. See `steps.py`.
    produced: set[str] = field(default_factory=set)
    # The rows of a table, for the steps that take one — pairs, which is what a table is. Empty for
    # every other step, which is most of them.
    table: list[list[str]] = field(default_factory=list)
    text: str = ""
    shown_keyword: str = ""
    problem: str = ""

    @property
    def takes_table(self) -> bool:
        return self.definition is not None and self.definition.takes_table

    @property
    def given(self) -> bool:
        return self.keyword == GIVEN

def make_row(
    index: int,
    keyword: str,
    chosen: dict[str, Any],
    offered: dict[str, list[StepDef]],
    catalog: Catalog,
) -> Row:
    """The choices somebody made for one row, as the row they describe.

    `chosen` is a plain mapping, so the same four choices mean the same line whether they arrived
    from a `<select>` or from a tool call. Its keys are the choices themselves: `subject`, `aspect`,
    `compare`, `target` for a claim, `pattern` and `params` for a step said by its wording.
    """
    row = Row(index=index, keyword=keyword)
    if row.given:
        row.resource_type = str(chosen.get("resource_type", "")).strip()
        row.resource_name = str(chosen.get("resource_name", "")).strip()
        return row

    row.subject = str(chosen.get("subject", "")).strip()
    row.aspect = str(chosen.get("aspect", "")).strip()
    row.compare = str(chosen.get("compare", "")).strip()
    # A resource chosen as the target arrives as `node:<id>`; a value arrives as itself. Stored bare
    # either way: what the claim writes is the same.
    row.target = str(chosen.get("target", "")).strip().removeprefix(NODE_SUBJECT)
    row.pattern = str(chosen.get("pattern", ""))
    row.table = [[str(cell) for cell in pair] for pair in chosen.get("table") or []]

    claimed = bool(row.subject) and not row.subject.startswith(STEP_SUBJECT)
    if claimed:
        write_claim(row, catalog)
    row.definition = next((step for step in offered[keyword] if step.pattern == row.pattern), None)

    if claimed:
        return row
    params = chosen.get("params") or {}
    if row.definition is not None:
        row.values = {name: str(params.get(name, "")).strip() for name in row.definition.params}
    # A pattern that arrived without the four choices — from text, or from a scenario written by
    # hand — is read back into them, so the row means one thing.
    if not row.subject:
        read_claim(row, catalog)
    return row

def write_claim(row: Row, catalog: Catalog) -> None:
    """Four choices, turned into the pattern and values ATF will actually write."""
    claimed = comparison(row.compare)
    if claimed is None:
        row.pattern = ""
        return
    row.pattern = claimed.pattern
    row.values = {}

    # A claim about a resource names it; a claim about a slot names one only when the slot is being
    # searched for it. A claim about a field of a slot names no resource at all, and a claim about a
    # whole type names the type and no instance — there is nothing to name.
    about = ""
    if claimed.subject == SLOT_OF:
        row.values[SLOT] = row.subject.removeprefix(SLOT_SUBJECT)
        about = row.target if claimed.target == "resource" else ""
    elif claimed.subject == TYPE_OF:
        row.values[TYPE] = row.subject.removeprefix(TYPE_SUBJECT)
    else:
        about = row.subject.removeprefix(NODE_SUBJECT)
    node = catalog.nodes.get(about)
    if node is not None:
        row.values.update({TYPE: node.resource, NAME: node.name})
    if claimed.field:
        row.values[FIELD] = row.aspect
    if claimed.target == "value":
        row.values[claimed.value_capture] = row.target

def read_claim(row: Row, catalog: Catalog) -> None:
    """The reverse: a pattern and its values, read back as what they claim."""
    claimed = claim_of(row.pattern)
    if claimed is None:
        row.subject = f"{STEP_SUBJECT}{row.pattern}" if row.pattern else ""
        return

    row.compare = claimed.key
    row.aspect = row.values.get(FIELD, "")
    named = catalog.find(row.values.get(TYPE, ""), row.values.get(NAME, ""))
    if claimed.subject == TYPE_OF:
        row.subject = f"{TYPE_SUBJECT}{row.values.get(TYPE, '')}"
        row.target = row.values.get(claimed.value_capture, "")
    elif claimed.subject == SLOT_OF:
        row.subject = f"{SLOT_SUBJECT}{row.values.get(SLOT, '')}"
        row.target = (
            (named.id if named else "")
            if claimed.target == "resource"
            else row.values.get(claimed.value_capture, "")
        )
    else:
        row.subject = f"{NODE_SUBJECT}{named.id}" if named else ""
        row.target = row.values.get(claimed.value_capture, "")

def held_before(rows: list[Row], index: int) -> set[str]:
    """What the context holds by the time row `index` runs.

    A `Given` puts its record under the type's name; a `When` or `Then` puts whatever its own
    source says it writes. This is the whole of what a step can read, so it is the whole of what
    decides whether a step can be used here.
    """
    return _before(rows, index, givens=True)

def produced_before(rows: list[Row], index: int) -> set[str]:
    """The part of that a step put there, which is what a claim about a slot may be about.

    A `Given`'s record is on the context too, but a claim about the *resource* re-reads it from the
    environment and a claim about the slot reads the copy the `Given` made. Offering both is
    offering the worse of two ways to say one thing, so only what a step produced is offered.
    """
    return _before(rows, index, givens=False)

def _before(rows: list[Row], index: int, givens: bool) -> set[str]:
    held: set[str] = set()
    for row in rows:
        if row.index == index:
            break
        if row.given and row.resource_type:
            if givens:
                held.add(row.resource_type)
        elif row.definition is not None:
            held.update(row.definition.produces)
    return held

def usable(step: StepDef, row: Row) -> bool:
    """Whether the scenario, as far as this row, can use this step at all.

    A step reading a fixed slot needs that one held. A step reading the slot its own wording names
    needs there to be *some* slot worth naming; which one it names is checked when the row resolves.
    """
    if not set(step.needs) <= row.held:
        return False
    return bool(row.produced) if step.needs_slot else True


def resolve(rows: list[Row], surface: Surface) -> None:
    """Turn every row into the words it will write, and say plainly where it cannot yet."""
    catalog, found = surface.catalog, surface.found
    for row in rows:
        row.held = held_before(rows, row.index)
        row.produced = produced_before(rows, row.index)
        if row.given:
            _resolve_given(row, catalog)
        else:
            _resolve_step(row, found, catalog)

    # Only a row that produced a line counts as something for the next one to continue, so an
    # unfinished row in the middle can never leave an `And` with no keyword above it.
    previous = ""
    for row in rows:
        row.shown_keyword = "And" if row.keyword == previous else row.keyword.capitalize()
        if row.text:
            previous = row.keyword

def _resolve_given(row: Row, catalog: Catalog) -> None:
    if not row.resource_type or not row.resource_name:
        row.problem = "pick a resource type and one of its instances"
        return
    row.text = f'the {row.resource_type} "{row.resource_name}"'
    node = catalog.find(row.resource_type, row.resource_name)
    if node is None:
        row.problem = f"the catalog declares no {row.resource_type} called {row.resource_name!r}"
        return
    row.node_id = node.id

def _resolve_step(row: Row, found: Discovery, catalog: Catalog) -> None:
    if not row.pattern:
        # A Then is chosen by what it is about; a When by what it does. Say the one that applies.
        row.problem = (
            "pick what this is about" if row.keyword == THEN else "choose the when step this scenario uses"
        )
        return
    if row.definition is None:
        row.problem = f"no {row.keyword} step this feature can reach is worded {row.pattern!r}"
        row.text = row.pattern
        return

    row.text = fill(row.definition.pattern, row.values)
    missing = [name for name in row.definition.params if not row.values.get(name)]
    if missing:
        row.problem = f"give {'a value' if len(missing) == 1 else 'values'} for {', '.join(missing)}"
        return

    if row.takes_table:
        if not row.table:
            row.problem = "say what this must hold — add a field and what it holds, below"
            return
        half = next((pair for pair in row.table if not pair[0] or not pair[1]), None)
        if half is not None:
            shown = half[0] or half[1]
            row.problem = f"the row for {shown!r} needs both a field and what it holds"
            return

    absent = [name for name in row.definition.needs if name not in row.held]
    # A step that names its own slot is held to the slot it named, not to a fixed one.
    if row.definition.needs_slot:
        named = row.values.get(SLOT, "")
        if named and named not in row.held:
            absent = [named]
    if absent:
        row.problem = (
            f"nothing above this puts {' or '.join(absent)} on the context — "
            f"add a row that does, above it"
        )
        return

    # A step ATF defines names a catalog resource, so it is held to the catalog exactly as a Given
    # row is, here, and not by a line that only fails when it runs.
    if generic(row.definition.pattern) is not None and NAME in row.definition.params:
        resource_type, name = row.values.get(TYPE, ""), row.values.get(NAME, "")
        node = catalog.find(resource_type, name)
        if node is None:
            row.problem = (
                f"the catalog declares no {resource_type} called {name!r}"
                if resource_type
                else "pick what this is about"
            )
            return
        row.node_id = node.id

def row_problems(rows: list[Row]) -> list[str]:
    """Everything standing between these rows and a scenario, each said in a sentence."""
    if not rows:
        return ["A scenario with no steps asserts nothing. Add a When and a Then."]
    problems: list[str] = []
    unresolved = [row for row in rows if row.problem]
    if unresolved:
        problems.append(
            f"{plural(len(unresolved), 'step')} {'does' if len(unresolved) == 1 else 'do'} not resolve yet — "
            + "; ".join(row.problem for row in unresolved)
            + "."
        )
    if not any(row.keyword == THEN for row in rows):
        problems.append("Nothing is asserted — a scenario needs at least one Then.")
    return problems

def gherkin(title: str, rows: list[Row]) -> str:
    """The scenario block exactly as it will be written: two spaces in, its steps four.

    A repeated keyword becomes `And`, as a person writing it by hand would. An untitled scenario is
    written untitled: nothing invented here ends up on disk.
    """
    lines = [f"  Scenario: {title}".rstrip()]
    # A row with nothing chosen yet contributes no line: a bare `Given` is not something that would
    # ever be written, and a preview is only worth trusting if it is exactly what will be.
    for row in rows:
        if not row.text:
            continue
        lines.append(f"    {row.shown_keyword} {row.text}")
        lines += table_lines(row)
    return "\n".join(lines) + "\n"

def table_lines(row: Row) -> list[str]:
    """A table under its step, its columns padded so a reader can follow a row across."""
    if not row.takes_table or not row.table:
        return []
    widest = [max(len(pair[column]) for pair in row.table) for column in (0, 1)]
    return [f"      | {pair[0].ljust(widest[0])} | {pair[1].ljust(widest[1])} |" for pair in row.table]
