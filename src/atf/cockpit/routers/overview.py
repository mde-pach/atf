"""Overview — the landing vertical, and the one question it answers: can I ship."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...engine.status import PRESENT
from ...model.text import plural
from ...suite.discovery import Discovery
from ..view import (
    BLOCKED,
    FAILING,
    NEVER_RUN,
    PASSING,
    SKIPPED_STATE,
    ScenarioView,
    current_env,
    page,
    partial,
    readiness,
    scenario_views,
    type_views,
    verdict,
)
from ..view import cockpit as app

router = APIRouter()

PURPOSE = "What the last run said, what is standing in the way, and what to do next."

# The order a reader wants them in: the two verdicts first, then the three kinds of "did not say".
STATES = (PASSING, FAILING, BLOCKED, NEVER_RUN, SKIPPED_STATE)

RUNS = 5


@router.get("/")
def overview(request: Request) -> Any:
    return page(request, "overview.html", **_context(current_env(request)))


@router.get("/overview/summary")
def summary(request: Request) -> Any:
    """The whole answer as a fragment.

    The activity dock pulls `#verdict` out of this after a run or a provision finishes, so the
    headline re-syncs without a reload, the verdict living in an element of its own.
    """
    return partial(request, "partials/summary.html", **_context(current_env(request)))


def _context(env: str) -> dict[str, Any]:
    cockpit = app()
    engine = cockpit.state(env).materializer
    nodes = engine.catalog.nodes
    status = cockpit.status.of(env)
    found = cockpit.discovery.of(env)
    scenarios = scenario_views(env)

    buckets = {state: [view for view in scenarios if view.state == state] for state in STATES}
    ready = readiness(sorted(nodes), engine, status)
    targets = cockpit.jobs.provision_targets(env)
    first_run = cockpit.results.last_run(env) is None

    return {
        "env": env,
        "title": "Overview",
        "purpose": PURPOSE,
        "verdict": verdict(env, scenarios),
        "states": [{"state": state, "count": len(views)} for state, views in buckets.items()],
        "total": len(scenarios),
        "failing": buckets[FAILING],
        "first_run": first_run,
        "steps": _steps(first_run, targets, scenarios),
        "run_label": f"Run all {plural(len(scenarios), 'scenario')}",
        "run_blocked": "" if scenarios else "this suite has no scenarios yet",
        "present": status.count(PRESENT),
        "resources": len(nodes),
        "absent": ready.will_create,
        "broken": ready.blockers,
        "runs": cockpit.results.recent_runs(env, RUNS),
        "flaky": _flaky(env, found),
        "unexercised": [name for name, view in type_views(env).items() if not view.specs],
        # The red cards of an Example Mapping session: a gap in the *description*, where everything
        # else on this page is a gap in the coverage. An unanswered question is the earliest form of
        # a bug, and the cheapest place to catch one.
        "questions": found.questions,
        "never_run": buckets[NEVER_RUN],
        "skipped": buckets[SKIPPED_STATE],
        "errors": found.errors,
        # Discovery failing outright is not a footnote: every count below it is a claim about an
        # empty model, and saying so is the only honest thing this page can do.
        "collection_failed": bool(found.errors) and not found.specs,
    }


def _steps(first_run: bool, targets: list[str], scenarios: list[ScenarioView]) -> list[dict[str, str]]:
    """The numbered path out of an empty environment. Three zeros teach nobody anything."""
    if not first_run:
        return []
    steps: list[dict[str, str]] = []
    if targets:
        steps.append({"kind": "provision", "label": f"Provision {plural(len(targets), 'resource')}"})
    if scenarios:
        steps.append({"kind": "run", "label": f"Run {plural(len(scenarios), 'scenario')}"})
    return steps


def _flaky(env: str, found: Discovery) -> list[tuple[str, int]]:
    """Flaky tests under the scenario title they belong to — nobody recognises a pytest nodeid."""
    titles = {spec.id: spec.scenario for spec in found.specs}
    labels = {test.nodeid: titles.get(test.covers) or test.name for test in found.tests}
    return [(labels.get(nodeid, nodeid), flips) for nodeid, flips in app().results.flaky(env).items()]
