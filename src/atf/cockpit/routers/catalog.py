"""Catalog — resources, their lineage graph, and the inspector."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request

from ...catalog import Node
from ..view import build_graph, current_env, page, partial, require_confirmation, require_mutable
from ..view import cockpit as app

router = APIRouter(prefix="/catalog")


@router.get("")
def index(request: Request):
    env = current_env(request)
    nodes = app().state(env).materializer.nodes
    focus = request.query_params.get("focus") or (sorted(nodes)[0] if nodes else "")
    return page(request, "catalog.html", **_context(env, focus))


@router.get("/node/{node_id}")
def node_detail(request: Request, node_id: str):
    env = current_env(request)
    context = _context(env, node_id)
    if request.headers.get("HX-Request") == "true":
        return partial(request, "partials/catalog_focus.html", **context)
    return page(request, "catalog.html", **context)


@router.post("/sync")
def sync(request: Request):
    env = current_env(request)
    cockpit = app()
    cockpit.invalidate(env)
    cockpit.status(env, refresh=True)
    focus = request.query_params.get("focus") or ""
    context = _context(env, focus, banner="Synced from the environment.")
    return partial(request, "partials/catalog_focus.html", **context)


@router.post("/create/{node_id}")
def create(request: Request, node_id: str, confirm: str = Form(default="")):
    env = current_env(request)
    require_mutable(env)
    require_confirmation(confirm)

    cockpit = app()
    engine = cockpit.state(env).materializer
    if node_id not in engine.nodes:
        raise HTTPException(status_code=404, detail=f"no resource {node_id!r} in the catalog")
    outcome = engine.create_closure(node_id)
    cockpit.status(env, refresh=True)
    return partial(request, "partials/catalog_focus.html", **_context(env, node_id, **_banner(outcome)))


@router.post("/seed")
def seed(request: Request, confirm: str = Form(default="")):
    env = current_env(request)
    require_mutable(env)
    require_confirmation(confirm)

    cockpit = app()
    engine = cockpit.state(env).materializer
    absent = [nid for nid, entry in cockpit.status(env).items() if entry["status"] in {"absent", "error"}]
    outcome = engine.materialize(absent) if absent else {"results": [], "records": {}}
    cockpit.status(env, refresh=True)

    focus = request.query_params.get("focus") or (sorted(engine.nodes)[0] if engine.nodes else "")
    return partial(request, "partials/catalog_focus.html", **_context(env, focus, **_banner(outcome)))


# ---- context ---------------------------------------------------------------


def _context(env: str, node_id: str, **extra: Any) -> dict[str, Any]:
    cockpit = app()
    nodes = cockpit.state(env).materializer.nodes
    status = cockpit.status(env)
    found = cockpit.discovery(env)
    node = nodes.get(node_id)

    return {
        "env": env,
        "title": "Catalog",
        "collections": _collections(nodes),
        "status": status,
        "focus": node_id,
        "node": node,
        "graph": build_graph(nodes, node_id, status) if node else None,
        "needs": [nodes[dep] for dep in node["depends_on"]] if node else [],
        "used_by": [nodes[dep] for dep in node["dependents"]] if node else [],
        "tests": found.tests_for_resource(node_id) if node else [],
        "specs": found.specs_for_resource(node_id) if node else [],
        "absent": [nid for nid, entry in status.items() if entry["status"] == "absent"],
        "banner": "",
        "banner_tone": "ok",
        **extra,
    }


def _collections(nodes: dict[str, Node]) -> dict[str, list[Node]]:
    grouped: dict[str, list[Node]] = {}
    for node in nodes.values():
        grouped.setdefault(node["collection"], []).append(node)
    return {name: sorted(members, key=lambda n: n["name"]) for name, members in sorted(grouped.items())}


def _banner(outcome: dict[str, Any]) -> dict[str, str]:
    results = outcome.get("results", [])
    created = sum(1 for result in results if result["action"] == "created")
    existing = sum(1 for result in results if result["action"] in {"exists", "reference"} and result["ok"])
    done = f"{created} created, {existing} already present"

    failed = [result for result in results if not result["ok"]]
    if failed:
        detail = failed[0].get("detail") or "failed"
        return {"banner": f"{done} — stopped at {failed[0]['id']}: {detail}", "banner_tone": "bad"}
    return {"banner": f"{done}.", "banner_tone": "ok"}
