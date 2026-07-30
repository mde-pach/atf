"""A suite's features, steps and fixtures as a structured model."""

from __future__ import annotations

from pathlib import Path

from ...model.catalog import Catalog
from .model import Discovery, Fixture, Question, Spec, Step, StepDef, Test, slug
from .observe import attach_fixtures, attach_tests, observe_pytest
from .parse import (
    attach_context_use,
    context_use,
    matching_step,
    parse_feature,
    parse_questions,
    parse_specs,
    questions_in,
    step_defs,
)

__all__ = [
    "Discovery",
    "Fixture",
    "Question",
    "Spec",
    "Step",
    "StepDef",
    "Test",
    "context_use",
    "discover",
    "matching_step",
    "parse_feature",
    "parse_questions",
    "parse_specs",
    "questions_in",
    "slug",
    "step_defs",
]


def discover(
    specs_dir: Path,
    catalog: Catalog,
    env: str,
    project_root: Path | None = None,
) -> Discovery:
    specs = parse_specs(specs_dir, catalog)
    result = Discovery(specs=specs, questions=parse_questions(specs_dir))

    root = project_root or specs_dir.parent
    observed, errors = observe_pytest(root, specs_dir, env)
    result.errors = errors
    attach_tests(result, observed, catalog.nodes)
    result.fixtures = attach_fixtures(root, env, observed, set(catalog.types), errors, result.tests)
    result.steps = step_defs(observed)
    attach_context_use(result.steps)
    result.index()
    return result
