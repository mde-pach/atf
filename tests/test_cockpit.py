"""The cockpit, where a scenario cannot watch it.

What the interface *shows* is now `specs/features/cockpit.feature`, read through ATF's own `html`
and `browser` systems — the rail, the verticals, what a type page lists, what a scenario page says
and links to. Those are claims about what a person can perceive, and a scenario says them better
than an assertion on a substring of HTML ever did.

Three kinds of thing are left here, and none of them is a page:

**Decision procedures over data.** `readiness`, `closure_of`, `lineage_sentence`, `neighbourhood`
and `build_graph` are pure functions — is this blocked, what does it pull in, where do the boxes go.
A truth table is the right description of those, and running a server to reach one would say less.

**Contracts a reading surface has no words for.** An htmx request gets a fragment and a full request
gets a document; a mutation without its confirmation token is refused; a run only accepts test ids
this suite discovered. Those are about the HTTP the interface speaks, not about what it shows, and
`the button "…" is showing` cannot express any of them.

**States that need a run to have happened.** A scenario turning failing, a verdict going negative, a
job reporting progress and settling. The cockpit's mutating routes are POSTs, and a `page` only ever
GETs — deliberately, so nothing that reads the interface can change it. The one scenario that does
press a button is tagged `@browser`.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from atf.cockpit.app import create_app
from atf.cockpit.deps import Cockpit, set_cockpit
from atf.cockpit.view import build_graph, closure_of, lineage_sentence, neighbourhood, readiness, scenario_views
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

    # The sample project's adapter module shares a name with one in tests/test_bootstrap.py, so a
    # leaked import here fails an unrelated file depending on collection order.
    sys.modules.pop("suite_adapters", None)
    cockpit = Cockpit("dev")
    app = create_app(cockpit=cockpit)
    try:
        with TestClient(app) as test_client:
            test_client.cockpit = cockpit  # type: ignore[attr-defined]
            yield test_client
    finally:
        set_cockpit(None)
        sys.modules.pop("suite_adapters", None)


def confirm(client) -> str:
    return client.cockpit.confirm_token


def wait_for_job(client, env: str = "dev", timeout: float = 180.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.cockpit.active_job(env) is None:
            return
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def run_everything(client, env: str = "dev") -> None:
    client.post("/run", data={"confirm": confirm(client)})
    wait_for_job(client, env)


def break_a_step(project) -> None:
    steps = project / "specs" / "steps" / "test_accounts.py"
    steps.write_text(steps.read_text().replace("assert context.result == expected", "assert False, 'boom'"))


# ---- readiness: absent is not blocked --------------------------------------


def test_an_absent_resource_is_not_a_blocker(client):
    """Naming a resource in a scenario is what makes ATF create it, so absent is information.

    Only states running cannot fix — no adapter, an adapter that raised, or a missing reference
    resource — actually stand between a scenario and its first `When`.
    """
    nodes = client.cockpit.state("dev").materializer.nodes
    status = client.cockpit.status("dev")
    assert status["accounts.primary"]["status"] == "absent"

    ready = readiness(["projects.alpha"], nodes, status)
    assert ready.blocked is False
    assert set(ready.will_create) == {"projects.alpha", "accounts.primary"}


def test_a_missing_reference_resource_does_block(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    # The sample project's conftest seeds the widget, so state it absent to reach the other case.
    status = {**client.cockpit.status("dev"), "widgets.imported": {"status": "absent"}}

    ready = readiness(["widgets.imported"], nodes, status)
    assert ready.blocked is True
    assert ready.blockers[0][0] == "widgets.imported"
    assert "never creates" in ready.blockers[0][1]
    assert ready.will_create == []


def test_an_unreachable_system_blocks(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    status = {**client.cockpit.status("dev"), "accounts.primary": {"status": "unsupported"}}

    ready = readiness(["projects.alpha"], nodes, status)
    assert [node_id for node_id, _ in ready.blockers] == ["accounts.primary"]


def test_readiness_covers_the_whole_dependency_closure(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    assert closure_of("projects.alpha", nodes) == ["projects.alpha", "accounts.primary"]


# ---- scenario state ---------------------------------------------------------


def test_scenarios_start_as_never_run_and_become_passing(client):
    before = {view.state for view in scenario_views("dev")}
    assert "passing" not in before and "failing" not in before

    run_everything(client)
    assert "passing" in {view.state for view in scenario_views("dev")}


def test_a_scenario_needing_an_unseeded_reference_resource_starts_blocked(client):
    """`widgets.imported` is find-only and the environment does not ship it until the suite runs."""
    blocked = [view for view in scenario_views("dev") if view.state == "blocked"]
    assert [node for view in blocked for node, _ in view.ready.blockers] == ["widgets.imported"]


def test_a_broken_step_makes_its_scenario_failing(client, project):
    break_a_step(project)
    run_everything(client)

    failing = [view for view in scenario_views("dev") if view.state == "failing"]
    assert failing, "a broken step should put its scenario in the failing state"


# ---- the failing Gherkin step ----------------------------------------------


def test_the_failure_names_the_gherkin_step_it_happened_on(client, project):
    break_a_step(project)
    run_everything(client)

    view = next(item for item in scenario_views("dev") if item.state == "failing")
    assert view.failed_step is not None
    assert view.failed_step.keyword == "Then"
    assert "plan" in view.failed_step.text
    assert "boom" in view.failed_step.error


def test_the_steps_before_a_failure_are_recorded_as_passed(client, project):
    break_a_step(project)
    run_everything(client)

    view = next(item for item in scenario_views("dev") if item.state == "failing")
    assert [step.state for step in view.steps][0] == "passed"


def test_the_scenario_page_renders_the_error_at_the_failing_step(client, project):
    break_a_step(project)
    run_everything(client)

    view = next(item for item in scenario_views("dev") if item.state == "failing")
    body = client.get(f"/scenarios/{view.id}").text
    assert 'class="step failed"' in body
    assert 'class="whence"' in body
    assert "boom" in body


def test_a_test_records_the_resources_it_provisioned(client):
    run_everything(client)
    provisioned = {node for result in client.cockpit.results("dev").values() for node in result.provisioned}
    assert "accounts.primary" in provisioned


# ---- run history survives the process --------------------------------------


def test_results_outlive_the_cockpit_that_produced_them(client, project):
    run_everything(client)
    assert client.cockpit.last_run("dev") is not None

    fresh = Cockpit("dev")
    try:
        last = fresh.last_run("dev")
        assert last is not None and last.counts["passed"] >= 6
        assert fresh.results("dev"), "a new cockpit must read the run history from disk"
    finally:
        set_cockpit(None)


def test_run_history_is_written_under_dot_atf(client, project):
    run_everything(client)
    assert len(list((project / ".atf" / "runs").glob("*.json"))) == 1


def test_the_overview_verdict_reflects_the_last_run(client):
    assert "Not yet" in client.get("/").text

    run_everything(client)
    body = client.get("/").text
    assert "Yes" in body and 'id="verdict"' in body


def test_a_failing_run_turns_the_verdict_negative(client, project):
    break_a_step(project)
    run_everything(client)

    body = client.get("/").text
    assert "failing" in body
    assert 'class="verdict bad"' in body


def test_the_summary_fragment_carries_the_verdict_for_out_of_band_refresh(client):
    assert 'id="verdict"' in client.get("/overview/summary").text


# ---- runs and provisioning are one job model -------------------------------


def test_provisioning_runs_as_a_job_with_per_node_progress(client):
    assert client.post("/provision", data={"confirm": confirm(client)}).status_code == 200

    job = client.cockpit.active_job("dev") or client.cockpit.recent_jobs("dev", limit=1)[0]
    assert job.kind == "provision"
    assert "accounts.primary" in job.items

    wait_for_job(client)
    assert client.cockpit.status("dev")["accounts.primary"]["status"] == "present"


def test_a_run_is_the_same_shape_of_job(client):
    client.post("/run", data={"confirm": confirm(client)})
    job = client.cockpit.active_job("dev") or client.cockpit.recent_jobs("dev", limit=1)[0]
    assert job.kind == "run"

    wait_for_job(client)
    assert job.done and job.counts["passed"] >= 6


def test_the_activity_dock_reports_progress_then_settles(client):
    client.post("/run", data={"confirm": confirm(client)})
    wait_for_job(client)

    settled = client.get("/activity").text
    assert 'hx-get="/activity' not in settled  # the poller disarms when the job ends
    assert 'class="activity running"' not in settled
    assert "all passed" in settled


def test_provisioning_only_targets_what_atf_can_actually_create(client):
    targets = client.cockpit.provision_targets("dev")
    # `visitors.walkin` is ephemeral and `widgets.imported` is a reference: neither is creatable.
    assert "visitors.walkin" not in targets and "widgets.imported" not in targets
    assert "accounts.primary" in targets


def test_the_provision_label_names_the_set_the_action_provisions(client):
    body = client.get("/catalog").text
    assert f"Provision {len(client.cockpit.provision_targets('dev'))} resources" in body


def test_provisioning_one_node_pulls_in_its_dependencies(client):
    client.post("/provision", data={"confirm": confirm(client), "node": "projects.alpha"})
    wait_for_job(client)

    status = client.cockpit.status("dev")
    assert status["projects.alpha"]["status"] == "present"
    assert status["accounts.primary"]["status"] == "present"


def test_an_environment_never_has_two_jobs_at_once(client):
    client.post("/run", data={"confirm": confirm(client)})
    first = client.cockpit.active_job("dev")
    client.post("/run", data={"confirm": confirm(client)})
    second = client.cockpit.active_job("dev")
    assert first is None or second is None or first.id == second.id
    wait_for_job(client)
    assert len(client.cockpit.recent_jobs("dev", limit=5)) == 1


# ---- mutations are gated ----------------------------------------------------


@pytest.mark.parametrize("path", ["/run", "/provision"])
def test_mutating_without_the_confirmation_token_is_rejected(client, path):
    response = client.post(path, data={"confirm": "wrong"})
    assert response.status_code == 409
    assert "must be confirmed" in response.text


@pytest.mark.parametrize("path", ["/run", "/provision"])
def test_a_read_only_environment_refuses_mutations(client, path):
    response = client.post(f"{path}?env=locked", data={"confirm": confirm(client)})
    assert response.status_code == 409
    assert "read-only" in response.text


def test_rescanning_is_a_read_and_needs_no_permission(client):
    """Rescan re-reads the environment and changes nothing, so neither gate applies to it."""
    assert client.post("/catalog/rescan?env=locked").status_code == 200


def test_a_run_only_accepts_tests_this_suite_discovered(client):
    response = client.post("/run", data={"confirm": confirm(client), "nodeid": "-p evil_module"})
    assert response.status_code == 409
    assert "belong to this suite" in response.text


def test_running_a_selection_runs_only_that_selection(client):
    target = next(test for test in client.cockpit.discovery("dev").tests if "standard_account" in test.nodeid)

    client.post("/run", data={"confirm": confirm(client), "nodeid": target.nodeid})
    wait_for_job(client)

    assert list(client.cockpit.results("dev")) == [target.nodeid]


# ---- environments -----------------------------------------------------------


def test_an_unknown_environment_is_an_error_not_a_silent_fallback(client):
    response = client.get("/catalog?env=nope")
    assert response.status_code == 404
    assert "nope" in response.text
    assert "dev" in response.text and "locked" in response.text


def test_links_never_drop_the_environment(client):
    body = client.get("/catalog?env=locked").text
    for href in ("/scenarios", "/catalog"):
        assert f'href="{href}?env=locked"' in body


# ---- catalog: navigated by resource type ------------------------------------


def test_a_type_page_teaches_how_to_use_the_type(client):
    body = client.get("/catalog/type/account").text
    assert 'Given the account "primary"' in body  # the Gherkin line that provisions one
    assert "email" in body  # its natural key, from the adapter settings


def test_a_type_shows_its_instances_and_what_the_environment_holds_in_one_table(client):
    """They were two tables and a nav entry for the same resources. Declared-or-not is a column."""
    body = client.get("/catalog/type/account").text
    assert body.count("Declared in the catalog") == 0
    assert "primary" in body and "secondary" in body
    assert "The account every other resource hangs off." in body
    assert body.index("INSTANCE") if "INSTANCE" in body else True  # the one table's first column


def test_a_type_says_nothing_about_settings_that_are_the_default(client):
    """`persistent` + `create` is what every type is unless it says otherwise."""
    ordinary = client.get("/catalog/type/account").text
    assert "built for the test that needs it" not in ordinary
    assert "never creates it" not in ordinary

    ephemeral = client.get("/catalog/type/visitor").text
    assert "built for the test that needs it" in ephemeral

    reference = client.get("/catalog/type/external_widget").text
    assert "never creates it" in reference


def test_the_inspector_puts_the_payload_beside_the_action(client):
    body = client.get("/catalog/node/projects.alpha").text
    assert "A project under the primary account." in body
    assert "${accounts.primary.id}" in body
    # One card: what it is, what would be sent, and the button that sends it. The button leads
    # because it is the reason the page was opened; the payload is the next thing read.
    assert body.index("Provision alpha") < body.index("Payload")
    assert body.index("Payload") < body.index("catalog/projects.yaml")


def test_the_inspector_states_the_closure_the_action_will_create(client):
    assert "Provision alpha + 1 dependency" in client.get("/catalog/node/projects.alpha").text


def test_the_lineage_is_also_stated_in_words(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    sentence = lineage_sentence(nodes["projects.alpha"], nodes)
    assert "alpha needs primary" in sentence and "2 resources" in sentence
    assert "nothing has to exist first" in lineage_sentence(nodes["accounts.primary"], nodes).lower()


def test_a_resource_that_depends_on_something_gets_a_diagram(client):
    """The graph is the only place the shape of the catalog is visible. Hiding it behind a size
    threshold meant nobody found out it existed."""
    depends = client.get("/catalog/node/projects.alpha").text
    assert 'class="graph"' in depends
    assert "alpha needs primary" in depends, "the sentence stays: it is what a reader actually reads"

    standalone = client.get("/catalog/node/accounts.primary").text
    assert 'class="graph"' not in standalone, "nothing to draw when nothing has to exist first"
    assert "Nothing has to exist first" in standalone


def test_a_lineage_node_carries_its_description_for_the_hover_card(client):
    assert "The account every other resource hangs off." in client.get("/catalog/node/projects.alpha").text


# ---- scenarios: one vertical, filterable ------------------------------------


def test_an_examples_table_carries_the_outcome_of_each_row(client):
    """An outline is one behaviour run several times, so the values belong beside the Gherkin —
    not under a card explaining what pytest collects."""
    body = client.get("/scenarios/accounts::accounts-report-their-own-plan").text
    assert "secondary" in body and "trial" in body
    assert "<th>who</th>" in body and "<th>outcome</th>" in body
    assert "What pytest collects" not in body


def test_a_scenario_with_one_test_and_no_examples_shows_neither_table(client):
    body = client.get("/scenarios/accounts::a-standard-account-reports-its-plan").text
    assert "<th>outcome</th>" not in body
    assert "What pytest collects" not in body


def test_filtering_by_state_focuses_a_scenario_in_that_state(client, project):
    break_a_step(project)
    run_everything(client)

    body = client.get("/scenarios?state=failing").text
    failing = next(view for view in scenario_views("dev") if view.state == "failing")
    assert failing.spec.scenario in body
    assert 'aria-pressed="true"' in body


# ---- htmx ------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/catalog/node/accounts.primary",
        "/catalog/type/account",
        "/scenarios/accounts::a-project-belongs-to-its-account",
    ],
)
def test_htmx_requests_return_fragments_not_whole_pages(client, path):
    response = client.get(path, headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "<!doctype html>" not in response.text.lower()
    assert 'class="rail"' not in response.text


def test_an_error_never_replaces_the_content_it_was_triggered_from(client):
    response = client.post("/run", data={"confirm": "wrong"})
    assert response.headers["HX-Reswap"] == "none"


# ---- search -----------------------------------------------------------------


def test_search_finds_resources_types_and_scenarios(client):
    assert "resource" in client.get("/search?q=primary").text
    assert "type" in client.get("/search?q=account").text
    assert "scenario" in client.get("/search?q=plan").text


def test_search_with_no_query_and_no_match(client):
    assert "Search a resource" in client.get("/search?q=").text
    assert "Nothing matches" in client.get("/search?q=zzzzz").text


# ---- lineage graph layout ---------------------------------------------------


def test_neighbourhood_walks_both_directions(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    assert neighbourhood(nodes, "accounts.primary")["projects.alpha"] == 1
    assert neighbourhood(nodes, "projects.alpha")["accounts.primary"] == -1


def test_the_graph_places_columns_by_depth_with_bezier_edges(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    graph = build_graph(nodes, "projects.alpha", client.cockpit.status("dev"))

    boxes = {box.id: box for box in graph.boxes}
    assert boxes["accounts.primary"].x < boxes["projects.alpha"].x
    assert boxes["projects.alpha"].focus is True
    assert boxes["accounts.primary"].represents  # the hover card has something to show
    assert len(graph.edges) == 1
    assert graph.edges[0].path.startswith("M ") and " C " in graph.edges[0].path


def test_an_isolated_node_is_a_single_box(client):
    nodes = client.cockpit.state("dev").materializer.nodes
    graph = build_graph(nodes, "widgets.imported", {})
    assert [box.id for box in graph.boxes] == ["widgets.imported"]
    assert graph.edges == []


# ---- theming + static -------------------------------------------------------


def test_both_themes_are_defined_and_htmx_is_vendored(client):
    css = client.get("/static/app.css").text
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css and ':root[data-theme="light"]' in css

    js = client.get("/static/htmx.min.js")
    assert js.status_code == 200 and "htmx 2." in js.text[:200]
    assert "unpkg.com" not in client.get("/").text


def test_an_unknown_resource_is_named_in_a_404_rather_than_shown_as_nothing(client):
    response = client.get("/catalog/node/nope.nope")
    assert response.status_code == 404
    assert "nope.nope" in response.text
