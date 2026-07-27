"""⌘K search across resources, resource types and scenarios."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request

from ..view import cockpit as app
from ..view import current_env, partial

router = APIRouter(prefix="/search")

LIMIT = 12


@dataclass
class Hit:
    kind: str
    label: str
    sub: str
    url: str
    score: int


@router.get("")
def search(request: Request):
    env = current_env(request)
    query = (request.query_params.get("q") or "").strip().lower()
    return partial(request, "partials/search_results.html", env=env, query=query, hits=_hits(env, query))


def _hits(env: str, query: str) -> list[Hit]:
    if not query:
        return []

    cockpit = app()
    engine = cockpit.state(env).materializer
    status = cockpit.status(env)
    hits: list[Hit] = []

    for name in engine.types:
        score = _score(query, name)
        if score:
            count = sum(1 for node in engine.nodes.values() if node["resource"] == name)
            hits.append(Hit("type", name, f"{count} in the catalog", f"/catalog/type/{name}?env={env}", score))

    for node_id, node in engine.nodes.items():
        score = _score(query, node["name"], node_id, node["resource"], node["represents"])
        if score:
            state = status.get(node_id, {}).get("status", "")
            hits.append(
                Hit("resource", node_id, state or node["resource"], f"/catalog/node/{node_id}?env={env}", score)
            )

    for spec in cockpit.discovery(env).specs:
        score = _score(query, spec.scenario, spec.feature, " ".join(spec.tags))
        if score:
            hits.append(Hit("scenario", spec.scenario, spec.feature, f"/scenarios/{spec.id}?env={env}", score))

    return sorted(hits, key=lambda hit: (-hit.score, hit.label))[:LIMIT]


def _score(query: str, *fields: str) -> int:
    """Exact > prefix > substring, weighted by field order."""
    best = 0
    for index, field in enumerate(fields):
        text = (field or "").lower()
        if not text or query not in text:
            continue
        if text == query:
            hit = 100
        elif text.startswith(query):
            hit = 60
        else:
            hit = 30
        best = max(best, hit - index * 5)
    return best
