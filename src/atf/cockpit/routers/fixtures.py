"""Fixtures — what tests build on, including the generated resource factories."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..view import cockpit as app
from ..view import current_env, page, partial

router = APIRouter(prefix="/fixtures")


@router.get("")
def index(request: Request):
    env = current_env(request)
    found = app().discovery(env)
    focus = request.query_params.get("focus") or (found.fixtures[0].name if found.fixtures else "")
    return page(request, "fixtures.html", **_context(env, focus))


@router.get("/{name}")
def detail(request: Request, name: str):
    env = current_env(request)
    context = _context(env, name)
    if request.headers.get("HX-Request") == "true":
        return partial(request, "partials/fixture_detail.html", **context)
    return page(request, "fixtures.html", **context)


def _context(env: str, name: str) -> dict[str, Any]:
    cockpit = app()
    found = cockpit.discovery(env)
    fixture = found.fixture(name)
    by_nodeid = {test.nodeid: test for test in found.tests}

    return {
        "env": env,
        "title": "Fixtures",
        "fixtures": found.fixtures,
        "focus": name,
        "fixture": fixture,
        "used_by": [by_nodeid[nodeid] for nodeid in (fixture.used_by if fixture else []) if nodeid in by_nodeid],
    }
