"""What the provisioning engine guarantees as a Python object, where no scenario can watch.

Most of what `Materializer` does is now said in `selftest/specs/features/` — seeding a chain,
stopping at a failure, keeping going, blocking what depended on it, tearing down what was built for
a run. Those are behaviours a person can observe, and a scenario is a better description of them
than a unit test was.

What is left here is the part with no observable surface, and it is deliberately small:

- **A graph and a cache.** `closure` and `topo` are pure functions over a dependency graph;
  `cached` is a memo. A scenario can prove that seeding happens dependency-first — the mutation
  guard in `test_selftest.py` breaks `topo` and watches the right scenario go red — but it cannot
  say *which* function was wrong, and for a pure function with a decision procedure the unit test
  is the better diagnosis. This is the trade `ATF-TARGET.md`'s risk section names, made explicitly
  and in the one place it is worth making.
- **The adapter registry.** A registration API, not a behaviour: nothing a suite can do observes it
  except by having an adapter at all.
- **What happens when an adapter misbehaves.** A `find` that raises must become a reported `error`
  rather than a crash, and a `delete` that raises must not fail a run that already passed. Both
  *are* observable in principle — through a suite-side adapter told to break — and both are
  [deliberately not converted yet](../ATF-PLAN.md); see the M1d notes.

Everything here uses the fake adapter from `conftest.py`, so it is fast and touches nothing.
"""

from __future__ import annotations

import pytest

from atf.adapters import build, register, registered_systems, unregister
from atf.materializer import Materializer, ProvisioningError, UnknownResource

# ---- the registry -----------------------------------------------------------


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


# ---- the graph --------------------------------------------------------------


def test_closure_and_topo(materializer):
    """Dependency-first ordering. A scenario proves it happens; this says where it is decided."""
    assert set(materializer.closure("runs.nightly")) == {"runs.nightly", "projects.alpha", "accounts.primary"}
    order = materializer.topo(materializer.closure("runs.nightly"))
    assert order == ["accounts.primary", "projects.alpha", "runs.nightly"]


def test_unknown_resource(materializer):
    with pytest.raises(UnknownResource):
        materializer.resolve_id("account", "nope")
    with pytest.raises(UnknownResource):
        materializer.node("nope.nope")


# ---- the listing cache ------------------------------------------------------


def test_listing_cache_is_reused_then_invalidated_on_create(materializer, fake):
    """A memo, and the one thing that must drop it: something was created, so a listing is stale."""
    calls: list[str] = []
    materializer.cached("k", lambda: calls.append("load") or "v")
    materializer.cached("k", lambda: calls.append("load") or "v")
    assert calls == ["load"]
    materializer.ensure("account", "primary")
    materializer.cached("k", lambda: calls.append("load") or "v")
    assert calls == ["load", "load"]


# ---- an adapter that misbehaves ---------------------------------------------


def test_status_reports_adapter_errors(materializer, fake):
    """A backend that is down is a status, not a traceback: every other node still gets read."""

    def explode(node, ctx):
        raise RuntimeError("backend down")

    fake.find = explode  # type: ignore[method-assign]
    entry = materializer.status("accounts")["accounts.primary"]
    assert entry["status"] == "error"
    assert "backend down" in entry["detail"]


def test_teardown_never_raises(materializer, fake):
    """A scenario that passed must not be turned red by the cleanup after it."""
    outcome = materializer.materialize(["leads.walkin"])

    def explode(node, record, ctx):
        raise RuntimeError("backend down")

    fake.delete = explode  # type: ignore[method-assign]
    materializer.teardown(outcome["records"])


# ---- provisioning for a scenario is not provisioning for a seed --------------


def test_ensure_is_never_keep_going(write_catalog, fake):
    """A spec needs its one resource; there is nothing to continue toward.

    `atf seed --keep-going` is the opposite case and `seeding.feature` says it: seeding a whole
    catalog is worth finishing, because the failures are usually independent of each other.
    """
    root = write_catalog(
        {
            "resources.yaml": (
                "account:\n  system: fake\n  natural_key: email\n"
                "project:\n  system: fake\n  natural_key: slug\n"
            ),
            "accounts.yaml": "alpha:\n  resource: account\n  body: {email: alpha@e.test}\n",
            "projects.yaml": (
                "one:\n  resource: project\n  depends_on: [accounts.alpha]\n"
                "  body: {slug: one, owner: '${accounts.alpha.id}'}\n"
            ),
        }
    )
    engine = Materializer(root, "test", {"fake": fake})
    fake.fail_create.add("accounts.alpha")

    with pytest.raises(ProvisioningError) as err:
        engine.ensure("project", "one")
    assert err.value.node_id == "accounts.alpha"


# ---- still here, and why ----------------------------------------------------
#
# Each of these has an observable surface that `selftest` cannot reach *yet*, rather than none at
# all. They are listed in `ATF-PLAN.md` under what M1d deliberately did not convert, with the
# vocabulary each one is waiting for:
#
# - the ephemeral pair need a sub-suite whose persistent resource hangs off an ephemeral one;
# - the cache pair need a step that changes the backend behind ATF's back, between two commands;
# - `mode: data` needs the cockpit's "can this be created?" question, which is M2's.


def test_ephemeral_is_built_every_pass_and_returned(materializer, fake):
    first = materializer.ensure("lead", "walkin")
    second = materializer.ensure("lead", "walkin")
    assert first["id"] == "lead-1"
    assert second["id"] == "lead-2"
    assert fake.actions("create") == ["leads.walkin", "leads.walkin"]


def test_status_can_scope_to_a_collection(materializer):
    assert set(materializer.status("projects")) == {"projects.alpha"}


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


def test_data_mode_is_an_answer_when_absent_rather_than_a_failure(materializer):
    outcome = materializer.create_closure("sightings.watched")
    assert outcome["results"][0]["ok"] is True
    assert outcome["results"][0]["action"] == "observed"


def test_data_mode_reads_back_what_is_there(materializer, fake):
    fake.seed("sighting", {"name": "watched", "id": "s-1"})
    record = materializer.ensure("sighting", "watched")
    assert record["id"] == "s-1"
    assert fake.actions("create") == [], "an observation is never created"


def test_data_mode_is_never_offered_as_something_to_create(materializer):
    can, why = materializer.provisionable("sightings.watched")
    assert can is False
    assert "an observation" in why

    can, why = materializer.provisionable("widgets.imported")
    assert can is False
    assert "must already exist" in why, "reference keeps its own reason, and its own behaviour"