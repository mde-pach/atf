"""The one place the cockpit changes anything: start a run, start provisioning, watch either.

Both are the same shape — a list of things attempted one at a time — so they share a job, a
progress partial and a dock that stays on screen while you navigate elsewhere.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request

from ..view import cockpit as app
from ..view import current_env, partial, require_confirmation, require_mutable

router = APIRouter()

NODEIDS = Form(default=[])
NODES = Form(default=[])
CONFIRM = Form(default="")

POLL_MS = 400

# Provisioning changes the environment, so the cached status is wrong the moment a job ends.
# Refresh once per job rather than on every poll.
_settled: set[str] = set()


@router.post("/run")
def start_run(request: Request, nodeid: list[str] = NODEIDS, confirm: str = CONFIRM):
    env = current_env(request)
    require_mutable(env)
    require_confirmation(confirm)

    cockpit = app()
    # Form values become pytest argv, so only ids the cockpit itself discovered may pass: otherwise
    # `-p evil_module` or an arbitrary path would be honoured.
    known = {test.nodeid for test in cockpit.discovery(env).tests}
    selected = [item for item in nodeid if item in known]
    if nodeid and not selected:
        raise HTTPException(status_code=409, detail="none of those tests belong to this suite")
    cockpit.start_run(selected or sorted(known), env)
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

    targets = selected or cockpit.provision_targets(env)
    if not targets:
        raise HTTPException(status_code=409, detail=f"nothing to provision — {env} already has every resource")
    cockpit.start_provision(targets, env)
    return partial(request, "partials/activity.html", **_context(env))


@router.get("/activity")
def activity(request: Request):
    return partial(request, "partials/activity.html", **_context(current_env(request)))


def _context(env: str) -> dict[str, Any]:
    cockpit = app()
    job = cockpit.active_job(env) or next(iter(cockpit.recent_jobs(env, limit=1)), None)

    if job is not None and job.done and job.kind == "provision" and job.id not in _settled:
        _settled.add(job.id)
        cockpit.status(env, refresh=True)

    return {"env": env, "job": job, "items": _items(env, job), "poll_ms": POLL_MS}


def _items(env: str, job: Any) -> list[Any]:
    """Job items with labels a person recognises, resolved here rather than stored on the job."""
    if job is None:
        return []
    cockpit = app()
    if job.kind == "provision":
        labels = {node_id: node_id for node_id in cockpit.state(env).materializer.nodes}
    else:
        found = cockpit.discovery(env)
        by_spec = {spec.id: spec.scenario for spec in found.specs}
        labels = {
            test.nodeid: f"{by_spec.get(test.covers, test.name)}{f' [{test.params}]' if test.params else ''}"
            for test in found.tests
        }

    ordered = sorted(job.items.values(), key=lambda item: (item.done, item.id))
    for item in ordered:
        item.label = labels.get(item.id, item.label or item.id.rsplit("::", 1)[-1])
    return ordered
