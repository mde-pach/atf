"""Tests — grouped by the spec they cover, selectable and runnable with live progress."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request

from ..view import cockpit as app
from ..view import current_env, outcome_of, page, partial, require_confirmation, require_mutable

router = APIRouter(prefix="/tests")

NODEIDS = Form(default=[])
CONFIRM = Form(default="")

POLL_MS = 400


@router.get("")
def index(request: Request):
    env = current_env(request)
    found = app().discovery(env)
    focus = request.query_params.get("focus") or (found.tests[0].id if found.tests else "")
    return page(request, "tests.html", **_context(env, focus))


@router.get("/detail/{test_id}")
def detail(request: Request, test_id: str):
    env = current_env(request)
    context = _context(env, test_id)
    if request.headers.get("HX-Request") == "true":
        return partial(request, "partials/test_detail.html", **context)
    return page(request, "tests.html", **context)


@router.post("/run")
def run(request: Request, nodeid: list[str] = NODEIDS, confirm: str = CONFIRM):
    env = current_env(request)
    require_mutable(env)
    require_confirmation(confirm)

    cockpit = app()
    # Form values become pytest argv, so only ids the cockpit itself discovered may pass:
    # otherwise `-p evil_module` or an arbitrary path would be honoured.
    known = {test.nodeid for test in cockpit.discovery(env).tests}
    selected = [item for item in nodeid if item in known]
    if nodeid and not selected:
        raise HTTPException(status_code=409, detail="none of the selected tests are known to this suite")
    if not selected:
        selected = sorted(known)
    cockpit.start_run(selected, env)
    return partial(request, "partials/run_progress.html", **_progress(env))


@router.get("/progress")
def progress(request: Request):
    return partial(request, "partials/run_progress.html", **_progress(current_env(request)))


def _progress(env: str) -> dict[str, Any]:
    cockpit = app()
    job = cockpit.active_job(env)
    found = cockpit.discovery(env)
    results = cockpit.results(env)
    by_nodeid = {test.nodeid: test for test in found.tests}

    if job is not None:
        rows = [
            {
                "nodeid": nodeid,
                "name": by_nodeid[nodeid].name if nodeid in by_nodeid else nodeid.rsplit("::", 1)[-1],
                "state": state.state,
                "duration": state.duration,
                "detail": state.detail,
            }
            for nodeid, state in job.states.items()
        ]
    else:
        rows = [
            {
                "nodeid": test.nodeid,
                "name": test.name,
                "state": outcome_of(test.nodeid, results),
                "duration": results[test.nodeid].duration if test.nodeid in results else 0.0,
                "detail": results[test.nodeid].detail if test.nodeid in results else "",
            }
            for test in found.tests
        ]

    return {
        "env": env,
        "job": job,
        "rows": sorted(rows, key=lambda row: row["nodeid"]),
        "poll_ms": POLL_MS,
        "running": job is not None and not job.done,
        "last": cockpit.recent_jobs(env, limit=1),
    }


def _context(env: str, test_id: str) -> dict[str, Any]:
    cockpit = app()
    found = cockpit.discovery(env)
    results = cockpit.results(env)
    test = found.test(test_id)

    grouped: dict[str, list[Any]] = {}
    for item in found.tests:
        grouped.setdefault(item.covers or "", []).append(item)

    return {
        "env": env,
        "title": "Tests",
        "groups": {
            spec_id: (found.spec(spec_id), members) for spec_id, members in sorted(grouped.items())
        },
        "focus": test_id,
        "test": test,
        "spec": found.spec(test.covers) if test else None,
        "fixtures": [found.fixture(name) for name in test.fixtures] if test else [],
        "nodes": cockpit.state(env).materializer.nodes,
        "outcomes": {item.nodeid: outcome_of(item.nodeid, results) for item in found.tests},
        "results": results,
        "active": cockpit.active_job(env),
        "poll_ms": POLL_MS,
    }
