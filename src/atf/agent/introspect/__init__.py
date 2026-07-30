"""What can be said about this environment, read out as data."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...model.compare import MARKERS
from ...run.runner import ERROR, PASSED
from ...run.runner import run as run_tests
from ...spec.vocabulary import COMPARISONS, Comparison, generic
from ...suite.discovery import StepDef
from .fields import FieldChoice, field_choices, written
from .options import (
    action_options,
    aspect_options,
    comparison_options,
    current_value,
    feature_options,
    field_options,
    held_fields,
    instance_options,
    instances_by_type,
    resource_options,
    step_options,
    subject_options,
    table_fields,
    type_options,
)
from .rows import (
    Row,
    gherkin,
    held_before,
    make_row,
    produced_before,
    read_claim,
    resolve,
    row_problems,
    table_lines,
    usable,
    write_claim,
)
from .surface import (
    FROM_ATF,
    FROM_PHRASEBOOK,
    FROM_SUITE,
    KEYWORDS,
    NODE_SUBJECT,
    SLOT_SUBJECT,
    STEP_SUBJECT,
    TYPE_SUBJECT,
    Option,
    Outside,
    Surface,
    binding_module,
    elsewhere,
    features,
    offered_steps,
    reachable,
    subject_kind,
    summary_of,
)

__all__ = [
    "Composition",
    "FROM_ATF",
    "FROM_PHRASEBOOK",
    "FROM_SUITE",
    "FieldChoice",
    "KEYWORDS",
    "NODE_SUBJECT",
    "Option",
    "Outside",
    "Row",
    "SLOT_SUBJECT",
    "STEP_SUBJECT",
    "Surface",
    "TYPE_SUBJECT",
    "Trial",
    "action_options",
    "aspect_options",
    "binding_module",
    "comparison_options",
    "compose",
    "current_value",
    "describe",
    "elsewhere",
    "feature_options",
    "features",
    "features_dir",
    "field_choices",
    "field_options",
    "gherkin",
    "held_before",
    "held_fields",
    "inside",
    "instance_options",
    "instances_by_type",
    "make_row",
    "offered_steps",
    "produced_before",
    "reachable",
    "read_claim",
    "rebound",
    "resolve",
    "resource_options",
    "row_problems",
    "step_options",
    "steps_dir",
    "subject_kind",
    "subject_options",
    "summary_of",
    "table_fields",
    "table_lines",
    "try_scenario",
    "type_options",
    "usable",
    "write_claim",
    "written",
]
# A `scenarios(...)` call on its own line — what binds a feature to pytest.
_SCENARIOS_CALL = re.compile(r"^[ \t]*scenarios\((?:[^()]|\([^()]*\))*\)[ \t]*$", re.MULTILINE)

# What a scratch module for a trial holds when the feature is new: nothing but the binding, which is
# also the truth about what such a scenario can reach. Nothing writes one of these to keep — ATF
# collects a `.feature` nobody bound, so a composed scenario needs no Python beside it.
BINDING = '''"""Binds {name} for one trial run. Written and removed by the composer."""

from pytest_bdd import scenarios

scenarios("{path}")
'''

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
        "features": [option.as_dict() for option in feature_options(surface.found)],
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
