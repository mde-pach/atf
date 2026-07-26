from __future__ import annotations

import os
import re
import time

import pytest
from fastapi.testclient import TestClient

from atf.cockpit.app import create_app
from atf.cockpit.deps import Cockpit, set_cockpit
from atf.cockpit.view import build_graph, neighbourhood
from tests.sample_project import write_sample_project

REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    monkeypatch.setenv("ATF_ENV", "dev")
    monkeypatch.setenv("PYTHONPATH", REPO_SRC)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def client(project):
    import sys

    sys.modules.pop("suite_adapters", None)
    cockpit = Cockpit("dev")
    app = create_app(cockpit=cockpit)
    with TestClient(app) as test_client:
        test_client.cockpit = cockpit  # type: ignore[attr-defined]
        yield test_client
    set_cockpit(None)


def confirm(client) -> str:
    return client.cockpit.confirm_token


def wait_for_run(client, env: str = "dev", timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.cockpit.active_job(env)
        if job is None:
            return
        time.sleep(0.05)
    raise AssertionError("run did not finish")


# ---- pages render ---------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/catalog", "/specs", "/tests", "/fixtures"])
def test_every_vertical_renders(client, path):
    response = client.get(path)
    assert response.status_code == 200
    body = response.text
    assert "<!doctype html>" in body.lower()
    assert 'class="rail"' in body
    assert "atf-progress" in body


def test_overview_shows_the_three_meters(client):
    body = client.get("/").text
    assert "Config" in body and "Coverage" in body and "Health" in body
    assert "Can I ship?" in body
    # 5 persistent nodes (the ephemeral one is not counted), none present yet
    assert re.search(r'class="value">0<small> / 5', body)


def test_rail_counts_reflect_discovery(client):
    body = client.get("/").text
    assert re.search(r"Catalog\s*<span class=\"count\">6<", body)
    assert re.search(r"Specs\s*<span class=\"count\">7<", body)
    assert re.search(r"Tests\s*<span class=\"count\">8<", body)


def test_catalog_lists_collections_and_renders_a_graph(client):
    body = client.get("/catalog").text
    for collection in ("accounts", "projects", "visitors", "widgets"):
        assert f'class="list-group-label">{collection}<' in body
    assert 'class="graph"' in body
    assert "<path d=" in body


def test_catalog_inspector_shows_lineage_and_payload(client):
    body = client.get("/catalog/node/projects.alpha").text
    assert "A project under the primary account." in body
    assert "accounts.primary" in body  # Needs
    assert "${accounts.primary.id}" in body  # payload
    needed_by = body.split("Needed by")[1][:400]
    assert "accounts.primary" not in needed_by  # it is a dependency, not a dependent


def test_catalog_shows_ephemeral_as_built_per_run(client):
    body = client.get("/catalog/node/visitors.walkin").text
    assert "built per run" in body


def test_specs_link_resource_names_to_their_node(client):
    body = client.get("/specs").text
    assert "A standard account reports its plan" in body

    detail = client.get("/specs/accounts::a-project-belongs-to-its-account").text
    assert 'href="/catalog/node/accounts.primary?env=dev"' in detail
    assert 'href="/catalog/node/projects.alpha?env=dev"' in detail
    assert "Given" in detail and "When" in detail and "Then" in detail


def test_specs_show_examples_and_covering_tests(client):
    body = client.get("/specs/accounts::accounts-report-their-own-plan").text
    assert "Examples" in body
    assert "secondary" in body
    assert "Run these tests" in body


def test_tests_are_grouped_by_spec_with_selection(client):
    body = client.get("/tests").text
    assert "Run selected" in body and "Run all" in body
    assert 'type="checkbox" name="nodeid"' in body
    assert "A standard account reports its plan" in body


def test_test_detail_shows_covers_resources_fixtures(client):
    found = client.cockpit.discovery("dev")
    test = next(item for item in found.tests if "standard_account" in item.nodeid)
    body = client.get(f"/tests/detail/{test.id}").text
    assert "Covers spec" in body and "Uses resources" in body and "Uses fixtures" in body
    assert "accounts.primary" in body
    assert 'href="/fixtures/account?env=dev"' in body


def test_fixtures_separate_generated_factories(client):
    body = client.get("/fixtures").text
    assert "Generated from the catalog" in body
    detail = client.get("/fixtures/account").text
    assert "generated from the catalog" in detail
    assert "Provision a `account` by catalog name" in detail


# ---- htmx partials --------------------------------------------------------


def test_htmx_requests_return_fragments_not_whole_pages(client):
    response = client.get("/catalog/node/accounts.primary", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "<!doctype html>" not in response.text.lower()
    assert 'class="rail"' not in response.text


def test_search_finds_each_entity_kind(client):
    for query, expected in [
        ("primary", "resource"),
        ("plan", "spec"),
        ("account", "fixture"),
    ]:
        body = client.get(f"/search?q={query}").text
        assert expected in body, (query, body[:400])


def test_search_with_no_query_and_no_match(client):
    assert "Type to search" in client.get("/search?q=").text
    assert "Nothing matches" in client.get("/search?q=zzzzz").text


# ---- mutations + security gating (§13.5) ----------------------------------


def test_seeding_creates_absent_resources(client):
    response = client.post("/catalog/seed", data={"confirm": confirm(client)})
    assert response.status_code == 200
    assert "5 created" in response.text  # 2 accounts, a project, a badge and its ephemeral visitor

    status = client.cockpit.status("dev")
    assert status["accounts.primary"]["status"] == "present"
    assert status["projects.alpha"]["status"] == "present"


def test_seeding_reports_a_reference_resource_that_is_missing(client):
    body = client.post("/catalog/seed", data={"confirm": confirm(client)}).text
    # `external_widget` is find-only: seeding cannot conjure it, and says so without hiding what worked.
    assert "stopped at widgets.imported" in body
    assert "5 created" in body
    assert 'class="banner bad' in body


def test_creating_one_node_provisions_its_closure(client):
    response = client.post("/catalog/create/projects.alpha", data={"confirm": confirm(client)})
    assert response.status_code == 200
    status = client.cockpit.status("dev")
    assert status["accounts.primary"]["status"] == "present"


def test_mutating_without_a_confirmation_token_is_rejected(client):
    response = client.post("/catalog/seed", data={"confirm": "wrong"})
    assert response.status_code == 409
    assert "must be confirmed" in response.text


def test_a_non_mutable_env_is_read_only(client):
    body = client.get("/?env=locked").text
    assert "read-only — not in mutable_envs" in body
    assert "disabled" in body

    for path in ("/catalog/seed?env=locked", "/catalog/create/accounts.primary?env=locked", "/tests/run?env=locked"):
        response = client.post(path, data={"confirm": confirm(client)})
        assert response.status_code == 409, path
        assert "read-only" in response.text


def test_sync_reloads_the_catalog(client):
    response = client.post("/catalog/sync?focus=accounts.primary")
    assert response.status_code == 200
    assert "Synced" in response.text


# ---- runs with live progress ----------------------------------------------


def test_running_tests_streams_progress_then_settles(client):
    response = client.post("/tests/run", data={"confirm": confirm(client)})
    assert response.status_code == 200
    assert 'hx-get="/tests/progress' in response.text  # poller armed
    assert "pending" in response.text or "running" in response.text

    wait_for_run(client)

    final = client.get("/tests/progress").text
    assert 'hx-get="/tests/progress' not in final  # poller disarmed
    assert "passed" in final
    assert "hx-get=\"/overview/meters" in final  # out-of-band meter re-sync


def test_run_results_reach_the_tests_table_and_meters(client):
    client.post("/tests/run", data={"confirm": confirm(client)})
    wait_for_run(client)

    body = client.get("/tests").text
    assert body.count('class="pill ok">passed') >= 6

    meters = client.get("/overview/meters").text
    assert re.search(r'class="value">7<small> / 8', meters)


def test_running_a_selection_runs_only_those(client):
    found = client.cockpit.discovery("dev")
    target = next(test for test in found.tests if "standard_account" in test.nodeid)

    client.post("/tests/run", data={"confirm": confirm(client), "nodeid": target.nodeid})
    wait_for_run(client)

    results = client.cockpit.results("dev")
    assert list(results) == [target.nodeid]
    assert results[target.nodeid].outcome == "passed"


def test_a_failing_test_shows_red_with_detail(client, project):
    steps = project / "specs" / "steps" / "test_accounts.py"
    steps.write_text(steps.read_text().replace("assert context.result == expected", "assert False, 'boom'"))

    client.post("/tests/run", data={"confirm": confirm(client)})
    wait_for_run(client)

    body = client.get("/tests/progress").text
    assert 'class="pill bad">failed' in body
    assert "AssertionError" in body  # the progress table shows pytest's summary line

    found = client.cockpit.discovery("dev")
    failing = next(
        test for test in found.tests if client.cockpit.result_for(test.nodeid, "dev").outcome == "failed"
    )
    detail = client.get(f"/tests/detail/{failing.id}").text
    assert "boom" in detail  # the inspector shows the whole traceback

    assert "failing" in client.get("/").text


# ---- graph layout (§13.7) -------------------------------------------------


def test_neighbourhood_walks_both_directions(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    layers = neighbourhood(nodes, "accounts.primary")
    assert layers["accounts.primary"] == 0
    assert layers["projects.alpha"] == 1

    layers = neighbourhood(nodes, "projects.alpha")
    assert layers["accounts.primary"] == -1


def test_graph_places_columns_by_depth_with_bezier_edges(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    graph = build_graph(nodes, "projects.alpha", client.cockpit.status("dev"))

    boxes = {box.id: box for box in graph.boxes}
    assert boxes["accounts.primary"].x < boxes["projects.alpha"].x
    assert boxes["projects.alpha"].focus is True
    assert len(graph.edges) == 1
    assert graph.edges[0].path.startswith("M ") and " C " in graph.edges[0].path
    assert graph.width > 0 and graph.height > 0


def test_isolated_node_graph_is_a_single_box(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    graph = build_graph(nodes, "widgets.imported", {})
    assert [box.id for box in graph.boxes] == ["widgets.imported"]
    assert graph.edges == []


# ---- theming + static -----------------------------------------------------


def test_both_themes_are_defined_and_htmx_is_vendored(client):
    css = client.get("/static/app.css").text
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css
    assert ':root[data-theme="light"]' in css

    js = client.get("/static/htmx.min.js")
    assert js.status_code == 200
    assert "htmx 2." in js.text[:200]
    assert "unpkg.com" not in client.get("/").text  # no CDN reference in the page


def test_unknown_page_renders_the_error_banner(client):
    response = client.get("/catalog/node/nope.nope")
    assert response.status_code == 200
    assert "Nothing selected" in response.text
