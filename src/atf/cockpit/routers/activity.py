"""The one place the cockpit changes anything: start a run, start provisioning, watch either."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request

from ...run.jobs import RUN, Job, Row
from ...run.runner import TestResult
from ..view import cockpit as app
from ..view import current_env, partial, require_confirmation, require_mutable

router = APIRouter()

NODEIDS = Form(default=[])
NODES = Form(default=[])
CONFIRM = Form(default="")

POLL_MS = 400

# Provisioning changes the environment, so the cached status is wrong the moment a job ends.
# Refresh once per job, and not on every poll.
_settled: set[str] = set()


@router.post("/run")
def start_run(request: Request, nodeid: list[str] = NODEIDS, confirm: str = CONFIRM):
    env = current_env(request)
    require_mutable(env)
    require_confirmation(confirm)

    cockpit = app()
    # Form values become pytest argv, so only ids the cockpit itself discovered may pass: otherwise
    # `-p evil_module` or an arbitrary path would be honoured.
    known = {test.nodeid for test in cockpit.discovery.of(env).tests}
    selected = [item for item in nodeid if item in known]
    if nodeid and not selected:
        raise HTTPException(status_code=409, detail="none of those tests belong to this suite")
    cockpit.jobs.start_run(selected or sorted(known), env)
    return partial(request, "partials/activity.html", **_context(env))


@router.post("/provision")
def start_provision(request: Request, node: list[str] = NODES, confirm: str = CONFIRM):
    env = current_env(request)
    require_mutable(env)
    require_confirmation(confirm)

    cockpit = app()
    nodes = cockpit.state(env).materializer.nodes
    selected = [item for item in node if item in nodes]
    if node and not selected:
        raise HTTPException(status_code=409, detail="none of those resources are in this catalog")

    targets = selected or cockpit.jobs.provision_targets(env)
    if not targets:
        raise HTTPException(status_code=409, detail=f"nothing to provision — {env} already has every resource")
    cockpit.jobs.start_provision(targets, env)
    return partial(request, "partials/activity.html", **_context(env))


@router.get("/activity")
def activity(request: Request):
    return partial(request, "partials/activity.html", **_context(current_env(request)))


def _context(env: str) -> dict[str, Any]:
    cockpit = app()
    job = cockpit.jobs.active(env) or next(iter(cockpit.jobs.recent(env, limit=1)), None)

    if job is not None and job.done and job.kind == "provision" and job.id not in _settled:
        _settled.add(job.id)
        cockpit.status.of(env, refresh=True)

    return {"env": env, "job": job, "items": _items(env, job), "poll_ms": POLL_MS}


def _items(env: str, job: Job | None) -> list[Row]:
    """A job's rows, the unfinished ones first, with a run's tests named as a person recognises them.

    A provisioning row is already called what it is — its node id — so only a run needs naming, and
    only here: a job can be started before discovery has run, so the name is resolved at render.
    """
    if job is None:
        return []
    ordered = sorted(job.items.values(), key=lambda item: (item.done, item.id))
    if job.kind != RUN:
        return ordered

    named = app().discovery.of(env).scenario_names()
    for item in ordered:
        if isinstance(item, TestResult):
            item.label = named.get(item.nodeid) or item.label or item.nodeid.rsplit("::", 1)[-1]
    return ordered
