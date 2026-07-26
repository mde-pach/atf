"""⌘K search across resources, specs, tests and fixtures."""

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
    found = cockpit.discovery(env)
    hits: list[Hit] = []

    for node_id, node in cockpit.state(env).materializer.nodes.items():
        score = _score(query, node_id, node["resource"], node["represents"])
        if score:
            hits.append(Hit("resource", node_id, node["resource"], f"/catalog/node/{node_id}?env={env}", score))

    for spec in found.specs:
        score = _score(query, spec.scenario, spec.feature, " ".join(spec.tags))
        if score:
            hits.append(Hit("spec", spec.scenario, spec.feature, f"/specs/{spec.id}?env={env}", score))

    for test in found.tests:
        score = _score(query, test.name, test.nodeid)
        if score:
            hits.append(Hit("test", test.name, test.covers, f"/tests/detail/{test.id}?env={env}", score))

    for fixture in found.fixtures:
        score = _score(query, fixture.name, fixture.doc)
        if score:
            hits.append(Hit("fixture", fixture.name, fixture.doc[:60], f"/fixtures/{fixture.name}?env={env}", score))

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
