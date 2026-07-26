from __future__ import annotations

import pytest

from atf.adapters import build, register, registered_systems, unregister
from atf.materializer import Materializer, ProvisioningError, UnknownResource


def test_registry_builds_by_factory():
    calls: list[dict] = []

    class Dummy:
        def find(self, node, ctx):
            return None

        def create(self, node, body, ctx):
            return {}

        def delete(self, node, record, ctx):
            return None

    def factory(settings):
        calls.append(settings)
        return Dummy()

    register("dummy", factory)
    assert "dummy" in registered_systems()
    build("dummy", {"base_url": "x"})
    assert calls == [{"base_url": "x"}]
    unregister("dummy")
    assert "dummy" not in registered_systems()


def test_registry_error_names_the_system():
    with pytest.raises(KeyError) as err:
        build("nope", {})
    assert "nope" in str(err.value)


def test_closure_and_topo(materializer):
    assert set(materializer.closure("runs.nightly")) == {"runs.nightly", "projects.alpha", "accounts.primary"}
    order = materializer.topo(materializer.closure("runs.nightly"))
    assert order == ["accounts.primary", "projects.alpha", "runs.nightly"]


def test_ensure_provisions_a_dependency_chain_and_resolves_placeholders(materializer, fake):
    record = materializer.ensure("job_run", "nightly")

    # non-default id_field honoured
    assert record["uuid"] == "job_run-3"
    assert fake.actions("create") == ["accounts.primary", "projects.alpha", "runs.nightly"]

    project = fake.store["project"][0]
    assert project["account_id"] == "account-1"
    assert record["project_id"] == "project-2"


def test_ensure_is_idempotent(materializer, fake):
    first = materializer.ensure("project", "alpha")
    second = materializer.ensure("project", "alpha")
    assert first["id"] == second["id"]
    assert fake.actions("create") == ["accounts.primary", "projects.alpha"]


def test_materialize_reports_exists_on_second_pass(materializer):
    materializer.create_closure("projects.alpha")
    outcome = materializer.create_closure("projects.alpha")
    assert [(r["id"], r["action"]) for r in outcome["results"]] == [
        ("accounts.primary", "exists"),
        ("projects.alpha", "exists"),
    ]


def test_ensure_raises_on_provisioning_failure(materializer, fake):
    fake.fail_create.add("projects.alpha")
    with pytest.raises(ProvisioningError) as err:
        materializer.ensure("project", "alpha")
    assert err.value.node_id == "projects.alpha"
    assert "refused" in err.value.detail


def test_materialize_stops_at_the_first_error(materializer, fake):
    fake.fail_create.add("accounts.primary")
    outcome = materializer.materialize(["accounts.primary", "projects.alpha"])
    assert len(outcome["results"]) == 1
    assert outcome["results"][0]["ok"] is False
    assert outcome["records"] == {}


def test_reference_mode_errors_when_absent(materializer):
    outcome = materializer.create_closure("widgets.imported")
    assert outcome["results"][0]["ok"] is False
    assert outcome["results"][0]["action"] == "reference"


def test_reference_mode_finds_a_seeded_record(materializer, fake):
    fake.seed("widget", {"name": "imported", "id": "w-1"})
    record = materializer.ensure("widget", "imported")
    assert record["id"] == "w-1"
    assert fake.actions("create") == []


def test_ephemeral_is_built_every_pass_and_returned(materializer, fake):
    first = materializer.ensure("lead", "walkin")
    second = materializer.ensure("lead", "walkin")
    assert first["id"] == "lead-1"
    assert second["id"] == "lead-2"
    assert fake.actions("create") == ["leads.walkin", "leads.walkin"]


def test_teardown_deletes_only_ephemeral_records(materializer, fake):
    outcome = materializer.materialize(["accounts.primary", "leads.walkin"])
    materializer.teardown(outcome["records"])
    assert fake.actions("delete") == ["leads.walkin"]


def test_teardown_never_raises(materializer, fake):
    outcome = materializer.materialize(["leads.walkin"])

    def explode(node, record, ctx):
        raise RuntimeError("backend down")

    fake.delete = explode  # type: ignore[method-assign]
    materializer.teardown(outcome["records"])


def test_status_classifies_every_node(materializer, fake):
    fake.seed("account", {"email": "primary@example.test", "id": "seeded"})
    status = materializer.status()
    assert status["accounts.primary"]["status"] == "present"
    assert status["accounts.primary"]["identity"] == "seeded"
    assert status["projects.alpha"]["status"] == "absent"
    assert status["leads.walkin"]["status"] == "ephemeral"
    assert status["widgets.imported"]["status"] == "absent"


def test_status_can_scope_to_a_collection(materializer):
    assert set(materializer.status("projects")) == {"projects.alpha"}


def test_status_reports_unsupported_when_no_adapter_is_built(good_catalog, fake):
    engine = Materializer(good_catalog, "test", {})
    assert engine.status()["accounts.primary"]["status"] == "unsupported"
    outcome = engine.create_closure("accounts.primary")
    assert outcome["results"][0]["action"] == "unsupported"


def test_status_reports_adapter_errors(materializer, fake):
    def explode(node, ctx):
        raise RuntimeError("backend down")

    fake.find = explode  # type: ignore[method-assign]
    entry = materializer.status("accounts")["accounts.primary"]
    assert entry["status"] == "error"
    assert "backend down" in entry["detail"]


def test_unknown_resource(materializer):
    with pytest.raises(UnknownResource):
        materializer.resolve_id("account", "nope")
    with pytest.raises(UnknownResource):
        materializer.node("nope.nope")


def test_listing_cache_is_reused_then_invalidated_on_create(materializer, fake):
    calls: list[str] = []
    materializer.cached("k", lambda: calls.append("load") or "v")
    materializer.cached("k", lambda: calls.append("load") or "v")
    assert calls == ["load"]
    materializer.ensure("account", "primary")
    materializer.cached("k", lambda: calls.append("load") or "v")
    assert calls == ["load", "load"]


def test_create_all_covers_every_creatable_node(materializer, fake):
    fake.seed("widget", {"name": "imported", "id": "w-1"})
    outcome = materializer.create_all()
    assert all(result["ok"] for result in outcome["results"])
    assert set(outcome["records"]) == set(materializer.nodes)


def test_ephemeral_reached_through_a_dependency_is_tracked_for_teardown(write_catalog, fake):
    """Nothing else would ever delete it: ephemeral nodes skip `find`, so each pass creates one."""
    root = write_catalog(
        {
            "resources.yaml": (
                "lead:\n  system: fake\n  lifecycle: ephemeral\n  natural_key: email\n"
                "listing:\n  system: fake\n  natural_key: slug\n"
            ),
            "leads.yaml": "walkin:\n  resource: lead\n  body: {email: w@e.test}\n",
            "listings.yaml": (
                "alpha:\n  resource: listing\n  depends_on: [leads.walkin]\n"
                "  body: {slug: alpha, lead_id: '${leads.walkin.id}'}\n"
            ),
        }
    )
    engine = Materializer(root, "test", {"fake": fake})

    record, provisioned = engine.ensure_closure("listing", "alpha")
    assert record["slug"] == "alpha"
    assert set(provisioned) == {"leads.walkin", "listings.alpha"}

    ephemeral = engine.ephemeral_records(provisioned)
    assert [nid for nid, _ in ephemeral] == ["leads.walkin"]

    engine.teardown(ephemeral)
    assert fake.actions("delete") == ["leads.walkin"]


def test_teardown_accepts_repeated_instances_of_one_ephemeral_node(materializer, fake):
    """Two provisions of the same ephemeral node are two records; both must be deleted."""
    first = materializer.ensure("lead", "walkin")
    second = materializer.ensure("lead", "walkin")
    assert first["id"] != second["id"]

    materializer.teardown([("leads.walkin", first), ("leads.walkin", second)])
    assert fake.actions("delete") == ["leads.walkin", "leads.walkin"]
    assert fake.store["lead"] == []


def test_the_listing_cache_does_not_survive_a_pass(materializer, fake):
    """The materializer is session-scoped; the backend changes underneath it between passes."""
    fake.seed("account", {"email": "primary@example.test", "id": "PRE"})
    assert materializer.status("accounts")["accounts.primary"]["identity"] == "PRE"

    loads: list[str] = []
    materializer.cached("listing", lambda: loads.append("load") or [])
    materializer.materialize(["accounts.primary"])
    materializer.cached("listing", lambda: loads.append("load") or [])
    assert loads == ["load", "load"], "materialize must start each pass with a cold cache"


def test_a_record_deleted_between_passes_is_seen_as_absent(materializer, fake):
    materializer.materialize(["accounts.primary"])
    fake.store["account"] = []

    outcome = materializer.materialize(["accounts.primary"])
    assert [r["action"] for r in outcome["results"]] == ["created"]


# ---- keep_going -----------------------------------------------------------


@pytest.fixture
def two_chains(write_catalog, fake):
    """Two independent chains, so a failure in one cannot explain a failure in the other."""
    root = write_catalog(
        {
            "resources.yaml": (
                "account:\n  system: fake\n  natural_key: email\n"
                "project:\n  system: fake\n  natural_key: slug\n"
            ),
            "accounts.yaml": (
                "alpha:\n  resource: account\n  body: {email: alpha@e.test}\n"
                "beta:\n  resource: account\n  body: {email: beta@e.test}\n"
            ),
            "projects.yaml": (
                "one:\n  resource: project\n  depends_on: [accounts.alpha]\n"
                "  body: {slug: one, owner: '${accounts.alpha.id}'}\n"
                "two:\n  resource: project\n  depends_on: [accounts.beta]\n"
                "  body: {slug: two, owner: '${accounts.beta.id}'}\n"
            ),
        }
    )
    return Materializer(root, "test", {"fake": fake})


def test_materialize_stops_at_the_first_failure_by_default(two_chains, fake):
    fake.fail_create.add("accounts.alpha")
    outcome = two_chains.materialize(["projects.one", "projects.two"])

    assert [(r["id"], r["ok"]) for r in outcome["results"]] == [("accounts.alpha", False)]
    # nothing past the failure was attempted, not even the independent chain
    assert fake.actions("create") == ["accounts.alpha"]


def test_keep_going_attempts_the_independent_chain(two_chains, fake):
    fake.fail_create.add("accounts.alpha")
    outcome = two_chains.materialize(["projects.one", "projects.two"], keep_going=True)

    by_id = {r["id"]: r for r in outcome["results"]}
    assert by_id["accounts.alpha"]["ok"] is False
    assert by_id["accounts.beta"]["ok"] is True
    assert by_id["projects.two"]["ok"] is True  # the independent chain finished
    assert set(outcome["records"]) == {"accounts.beta", "projects.two"}


def test_keep_going_blocks_the_dependents_of_a_failure(two_chains, fake):
    fake.fail_create.add("accounts.alpha")
    outcome = two_chains.materialize(["projects.one", "projects.two"], keep_going=True)

    blocked = next(r for r in outcome["results"] if r["id"] == "projects.one")
    assert blocked["action"] == "blocked"
    assert blocked["ok"] is False
    assert "depends on accounts.alpha" in blocked["detail"]
    # and it was never attempted against the backend
    assert "projects.one" not in fake.actions("create")


def test_keep_going_blocks_transitively(write_catalog, fake):
    root = write_catalog(
        {
            "resources.yaml": "thing:\n  system: fake\n  natural_key: name\n",
            "things.yaml": (
                "a:\n  resource: thing\n  body: {name: a}\n"
                "b:\n  resource: thing\n  depends_on: [things.a]\n  body: {name: b, up: '${things.a.id}'}\n"
                "c:\n  resource: thing\n  depends_on: [things.b]\n  body: {name: c, up: '${things.b.id}'}\n"
            ),
        }
    )
    engine = Materializer(root, "test", {"fake": fake})
    fake.fail_create.add("things.a")

    outcome = engine.materialize(["things.c"], keep_going=True)
    actions = {r["id"]: r["action"] for r in outcome["results"]}
    assert actions == {"things.a": "error", "things.b": "blocked", "things.c": "blocked"}


def test_ensure_is_never_keep_going(two_chains, fake):
    """A spec needs its one resource; there is nothing to continue toward."""
    fake.fail_create.add("accounts.alpha")
    with pytest.raises(ProvisioningError) as err:
        two_chains.ensure("project", "one")
    assert err.value.node_id == "accounts.alpha"
