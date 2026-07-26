"""Specs — the behaviour, in plain English, linked to the resources it needs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..view import cockpit as app
from ..view import current_env, outcome_of, page, partial

router = APIRouter(prefix="/specs")


@router.get("")
def index(request: Request):
    env = current_env(request)
    found = app().discovery(env)
    focus = request.query_params.get("focus") or (found.specs[0].id if found.specs else "")
    return page(request, "specs.html", **_context(env, focus))


@router.get("/{spec_id:path}")
def detail(request: Request, spec_id: str):
    env = current_env(request)
    context = _context(env, spec_id)
    if request.headers.get("HX-Request") == "true":
        return partial(request, "partials/spec_detail.html", **context)
    return page(request, "specs.html", **context)


def _context(env: str, spec_id: str) -> dict[str, Any]:
    cockpit = app()
    found = cockpit.discovery(env)
    results = cockpit.results(env)
    nodes = cockpit.state(env).materializer.nodes
    spec = found.spec(spec_id)
    tests = found.tests_for_spec(spec_id) if spec else []

    return {
        "env": env,
        "title": "Specs",
        "specs": found.specs,
        "focus": spec_id,
        "spec": spec,
        "tests": tests,
        "nodes": nodes,
        "outcomes": {test.nodeid: outcome_of(test.nodeid, results) for test in tests},
        "results": results,
        "active": cockpit.active_job(env),
    }
