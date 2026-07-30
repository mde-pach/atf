"""The choices, each carrying what is needed to make it."""

from __future__ import annotations

from pathlib import Path

from ...engine.status import Statuses
from ...model.catalog import Node
from ...model.text import plural
from ...model.typespec import DATA, REFERENCE
from ...run.runner import TestResult
from ...spec.context import RESULT
from ...spec.steps import comparisons_for, generic
from ...suite.discovery import Discovery, StepDef
from .fields import field_choices
from .rows import Row
from .surface import (
    NODE_SUBJECT,
    SLOT_SUBJECT,
    STEP_SUBJECT,
    TYPE_SUBJECT,
    Option,
    Surface,
    subject_kind,
    summary_of,
)


def feature_options(found: Discovery) -> list[Option]:
    counts: dict[str, int] = {}
    for spec in found.specs:
        counts[spec.feature] = counts.get(spec.feature, 0) + 1
    return [
        Option(value=name, label=name, meta=plural(counts.get(name, 0), "scenario"))
        for name in sorted(counts)
    ]

def instances_by_type(surface: Surface) -> dict[str, list[Node]]:
    grouped: dict[str, list[Node]] = {}
    for node in sorted(surface.nodes.values(), key=lambda item: item.name):
        grouped.setdefault(node.resource, []).append(node)
    return grouped

def type_options(surface: Surface) -> list[Option]:
    status = surface.status
    instances = instances_by_type(surface)
    options: list[Option] = []
    for name in surface.catalog.resource_types:
        spec = surface.catalog.types[name]
        members = instances.get(name, [])
        present = sum(1 for node in members if status.of(node.id).present)
        note = " · built fresh per run" if spec.ephemeral else ""
        note += " · must already exist here" if spec.mode == REFERENCE else ""
        note += " · observed, never created" if spec.mode == DATA else ""
        options.append(
            Option(
                value=name,
                label=name,
                meta=spec.system,
                desc=f"{len(members)} in the catalog, {present} present in this environment{note}",
            )
        )
    return options

def instance_options(members: list[Node], status: Statuses) -> list[Option]:
    """The resources of one type, each with where it stands and what it is for.

    Choosing between `primary` and `secondary` is impossible from the names alone, which is exactly
    what `represents` was written to answer.
    """
    return [
        Option(value=node.name, label=node.name, meta=status.state(node.id), desc=node.represents or node.id)
        for node in members
    ]

def resource_options(surface: Surface, group: str = "") -> list[Option]:
    status = surface.status
    return [
        Option(
            value=f"{NODE_SUBJECT}{node.id}",
            label=node.name,
            meta=node.resource,
            desc=node.represents or status.state(node.id),
            group=group,
        )
        for node in sorted(surface.nodes.values(), key=lambda item: (item.resource, item.name))
    ]

def step_options(steps: list[StepDef]) -> list[Option]:
    """Every step of one keyword, the ones needing no code first.

    Order is the whole point: ATF's own steps first, then this suite's phrases, then the steps it
    had to write. An author takes the first plausible thing they see, and what that is teaches them
    whether assertions are something you write.
    """
    return sorted(
        (
            Option(
                value=step.pattern,
                label=step.pattern,
                meta=Path(step.file).name if step.file else "",
                desc=summary_of(step),
                group=_group(step),
            )
            for step in steps
        ),
        key=lambda option: (_rank(option.group), option.label),
    )

def subject_options(surface: Surface, steps: list[StepDef], row: Row) -> list[Option]:
    """What a Then can be about: a resource, a whole type of them, a slot, or a step of your own.

    One question — *what are you asserting about?* — and answering it decides the shape of the rest.
    """
    options = resource_options(surface, group="A resource")
    # A whole type, for the one claim that is about a population and not about a resource:
    # "nothing was created the second time" names nothing, having nothing to name.
    for resource_type in surface.engine.resource_types():
        options.append(
            Option(
                value=f"{TYPE_SUBJECT}{resource_type}",
                label=f"every {resource_type}",
                meta=resource_type,
                desc=f"how many {resource_type} records this environment holds",
                group="All of a type",
            )
        )
    # One option per slot the rows above actually put there: a scenario with two actions has two
    # things to be about, and the picker is where that has to be visible.
    for name in sorted(row.produced):
        # `result` is the name ATF suggests, so it keeps ATF's wording. A slot a suite named itself
        # is said by that name — the name is the whole point of having chosen it.
        conventional = name == RESULT
        options.append(
            Option(
                value=f"{SLOT_SUBJECT}{name}",
                label="what the step before produced" if conventional else f"what {name} holds",
                meta="" if conventional else name,
                desc=(
                    "the records a When put on the context"
                    if conventional
                    else f"what a step above put on the context as {name}"
                ),
                group="A resource",
            )
        )
    for step in steps:
        # A step ATF defines is reached through the four choices, which is what a claim row is. The
        # exception is a step taking a table: the table *is* the comparison, so there is no
        # comparison to pick, and it is offered here by name with the rows filled in underneath.
        if generic(step.pattern) is not None and not step.takes_table:
            continue
        # A phrase is not a step this suite defines — it is this suite's wording over steps that
        # needed no code, and saying so keeps someone from going looking for the Python behind it.
        options.append(
            Option(
                value=f"{STEP_SUBJECT}{step.pattern}",
                label=step.pattern,
                meta=Path(step.file).name if step.file else "",
                desc=summary_of(step),
                group=_subject_group(step),
            )
        )
    return options

def aspect_options(surface: Surface, node_id: str) -> list[Option]:
    """The thing itself, or one of its fields. Which of the two decides what can be claimed."""
    options = [Option(value="", label="the resource itself", desc="whether it is there at all")]
    node = surface.nodes.get(node_id)
    if node is None:
        return options
    return options + [choice.as_option() for choice in field_choices(node, surface.status.of(node_id))]

def comparison_options(subject: str, aspect: str) -> list[Option]:
    return [
        Option(value=item.key, label=item.label)
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

def action_options(surface: Surface, resource_type: str) -> list[Option]:
    """Everything this type says can be done to one of its resources, and what ATF can always do."""
    spec = surface.catalog.spec(resource_type)
    if spec is None:
        return []
    declared = set(spec.declared_actions)
    return [
        Option(
            value=action,
            label=action,
            meta="" if action in declared else "always",
            desc=(
                f"declared on the {resource_type} type"
                if action in declared
                else "ATF's own — every adapter can remove a resource"
            ),
        )
        for action in spec.actions
    ]

def field_options(surface: Surface, resource_type: str, name: str) -> list[Option]:
    """The fields of one resource, each carrying what it holds right now.

    Choosing a field from a list of bare names is guessing. Choosing `done` while the interface
    says it is currently `false` is writing an assertion with the answer in front of you.
    """
    node = surface.catalog.find(resource_type, name)
    if node is None:
        return []
    return [choice.as_option() for choice in field_choices(node, surface.status.of(node.id))]

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


# The headings a When's step picker files a step under, worst-to-best order and all. An author
# takes the first plausible thing they see, and what that is teaches them whether assertions are
# something you write.
READY, WORDING, OWN = "Ready to use", "This suite's wording", "This suite's own"

_ORDER = (READY, WORDING, OWN)


def _group(step: StepDef) -> str:
    if step.phrase:
        return WORDING
    return READY if generic(step.pattern) is not None else OWN


def _rank(group: str) -> int:
    return _ORDER.index(group) if group in _ORDER else len(_ORDER)


def _subject_group(step: StepDef) -> str:
    """Which heading a Then's subject picker files a step under.

    Not `_group`, which names the same steps for the *When* picker. Two pickers, two questions —
    a When asks what the scenario does and a Then asks what it is about — and a step means a
    different thing under each, so it is filed differently.
    """
    if step.takes_table and generic(step.pattern) is not None:
        return "A whole shape, said as a table"
    return "A phrase this suite writes" if step.phrase else "A step this suite defines"
