"""Shared view layer: template environment, page context, graph layout, security gating."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates

from ..catalog import Node
from ..discovery import Discovery
from ..materializer import ABSENT, EPHEMERAL, ERROR, PRESENT
from ..runner import FAILED, PASSED, SKIPPED
from .deps import Cockpit, get_cockpit

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Graph layout (§13.7)
NODE_W = 162
NODE_H = 44
COL_GAP = 232
ROW_GAP = 60
PAD = 60

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def cockpit() -> Cockpit:
    return get_cockpit()


def current_env(request: Request) -> str:
    app = cockpit()
    requested = request.query_params.get("env") or request.headers.get("HX-Env")
    if requested and requested in app.manifest.environments:
        return requested
    return app.default_env


def require_mutable(env: str) -> None:
    """Every mutating route calls this first (§13.5)."""
    if not cockpit().is_mutable(env):
        raise HTTPException(
            status_code=409,
            detail=f"environment {env!r} is read-only; add it to `mutable_envs` in the manifest to allow changes",
        )


def require_confirmation(token: str | None) -> None:
    if not token or not secrets.compare_digest(token, cockpit().confirm_token):
        raise HTTPException(status_code=409, detail="this action must be confirmed")


def page(request: Request, template: str, **context: Any) -> Any:
    app = cockpit()
    env = context.pop("env", None) or current_env(request)
    base = {
        "request": request,
        "env": env,
        "environments": app.environments,
        "mutable": app.is_mutable(env),
        "confirm_token": app.confirm_token,
        "counts": nav_counts(env),
        "manifest": app.manifest,
        "display": app.manifest.display,
        "partial": request.headers.get("HX-Request") == "true",
    }
    return templates.TemplateResponse(request, template, {**base, **context})


def partial(request: Request, template: str, **context: Any) -> Any:
    app = cockpit()
    env = context.pop("env", None) or current_env(request)
    base = {
        "request": request,
        "env": env,
        "mutable": app.is_mutable(env),
        "confirm_token": app.confirm_token,
        "display": app.manifest.display,
    }
    return templates.TemplateResponse(request, template, {**base, **context})


def nav_counts(env: str) -> dict[str, int]:
    app = cockpit()
    found = app.discovery(env)
    return {
        "catalog": len(app.state(env).materializer.nodes),
        "specs": len(found.specs),
        "tests": len(found.tests),
        "fixtures": len(found.fixtures),
    }


# ---- meters (§13.2) --------------------------------------------------------


@dataclass
class Meter:
    label: str
    value: int
    total: int
    tone: str
    detail: str = ""

    @property
    def percent(self) -> int:
        return 0 if not self.total else round(100 * self.value / self.total)


def config_meter(status: dict[str, dict[str, Any]]) -> Meter:
    counted = {nid: entry for nid, entry in status.items() if entry["status"] != EPHEMERAL}
    present = sum(1 for entry in counted.values() if entry["status"] == PRESENT)
    total = len(counted)
    absent = sum(1 for entry in counted.values() if entry["status"] == ABSENT)
    errored = sum(1 for entry in counted.values() if entry["status"] == ERROR)
    tone = "ok" if total and present == total else ("bad" if errored else "warn")
    detail = "everything present" if present == total else f"{absent} absent"
    if errored:
        detail += f", {errored} errored"
    return Meter("Config", present, total, tone, detail)


def coverage_meter(found: Discovery, nodes: dict[str, Node]) -> Meter:
    covered = sum(1 for spec in found.specs if spec.test_ids)
    exercised = {node_id for spec in found.specs for node_id in spec.resources}
    tone = "ok" if found.specs and covered == len(found.specs) else "warn"
    return Meter(
        "Coverage",
        covered,
        len(found.specs),
        tone,
        f"{len(exercised)}/{len(nodes)} resources exercised",
    )


def health_meter(found: Discovery, results: dict[str, Any]) -> Meter:
    passed = failed = skipped = 0
    for test in found.tests:
        result = results.get(test.nodeid)
        if result is None:
            continue
        if result.outcome == PASSED:
            passed += 1
        elif result.outcome == SKIPPED:
            skipped += 1
        else:
            failed += 1
    ran = passed + failed + skipped
    tone = "bad" if failed else ("ok" if ran and ran == len(found.tests) else "warn")
    detail = "never run" if not ran else f"{failed} failing, {skipped} skipped, {len(found.tests) - ran} not run"
    return Meter("Health", passed, len(found.tests), tone, detail)


def coverage_gaps(found: Discovery, nodes: dict[str, Node]) -> dict[str, list[str]]:
    exercised = {node_id for spec in found.specs for node_id in spec.resources}
    return {
        "specs_without_tests": [spec.id for spec in found.specs if not spec.test_ids],
        "resources_without_specs": sorted(set(nodes) - exercised),
        "skipped_specs": [spec.id for spec in found.specs if spec.skipped],
    }


# ---- graph (§13.7) ---------------------------------------------------------


@dataclass
class GraphBox:
    id: str
    label: str
    sub: str
    x: int
    y: int
    focus: bool
    status: str
    system: str


@dataclass
class GraphEdge:
    path: str
    frm: str
    to: str


@dataclass
class Graph:
    boxes: list[GraphBox]
    edges: list[GraphEdge]
    width: int
    height: int
    focus: str


def neighbourhood(nodes: dict[str, Node], focus: str) -> dict[str, int]:
    """Every node in the focus node's lineage, mapped to its column (0 = focus)."""
    layers: dict[str, int] = {focus: 0}

    def walk(current: str, depth: int, upstream: bool) -> None:
        node = nodes[current]
        neighbours = node["depends_on"] if upstream else node["dependents"]
        for neighbour in neighbours:
            if neighbour not in nodes:
                continue
            column = depth + (-1 if upstream else 1)
            if neighbour not in layers or abs(column) < abs(layers[neighbour]):
                layers[neighbour] = column
                walk(neighbour, column, upstream)

    walk(focus, 0, upstream=True)
    walk(focus, 0, upstream=False)
    return layers


def build_graph(nodes: dict[str, Node], focus: str, status: dict[str, dict[str, Any]]) -> Graph:
    layers = neighbourhood(nodes, focus)
    columns: dict[int, list[str]] = {}
    for node_id, column in sorted(layers.items()):
        columns.setdefault(column, []).append(node_id)

    order = sorted(columns)
    tallest = max((len(members) for members in columns.values()), default=1)
    height = PAD * 2 + tallest * NODE_H + (tallest - 1) * ROW_GAP
    width = PAD * 2 + len(order) * NODE_W + max(len(order) - 1, 0) * (COL_GAP - NODE_W)

    positions: dict[str, tuple[int, int]] = {}
    boxes: list[GraphBox] = []
    for index, column in enumerate(order):
        members = columns[column]
        span = len(members) * NODE_H + (len(members) - 1) * ROW_GAP
        top = (height - span) // 2
        for row, node_id in enumerate(members):
            x = PAD + index * COL_GAP
            y = top + row * (NODE_H + ROW_GAP)
            positions[node_id] = (x, y)
            node = nodes[node_id]
            boxes.append(
                GraphBox(
                    id=node_id,
                    label=node["name"],
                    sub=node["resource"],
                    x=x,
                    y=y,
                    focus=node_id == focus,
                    status=status.get(node_id, {}).get("status", ""),
                    system=node["system"],
                )
            )

    edges: list[GraphEdge] = []
    for node_id in layers:
        for dependency in nodes[node_id]["depends_on"]:
            if dependency not in positions or node_id not in positions:
                continue
            start = positions[dependency]
            end = positions[node_id]
            x1, y1 = start[0] + NODE_W, start[1] + NODE_H // 2
            x2, y2 = end[0], end[1] + NODE_H // 2
            mid = (x1 + x2) // 2
            edges.append(
                GraphEdge(path=f"M {x1} {y1} C {mid} {y1}, {mid} {y2}, {x2} {y2}", frm=dependency, to=node_id)
            )

    return Graph(boxes=boxes, edges=edges, width=width, height=height, focus=focus)


# ---- status helpers --------------------------------------------------------

TONES = {
    PRESENT: "ok",
    PASSED: "ok",
    ABSENT: "idle",
    "pending": "idle",
    "not run": "idle",
    EPHEMERAL: "accent",
    "running": "running",
    FAILED: "bad",
    ERROR: "bad",
    "unsupported": "warn",
    SKIPPED: "warn",
}


def tone(status: str) -> str:
    return TONES.get(status, "idle")


def outcome_of(nodeid: str, results: dict[str, Any]) -> str:
    result = results.get(nodeid)
    return result.outcome if result else "not run"


_GLOBALS: dict[str, Any] = {"tone": tone, "NODE_W": NODE_W, "NODE_H": NODE_H}
templates.env.globals.update(_GLOBALS)
