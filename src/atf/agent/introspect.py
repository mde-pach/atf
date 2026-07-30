"""What can be said about this environment, read out as data."""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..engine.materializer import Materializer
from ..engine.status import ResourceStatus, Statuses
from ..model.catalog import Catalog, Node
from ..model.compare import MARKERS
from ..model.text import plural
from ..model.typespec import DATA, REFERENCE
from ..run.runner import ERROR, PASSED, TestResult
from ..run.runner import run as run_tests
from ..spec.context import RESULT
from ..spec.patterns import GIVEN, THEN, WHEN, fill
from ..spec.steps import (
    COMPARISONS,
    FIELD,
    NAME,
    RESOURCE,
    SLOT,
    SLOT_OF,
    TYPE,
    TYPE_OF,
    Comparison,
    claim_of,
    comparison,
    comparisons_for,
    generic,
)
from ..suite.discovery import Discovery, StepDef

KEYWORDS = (GIVEN, WHEN, THEN)

# The three things a Then can be about, plus a project's own step. A slot and a type carry their name
# in the prefix: *which* one is half of what the choice says.
NODE_SUBJECT, SLOT_SUBJECT, STEP_SUBJECT, TYPE_SUBJECT = "node:", "slot:", "step:", "type:"

# What a step wording is filed under, so a caller can tell whose vocabulary it is looking at without
# knowing where any file lives. A phrase is its own answer: there is no Python behind one.
FROM_ATF, FROM_SUITE, FROM_PHRASEBOOK = "atf", "suite", "phrasebook"

# A `scenarios(...)` call on its own line — what binds a feature to pytest.
_SCENARIOS_CALL = re.compile(r"^[ \t]*scenarios\((?:[^()]|\([^()]*\))*\)[ \t]*$", re.MULTILINE)

# What a scratch module for a trial holds when the feature is new: nothing but the binding, which is
# also the truth about what such a scenario can reach. Nothing writes one of these to keep — ATF
# collects a `.feature` nobody bound, so a composed scenario needs no Python beside it.
BINDING = '''"""Binds {name} for one trial run. Written and removed by the composer."""

from pytest_bdd import scenarios

scenarios("{path}")
'''


class Outside(Exception):
    """A path that is not under the suite's specs directory. Refused, never clamped."""

    def __init__(self, specs_dir: Path) -> None:
        super().__init__(f"refusing to write outside {specs_dir}")


# ---- the thing every question is asked of ----------------------------------


@dataclass(frozen=True)
class Surface:
    """One environment, as everything that decides what can be said about it.

    The set is exactly what an answer depends on: change the catalog, the environment's status or the
    steps the project registers, and every answer below changes with it.
    """

    env: str
    root: Path
    specs_dir: Path
    engine: Materializer
    found: Discovery
    status: Statuses = field(default_factory=Statuses)

    @property
    def catalog(self) -> Catalog:
        return self.engine.catalog

    @property
    def nodes(self) -> dict[str, Node]:
        return self.engine.nodes


# ---- the fields of a resource, for an assertion built without an editor -----


@dataclass
class FieldChoice:
    """One field an assertion can name, and what it holds right now."""

    name: str
    current: str = ""
    source: str = ""

    @property
    def hint(self) -> str:
        if self.current:
            return f"currently {self.current} · {self.source}" if self.source else f"currently {self.current}"
        return self.source


def field_choices(node: Node, entry: ResourceStatus) -> list[FieldChoice]:
    """The fields of one resource, best-known first.

    Three sources, in decreasing authority: what the environment's record actually carries, what
    the catalog body declares, and the two fields the type itself names — its identity and whatever
    it is recognised by. A field is only ever *offered*; nothing here requires one to exist, which
    is the line the framework holds on record shape.
    """
    record = entry.fields
    declared = node.body
    named = [node.id_field, *node.natural_keys]

    ordered: list[str] = []
    for name in [*named, *sorted(record), *sorted(declared)]:
        if name not in ordered:
            ordered.append(str(name))

    choices: list[FieldChoice] = []
    for name in ordered:
        if name in record:
            choices.append(FieldChoice(name, written(record[name]), "on the record in this environment"))
        elif name in declared:
            choices.append(FieldChoice(name, written(declared[name]), "declared in the catalog"))
        elif name == node.id_field:
            choices.append(FieldChoice(name, "", "the identity field, assigned when it is created"))
        else:
            choices.append(FieldChoice(name, "", "part of the natural key"))
    return choices


def written(value: Any) -> str:
    """A record's value as a scenario would write it between quotes."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)[:60]
    return str(value)[:60]


# ---- one step under construction --------------------------------------------


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


# ---- a claim, both ways round -----------------------------------------------


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


def subject_kind(subject: str) -> str:
    """Which of the three things a chosen subject is, in the terms `COMPARISONS` is written in."""
    if subject.startswith(TYPE_SUBJECT):
        return TYPE_OF
    if subject.startswith(SLOT_SUBJECT):
        return SLOT_OF
    return RESOURCE


# ---- which steps a scenario in this feature can use --------------------------


def features(found: Discovery) -> list[str]:
    return sorted({spec.feature for spec in found.specs if spec.feature})


def binding_module(found: Discovery, feature: str) -> Path | None:
    """The module that hands this feature to pytest, if one does.

    It matters far beyond collection: pytest-bdd registers every step as a fixture in the module
    that declares it, so *which* module binds a feature decides which steps that feature can use.
    """
    for test in found.tests:
        spec = found.spec(test.covers) if test.covers else None
        if spec is not None and spec.feature == feature and test.file:
            return Path(test.file)
    return None


def reachable(step: StepDef, module: Path | None, specs_dir: Path) -> bool:
    """Whether a step definition is visible from the module that will bind a feature.

    pytest's fixture rules, which is what step lookup really is: a step declared in a module is
    visible in that module, one declared in a `conftest.py` is visible below it, and one a plugin
    registered — every step ATF itself defines — is visible everywhere.

    A [phrase](../spec/phrasebook.py) is in that last group and is named here: its `file` is the
    phrasebook, which sits inside the specs tree, but ATF's plugin is what registered it, so every
    feature can say it.
    """
    if not step.file or step.phrase:
        return True
    path = Path(step.file)
    try:
        path.relative_to(specs_dir)
    except ValueError:
        return True
    if path.name == "conftest.py":
        return module is None or path.parent in module.parents
    return module is not None and path == module


def offered_steps(surface: Surface, feature: str = "") -> dict[str, list[StepDef]]:
    """The steps a scenario in `feature` can actually use, by keyword.

    Everything anything does with steps goes through here — what it offers, and what it accepts. A
    step resolved from a wider set than it is offered from is a step someone can keep by switching
    feature after choosing it, and then find missing only when it runs.
    """
    binding = binding_module(surface.found, feature) if feature else None
    return {
        keyword: [
            step
            for step in surface.found.steps_for(keyword)
            if reachable(step, binding, surface.specs_dir)
        ]
        for keyword in KEYWORDS
    }


def elsewhere(
    found: Discovery, offered: dict[str, list[StepDef]], binding: Path | None, specs_dir: Path
) -> list[str]:
    """Modules holding steps this feature cannot use, for a surface that has to say so.

    The fix is a choice between two files — move the scenario, or move the step into a `conftest.py`
    every feature can see — so this names both and picks neither.
    """
    shown = {step.pattern for steps in offered.values() for step in steps}
    files = {
        Path(step.file).name
        for keyword in KEYWORDS
        for step in found.steps_for(keyword)
        if step.pattern not in shown and step.file and not reachable(step, binding, specs_dir)
    }
    return sorted(files)


# ---- what the rows above a row have left behind ------------------------------


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


# ---- turning rows into the words they will write -----------------------------


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


# ---- the choices, each carrying what is needed to make it --------------------
#
# A list of names tells you nothing about which name you want. Every option below carries a label, a
# short `meta` and a longer `desc` — what an interface renders and what an agent reads, in one shape.


def feature_options(found: Discovery) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for spec in found.specs:
        counts[spec.feature] = counts.get(spec.feature, 0) + 1
    return [
        {
            "value": name,
            "label": name,
            "meta": plural(counts.get(name, 0), "scenario"),
            "desc": "",
        }
        for name in sorted(counts)
    ]


def instances_by_type(surface: Surface) -> dict[str, list[Node]]:
    grouped: dict[str, list[Node]] = {}
    for node in sorted(surface.nodes.values(), key=lambda item: item.name):
        grouped.setdefault(node.resource, []).append(node)
    return grouped


def type_options(surface: Surface) -> list[dict[str, str]]:
    status = surface.status
    instances = instances_by_type(surface)
    options: list[dict[str, str]] = []
    for name in surface.catalog.resource_types:
        spec = surface.catalog.types[name]
        members = instances.get(name, [])
        present = sum(1 for node in members if status.of(node.id).present)
        note = " · built fresh per run" if spec.ephemeral else ""
        note += " · must already exist here" if spec.mode == REFERENCE else ""
        note += " · observed, never created" if spec.mode == DATA else ""
        options.append(
            {
                "value": name,
                "label": name,
                "meta": spec.system,
                "desc": f"{len(members)} in the catalog, {present} present in this environment{note}",
            }
        )
    return options


def instance_options(members: list[Node], status: Statuses) -> list[dict[str, str]]:
    """The resources of one type, each with where it stands and what it is for.

    Choosing between `primary` and `secondary` is impossible from the names alone, which is exactly
    what `represents` was written to answer.
    """
    return [
        {
            "value": node.name,
            "label": node.name,
            "meta": status.state(node.id),
            "desc": node.represents or node.id,
        }
        for node in members
    ]


def resource_options(surface: Surface, group: str = "") -> list[dict[str, str]]:
    status = surface.status
    return [
        {
            "value": f"{NODE_SUBJECT}{node.id}",
            "label": node.name,
            "meta": node.resource,
            "desc": node.represents or status.state(node.id),
            "group": group,
        }
        for node in sorted(surface.nodes.values(), key=lambda item: (item.resource, item.name))
    ]


def step_options(steps: list[StepDef]) -> list[dict[str, str]]:
    """Every step of one keyword, the ones needing no code first.

    Order is the whole point: ATF's own steps first, then this suite's phrases, then the steps it
    had to write. An author takes the first plausible thing they see, and what that is teaches them
    whether assertions are something you write.
    """
    options = [
        {
            "value": step.pattern,
            "label": step.pattern,
            "meta": Path(step.file).name if step.file else "",
            "desc": summary_of(step),
            "group": _group(step),
            "rank": _rank(step),
        }
        for step in steps
    ]
    return sorted(options, key=lambda option: (option["rank"], option["label"]))


def summary_of(step: StepDef) -> str:
    """What a step says it does: its table entry where ATF defines it, else its own docstring."""
    own = generic(step.pattern)
    return own.summary if own else step.docstring


def _group(step: StepDef) -> str:
    if step.phrase:
        return "This suite's wording"
    return "Ready to use" if generic(step.pattern) is not None else "This suite's own"


def _rank(step: StepDef) -> str:
    if step.phrase:
        return "1"
    return "0" if generic(step.pattern) is not None else "2"


def subject_options(surface: Surface, steps: list[StepDef], row: Row) -> list[dict[str, str]]:
    """What a Then can be about: a resource, a whole type of them, a slot, or a step of your own.

    One question — *what are you asserting about?* — and answering it decides the shape of the rest.
    """
    options = resource_options(surface, group="A resource")
    # A whole type, for the one claim that is about a population and not about a resource:
    # "nothing was created the second time" names nothing, having nothing to name.
    for resource_type in surface.engine.resource_types():
        options.append(
            {
                "value": f"{TYPE_SUBJECT}{resource_type}",
                "label": f"every {resource_type}",
                "meta": resource_type,
                "desc": f"how many {resource_type} records this environment holds",
                "group": "All of a type",
            }
        )
    # One option per slot the rows above actually put there: a scenario with two actions has two
    # things to be about, and the picker is where that has to be visible.
    for name in sorted(row.produced):
        # `result` is the name ATF suggests, so it keeps ATF's wording. A slot a suite named itself
        # is said by that name — the name is the whole point of having chosen it.
        conventional = name == RESULT
        options.append(
            {
                "value": f"{SLOT_SUBJECT}{name}",
                "label": "what the step before produced" if conventional else f"what {name} holds",
                "meta": "" if conventional else name,
                "desc": (
                    "the records a When put on the context"
                    if conventional
                    else f"what a step above put on the context as {name}"
                ),
                "group": "A resource",
            }
        )
    for step in steps:
        # A step ATF defines is reached through the four choices, which is what a claim row is. The
        # exception is a step taking a table: the table *is* the comparison, so there is no
        # comparison to pick, and it is offered here by name with the rows filled in underneath.
        if generic(step.pattern) is not None and not step.takes_table:
            continue
        options.append(
            {
                "value": f"{STEP_SUBJECT}{step.pattern}",
                "label": step.pattern,
                "meta": Path(step.file).name if step.file else "",
                "desc": summary_of(step),
                # A phrase is not a step this suite defines — it is this suite's wording over
                # steps that needed no code, and saying so is what keeps someone from going
                # looking for the Python behind it.
                "group": _subject_group(step),
            }
        )
    return options


def _subject_group(step: StepDef) -> str:
    """Which heading a Then's subject picker files a step under.

    Not `_group`, which names the same steps for the *When* picker. Two pickers, two questions —
    a When asks what the scenario does and a Then asks what it is about — and a step means a
    different thing under each, so it is filed differently.
    """
    if step.takes_table and generic(step.pattern) is not None:
        return "A whole shape, said as a table"
    return "A phrase this suite writes" if step.phrase else "A step this suite defines"


def aspect_options(surface: Surface, node_id: str) -> list[dict[str, str]]:
    """The thing itself, or one of its fields. Which of the two decides what can be claimed."""
    options = [
        {"value": "", "label": "the resource itself", "meta": "", "desc": "whether it is there at all"}
    ]
    node = surface.nodes.get(node_id)
    if node is None:
        return options
    return options + [
        {"value": choice.name, "label": choice.name, "meta": choice.current, "desc": choice.source}
        for choice in field_choices(node, surface.status.of(node_id))
    ]


def comparison_options(subject: str, aspect: str) -> list[dict[str, str]]:
    return [
        {"value": item.key, "label": item.label, "meta": "", "desc": ""}
        for item in comparisons_for(subject_kind(subject), bool(aspect))
    ]


def table_fields(surface: Surface, row: Row) -> list[dict[str, str]]:
    """The fields a table row may name, and what each holds — empty where the row names no resource.

    A slot's shape has nothing to offer: the slot is filled by a step that has not run yet, so there
    is no record to read. Those rows are typed by hand.
    """
    node = surface.nodes.get(row.node_id) if row.node_id else None
    if node is None:
        return []
    return [
        {"name": choice.name, "current": choice.current, "source": choice.source}
        for choice in field_choices(node, surface.status.of(row.node_id))
    ]


def action_options(surface: Surface, resource_type: str) -> list[dict[str, str]]:
    """Everything this type says can be done to one of its resources, and what ATF can always do."""
    spec = surface.catalog.spec(resource_type)
    if spec is None:
        return []
    declared = set(spec.declared_actions)
    return [
        {
            "value": action,
            "label": action,
            "meta": "" if action in declared else "always",
            "desc": (
                f"declared on the {resource_type} type"
                if action in declared
                else "ATF's own — every adapter can remove a resource"
            ),
        }
        for action in spec.actions
    ]


def field_options(surface: Surface, resource_type: str, name: str) -> list[dict[str, str]]:
    """The fields of one resource, each carrying what it holds right now.

    Choosing a field from a list of bare names is guessing. Choosing `done` while the interface
    says it is currently `false` is writing an assertion with the answer in front of you.
    """
    node = surface.catalog.find(resource_type, name)
    if node is None:
        return []
    return [
        {"value": choice.name, "label": choice.name, "meta": choice.current, "desc": choice.source}
        for choice in field_choices(node, surface.status.of(node.id))
    ]


def current_value(surface: Surface, resource_type: str, name: str, of_field: str) -> str:
    node = surface.catalog.find(resource_type, name)
    if node is None:
        return ""
    return next(
        (
            choice.current
            for choice in field_choices(node, surface.status.of(node.id))
            if choice.name == of_field
        ),
        "",
    )


def held_fields(results: dict[str, TestResult]) -> list[str]:
    """Completions for a field of a slot, gathered from what the last run saw every slot hold.

    Across all slots, not per slot: it is a hint while typing, and a slot the run has never seen is
    exactly the case where a hint is worth having.
    """
    return sorted({name for result in results.values() for slot in result.held for name in slot.fields})


# ---- describe: what can be said here ----------------------------------------


def describe(surface: Surface, feature: str = "") -> dict[str, Any]:
    """Everything that decides what a scenario in this suite may say, as plain data.

    Nothing below enumerates a wording, a comparison or a marker: the tables that define them stay
    the only place they are written down, so this surface extends itself when they grow.
    """
    offered = offered_steps(surface, feature)
    binding = binding_module(surface.found, feature) if feature else None
    steps = {keyword: [_step_entry(step) for step in offered[keyword]] for keyword in KEYWORDS}

    return {
        "environment": surface.env,
        "specs": str(surface.specs_dir),
        "features": feature_options(surface.found),
        "resource_types": _types_described(surface),
        "resources": _resources_described(surface),
        "steps": steps,
        # A phrase is already among the steps above, and is listed again with what it stands for —
        # which is the whole of what a reader needs in order to trust it.
        "phrases": [
            {
                "pattern": step.pattern,
                "keyword": step.keyword,
                "means": list(step.expands_to),
                "file": step.file,
            }
            for keyword in KEYWORDS
            for step in offered[keyword]
            if step.phrase
        ],
        "comparisons": [_comparison_entry(item) for item in COMPARISONS],
        "markers": [{"marker": marker, "means": means} for marker, means in MARKERS.items()],
        # Named, not left out: a step this feature cannot reach is a step someone will go looking
        # for, and what they need is the two files to choose between.
        "out_of_reach": elsewhere(surface.found, offered, binding, surface.specs_dir),
    }


def _step_entry(step: StepDef) -> dict[str, Any]:
    """One step wording, and everything that decides whether a scenario may use it here."""
    own = generic(step.pattern)
    return {
        "pattern": step.pattern,
        "keyword": step.keyword,
        "captures": list(step.params),
        "needs": list(step.needs),
        "produces": list(step.produces),
        "needs_slot": step.needs_slot,
        "takes_table": step.takes_table,
        "defined_by": FROM_PHRASEBOOK if step.phrase else (FROM_ATF if own else FROM_SUITE),
        "summary": summary_of(step),
        "file": step.file,
    }


def _comparison_entry(item: Comparison) -> dict[str, Any]:
    return {
        "key": item.key,
        "label": item.label,
        "pattern": item.pattern,
        "about": item.subject,
        "names_a_field": item.field,
        "compared_with": item.target,
    }


def _types_described(surface: Surface) -> list[dict[str, Any]]:
    instances = instances_by_type(surface)
    described: list[dict[str, Any]] = []
    for name in surface.catalog.resource_types:
        spec = surface.catalog.types[name]
        described.append(
            {
                "name": name,
                "system": spec.system,
                "mode": spec.mode,
                "lifecycle": spec.lifecycle,
                "actions": spec.actions,
                "instances": [node.name for node in instances.get(name, [])],
            }
        )
    return described


def _resources_described(surface: Surface) -> list[dict[str, Any]]:
    described: list[dict[str, Any]] = []
    for node in sorted(surface.nodes.values(), key=lambda item: (item.resource, item.name)):
        entry = surface.status.of(node.id)
        described.append(
            {
                "id": node.id,
                "type": node.resource,
                "name": node.name,
                "represents": node.represents,
                "status": entry.state,
                "detail": entry.detail,
                "depends_on": list(node.depends_on),
                "fields": [
                    {"name": choice.name, "current": choice.current, "source": choice.source}
                    for choice in field_choices(node, entry)
                ],
            }
        )
    return described


# ---- compose: these choices, and the Gherkin they mean -----------------------


@dataclass
class Composition:
    """A draft, resolved: the lines it writes, and everything that stops it being a scenario."""

    title: str
    gherkin: str
    rows: list[Row] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.problems


def compose(
    surface: Surface, chosen: list[dict[str, Any]], title: str = "", feature: str = ""
) -> Composition:
    """A list of choices, turned into the scenario they mean or why they are not one yet.

    The refusals are the valuable half. An agent composing from `available steps × catalog nodes`
    cannot write a step this suite does not define or name a resource the catalog does not declare:
    nothing here turns those into a line. What comes back is a sentence naming the choice that does
    not exist.
    """
    offered = offered_steps(surface, feature)
    rows: list[Row] = []
    problems: list[str] = []
    for index, entry in enumerate(chosen):
        keyword = str(entry.get("keyword", "")).strip().lower()
        if keyword not in KEYWORDS:
            problems.append(
                f"row {index + 1} is a {keyword!r} step, and a scenario is written in "
                f"{', '.join(KEYWORDS)}."
            )
            continue
        rows.append(make_row(index, keyword, entry, offered, surface.catalog))

    resolve(rows, surface)
    if not title:
        problems.append("The scenario needs a title — it is the name the whole cockpit calls it by.")
    problems.extend(row_problems(rows))
    return Composition(title=title, gherkin=gherkin(title, rows), rows=rows, problems=problems)


# ---- try_scenario: run a draft without keeping it ----------------------------


@dataclass
class Trial:
    """What happened when a draft was run without being saved."""

    outcome: str = ""
    detail: str = ""
    step: str = ""
    duration: float = 0.0

    @property
    def passed(self) -> bool:
        return self.outcome == PASSED


def inside(path: Path, specs_dir: Path) -> Path:
    """Every write goes through here: a path outside `specs_dir` is refused, never clamped."""
    resolved, root = path.resolve(), specs_dir.resolve()
    if root not in resolved.parents:
        raise Outside(root)
    return resolved


def features_dir(surface: Surface) -> Path:
    """Where a new feature file belongs: beside the ones already there, else the specs root."""
    existing = sorted({Path(spec.file).parent for spec in surface.found.specs if spec.file})
    return existing[0] if existing else surface.specs_dir


def steps_dir(surface: Surface) -> Path:
    """Where the modules that bind features to pytest live — beside the ones already there."""
    existing = sorted({Path(test.file).parent for test in surface.found.tests if test.file})
    return existing[0] if existing else surface.specs_dir / "steps"


def rebound(source: str, feature: Path, module_dir: Path) -> str:
    """A steps module, rewritten so that it binds `feature` and nothing else.

    A copy is what makes a trial faithful: a step is only visible to the module that declares it, so
    a scenario tried beside a bare module reports steps missing that will resolve once it is saved.
    """
    call = f'scenarios("{Path(os.path.relpath(feature, module_dir)).as_posix()}")'
    seen = False

    def swap(match: re.Match[str]) -> str:
        nonlocal seen
        if seen:
            return ""  # one feature per scratch module: the rest would collect twice
        seen = True
        return call

    rewritten = _SCENARIOS_CALL.sub(swap, source)
    return rewritten if seen else f"{rewritten}\n\n{call}\n"


def try_scenario(surface: Surface, block: str, feature: str = "", heading: str = "") -> Trial:
    """Run this scenario from a scratch file, then take the file away again.

    Composing a scenario and being told to go and run it somewhere else is the point at which an
    interface stops being one. This writes the draft to a scratch feature, runs that one scenario,
    reports what happened, and removes it again — so the answer arrives before the decision to keep
    it does.
    """
    name = f"atf_trying_{secrets.token_hex(4)}"
    binding = binding_module(surface.found, feature) if feature else None
    scratch = inside(features_dir(surface) / f"{name}.feature", surface.specs_dir)
    module = inside(
        (binding.parent if binding else steps_dir(surface)) / f"test_{name}.py", surface.specs_dir
    )
    titled = heading or feature or "Trying a scenario"

    try:
        scratch.parent.mkdir(parents=True, exist_ok=True)
        module.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text(f"Feature: {titled}\n\n{block}", encoding="utf-8")
        # A copy of the module that will bind this scenario, so the trial sees the steps the real
        # run will. Bare, when the feature is new and no module binds it yet — which is also the
        # truth about what such a scenario would be able to reach.
        module.write_text(
            rebound(binding.read_text(encoding="utf-8"), scratch, module.parent)
            if binding
            else BINDING.format(
                name=scratch.name, path=Path(os.path.relpath(scratch, module.parent)).as_posix()
            ),
            encoding="utf-8",
        )
        summary = run_tests([str(module)], surface.env, surface.root, surface.specs_dir)
    finally:
        scratch.unlink(missing_ok=True)
        module.unlink(missing_ok=True)

    result = next(iter(summary.results.values()), None)
    if result is None:
        return Trial(outcome=ERROR, detail=summary.output[-600:] or "the run produced no result")
    failed = result.failed_step
    return Trial(
        outcome=result.outcome,
        detail=(failed.error if failed else "") or result.detail,
        step=f"{failed.keyword} {failed.text}".strip() if failed else "",
        duration=result.duration,
    )
