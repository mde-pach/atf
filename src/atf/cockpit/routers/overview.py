"""Overview — the landing vertical: can I ship with confidence?"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..view import cockpit as app
from ..view import (
    config_meter,
    coverage_gaps,
    coverage_meter,
    current_env,
    health_meter,
    outcome_of,
    page,
)

router = APIRouter()


@router.get("/")
def overview(request: Request):
    env = current_env(request)
    cockpit = app()
    state = cockpit.state(env)
    status = cockpit.status(env)
    found = cockpit.discovery(env)
    results = cockpit.results(env)

    absent = [nid for nid, entry in status.items() if entry["status"] == "absent"]
    failing = [test for test in found.tests if outcome_of(test.nodeid, results) in {"failed", "error"}]

    return page(
        request,
        "overview.html",
        env=env,
        title="Overview",
        meters=[
            config_meter(status),
            coverage_meter(found, state.materializer.nodes),
            health_meter(found, results),
        ],
        absent=absent,
        failing=failing,
        gaps=coverage_gaps(found, state.materializer.nodes),
        jobs=cockpit.recent_jobs(env),
        active=cockpit.active_job(env),
        discovery_errors=found.errors,
    )


@router.get("/overview/meters")
def meters(request: Request):
    """Out-of-band refresh target after a run or a seed."""
    env = current_env(request)
    cockpit = app()
    state = cockpit.state(env)
    found = cockpit.discovery(env)
    return page(
        request,
        "partials/meters.html",
        env=env,
        meters=[
            config_meter(cockpit.status(env)),
            coverage_meter(found, state.materializer.nodes),
            health_meter(found, cockpit.results(env)),
        ],
    )
