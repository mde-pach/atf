"""Scenarios — the one vertical for seeking behaviour: find it, trust it, run it, read why it is red."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...run.jobs import RUN
from ..view import (
    BLOCKED,
    FAILING,
    NEVER_RUN,
    PASSING,
    ScenarioView,
    current_env,
    is_htmx,
    page,
    partial,
    scenario_views,
)
from ..view import cockpit as app

router = APIRouter(prefix="/scenarios")

# The states worth filtering by, in the order someone triaging asks for them.
FILTERS = (FAILING, BLOCKED, NEVER_RUN, PASSING)


@router.get("")
def index(request: Request):
    env = current_env(request)
    # Overview links straight to a state ("show me the failing ones"), so arriving here filtered
    # is a first-class way in, not a refinement you make once you are already looking at the list.
    preset = request.query_params.get("state", "")
    focus = request.query_params.get("focus", "")
    context = _context(env, focus, prefer=preset if not focus else "")
    context["preset"] = preset
    return page(request, "scenarios.html", **context)


@router.get("/{spec_id:path}")
def detail(request: Request, spec_id: str):
    env = current_env(request)
    context = _context(env, spec_id)
    if is_htmx(request):
        return partial(request, "partials/scenario_detail.html", **context)
    return page(request, "scenarios.html", **context)


def _context(env: str, spec_id: str, prefer: str = "") -> dict[str, Any]:
    views = scenario_views(env)
    view = next((candidate for candidate in views if candidate.id == spec_id), None)
    if view is None and prefer:
        # Arriving filtered to a state and being shown a scenario in a different one is a
        # non-answer: open the first scenario the filter actually matched.
        view = next((candidate for candidate in views if candidate.state == prefer), None)
    if view is None:
        view = views[0] if views else None

    return {
        "env": env,
        "title": "Scenarios",
        "views": views,
        "view": view,
        "focus": view.id if view else "",
        "status": app().status.of(env),
        "results": app().results.of(env),
        # Named by the name the scenario used: a step reads `visitor`, never `guests.visitor`.
        "nodes": app().state(env).materializer.nodes,
        # What a run currently has in flight, so a verdict on screen moves with it.
        "busy": _busy(env),
        "failed_index": _failed_index(view) if view else None,
        "tally": {state: sum(1 for item in views if item.state == state) for state in FILTERS},
        # The red cards of an Example Mapping session, kept where they were written. Handed over
        # keyed by the rule they sit under, which is where the list renders them.
        "questions": _questions(env),
        "preset": "",
    }


def _questions(env: str) -> dict[tuple[str, str], list[Any]]:
    asked: dict[tuple[str, str], list[Any]] = {}
    for question in app().discovery.of(env).questions:
        asked.setdefault((question.feature, question.rule), []).append(question)
    return asked


def _busy(env: str) -> set[str]:
    """The tests a run has started and not finished. Empty whenever nothing is running."""
    job = app().jobs.active(env)
    if job is None or job.kind != RUN:
        return set()
    return {item.id for item in job.items.values() if not item.done}


def _failed_index(view: ScenarioView) -> int | None:
    """Which Gherkin step the failure lands on, so the error can be shown where it happened.

    The runner reports the step as pytest-bdd saw it; matching on keyword and text first keeps a
    repeated `And` honest, and text alone is the fallback when the keyword was normalised.
    """
    failed = view.failed_step
    if failed is None:
        return None
    steps = view.spec.steps
    for index, step in enumerate(steps):
        if step.keyword == failed.keyword and step.text == failed.text:
            return index
    return next((index for index, step in enumerate(steps) if step.text == failed.text), None)
