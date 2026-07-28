from __future__ import annotations

import pytest

from atf.catalog import CatalogError, find_node, load_catalog, resource_types

SYSTEMS = {"fake"}


def test_loads_ids_types_and_reverse_edges(good_catalog):
    types, nodes = load_catalog(good_catalog, SYSTEMS)

    assert set(types) == {"account", "project", "job_run", "lead", "widget", "sighting"}
    assert set(nodes) == {
        "accounts.primary",
        "projects.alpha",
        "runs.nightly",
        "leads.walkin",
        "widgets.imported",
        "sightings.watched",
    }

    alpha = nodes["projects.alpha"]
    assert alpha["collection"] == "projects"
    assert alpha["name"] == "alpha"
    assert alpha["resource"] == "project"
    assert alpha["system"] == "fake"
    assert alpha["mode"] == "create"
    assert alpha["lifecycle"] == "persistent"
    assert alpha["id_field"] == "id"
    assert alpha["config"] == {"natural_key": ["account_id", "slug"]}
    assert alpha["depends_on"] == ["accounts.primary"]
    assert alpha["body"]["account_id"] == "${accounts.primary.id}"

    assert nodes["accounts.primary"]["dependents"] == ["projects.alpha"]
    assert nodes["projects.alpha"]["dependents"] == ["runs.nightly"]
    assert nodes["runs.nightly"]["dependents"] == []


def test_type_level_keys_reach_the_node(good_catalog):
    _, nodes = load_catalog(good_catalog, SYSTEMS)
    assert nodes["runs.nightly"]["id_field"] == "uuid"
    assert nodes["leads.walkin"]["lifecycle"] == "ephemeral"
    assert nodes["widgets.imported"]["mode"] == "reference"
    assert nodes["widgets.imported"]["config"]["ref_field"] == "name"


def test_helpers(good_catalog):
    _, nodes = load_catalog(good_catalog, SYSTEMS)
    assert resource_types(nodes) == {"account", "project", "job_run", "lead", "widget", "sighting"}
    node = find_node(nodes, "project", "alpha")
    assert node is not None and node["id"] == "projects.alpha"
    assert find_node(nodes, "project", "nope") is None


def test_missing_directory(tmp_path):
    with pytest.raises(CatalogError) as err:
        load_catalog(tmp_path / "nope", SYSTEMS)
    assert "does not exist" in str(err.value)


def test_missing_types_file(write_catalog):
    root = write_catalog({"accounts.yaml": "primary:\n  resource: account\n"})
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("resources.yaml is missing" in p for p in err.value.problems)


def test_unknown_resource_type(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\n",
            "ghosts.yaml": "spooky:\n  resource: ghost\n",
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("unknown resource type 'ghost'" in p for p in err.value.problems)


def test_dangling_dependency(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\n",
            "accounts.yaml": "primary:\n  resource: account\n  depends_on: [accounts.missing]\n",
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("not a known node" in p for p in err.value.problems)


def test_duplicate_name_for_same_type(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\n",
            "a.yaml": "primary:\n  resource: account\n",
            "b.yaml": "primary:\n  resource: account\n",
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("duplicate name 'primary'" in p for p in err.value.problems)


def test_same_name_across_different_types_is_fine(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\nproject:\n  system: fake\n",
            "a.yaml": "shared:\n  resource: account\n",
            "b.yaml": "shared:\n  resource: project\n",
        }
    )
    _, nodes = load_catalog(root, SYSTEMS)
    assert set(nodes) == {"a.shared", "b.shared"}


def test_unknown_system(write_catalog):
    root = write_catalog({"resources.yaml": "account:\n  system: quantum\n"})
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("system 'quantum' with no registered adapter" in p for p in err.value.problems)


def test_reserved_name_collision(write_catalog):
    root = write_catalog({"resources.yaml": "context:\n  system: fake\napi:\n  system: fake\n"})
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert sum("reserved fixture name" in p for p in err.value.problems) == 2


def test_cycle_is_detected(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\n",
            "accounts.yaml": (
                "one:\n  resource: account\n  depends_on: [accounts.two]\n"
                "two:\n  resource: account\n  depends_on: [accounts.three]\n"
                "three:\n  resource: account\n  depends_on: [accounts.one]\n"
            ),
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    cycles = [p for p in err.value.problems if p.startswith("dependency cycle")]
    assert len(cycles) == 1
    assert cycles[0].count("->") == 3


def test_self_cycle_is_detected(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\n",
            "accounts.yaml": "loop:\n  resource: account\n  depends_on: [accounts.loop]\n",
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any(p.startswith("dependency cycle") for p in err.value.problems)


def test_bad_mode_and_lifecycle(write_catalog):
    root = write_catalog({"resources.yaml": "account:\n  system: fake\n  mode: destroy\n  lifecycle: forever\n"})
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("mode 'destroy'" in p for p in err.value.problems)
    assert any("lifecycle 'forever'" in p for p in err.value.problems)


def test_all_problems_are_reported_at_once(write_catalog):
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: quantum\ncontext:\n  system: fake\n",
            "accounts.yaml": (
                "primary:\n  resource: account\n  depends_on: [accounts.missing]\n"
                "other:\n  resource: nope\n"
            ),
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert len(err.value.problems) >= 4


def test_loader_is_import_safe(good_catalog, monkeypatch):
    # No socket use: the loader must be pure filesystem + yaml.
    import socket

    def explode(*args, **kwargs):
        raise AssertionError("catalog loader must not touch the network")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    load_catalog(good_catalog, SYSTEMS)


def test_a_placeholder_typo_is_caught_at_load(write_catalog):
    """The loader's promise is to list every problem at load; this was failing at provision time."""
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\nproject:\n  system: fake\n",
            "accounts.yaml": "primary:\n  resource: account\n",
            "projects.yaml": (
                "alpha:\n  resource: project\n  depends_on: [accounts.primary]\n"
                "  body: {account_id: '${accounts.typo.id}'}\n"
            ),
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("not a known node" in problem for problem in err.value.problems)


def test_a_reference_outside_depends_on_is_caught(write_catalog):
    """It resolves only by luck of ordering, and silently is not provisioned first."""
    root = write_catalog(
        {
            "resources.yaml": "account:\n  system: fake\nproject:\n  system: fake\n",
            "accounts.yaml": "primary:\n  resource: account\n",
            "projects.yaml": "alpha:\n  resource: project\n  body: {account_id: '${accounts.primary.id}'}\n",
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root, SYSTEMS)
    assert any("does not list it in depends_on" in problem for problem in err.value.problems)


# ---- a generated value where ATF has to look one up again -------------------

GENERATED_TYPES = """
account:
  system: fake
  natural_key: email
visitor:
  system: fake
  lifecycle: ephemeral
  natural_key: email
widget:
  system: fake
  mode: reference
  natural_key: name
"""


def test_a_generated_natural_key_is_refused(write_catalog):
    """`find` resolves the key and asks the backend for a match. A value that is new every run
    never matches, so every run creates another record and the environment fills up quietly."""
    root = write_catalog(
        {
            "resources.yaml": GENERATED_TYPES,
            "accounts.yaml": "primary:\n  resource: account\n  body:\n    email: ${fake:email}\n",
        }
    )
    with pytest.raises(CatalogError) as err:
        load_catalog(root)

    problem = "\n".join(err.value.problems)
    assert "accounts.primary: email is part of the natural key and is generated" in problem
    assert "Write it out, or make the type ephemeral" in problem


def test_a_generated_key_on_an_ephemeral_resource_is_fine(write_catalog):
    """One is never looked up — that is what ephemeral means — so nothing can accumulate."""
    root = write_catalog(
        {
            "resources.yaml": GENERATED_TYPES,
            "visitors.yaml": "walkin:\n  resource: visitor\n  body:\n    email: ${fake:email}\n",
        }
    )
    _, nodes = load_catalog(root)
    assert nodes["visitors.walkin"]["body"]["email"] == "${fake:email}"


def test_a_generated_value_outside_the_natural_key_is_fine(write_catalog):
    """It is only ever evaluated at creation; every later run finds the record and keeps it."""
    root = write_catalog(
        {
            "resources.yaml": GENERATED_TYPES,
            "accounts.yaml": (
                "primary:\n  resource: account\n  body:\n"
                "    email: primary@example.test\n    nickname: ${fake:first_name}\n"
            ),
        }
    )
    _, nodes = load_catalog(root)
    assert nodes["accounts.primary"]["body"]["nickname"] == "${fake:first_name}"


def test_a_node_reference_in_a_natural_key_is_not_a_generated_value(write_catalog):
    """`${...id}` is resolved from the graph and is the same every run, which is the whole point."""
    root = write_catalog(
        {
            "resources.yaml": GENERATED_TYPES + "\nnote:\n  system: fake\n  natural_key: [account_id, slug]\n",
            "accounts.yaml": "primary:\n  resource: account\n  body:\n    email: a@b.test\n",
            "notes.yaml": (
                "first:\n  resource: note\n  depends_on: [accounts.primary]\n"
                "  body:\n    slug: first\n    account_id: ${accounts.primary.id}\n"
            ),
        }
    )
    _, nodes = load_catalog(root)
    assert nodes["notes.first"]["body"]["account_id"] == "${accounts.primary.id}"


def test_the_three_modes_are_the_ones_the_model_has(good_catalog):
    """`data` is a third mode, not a rename of `reference`: an observation is not a precondition."""
    _, nodes = load_catalog(good_catalog, SYSTEMS)
    assert nodes["accounts.primary"]["mode"] == "create"
    assert nodes["widgets.imported"]["mode"] == "reference"
    assert nodes["sightings.watched"]["mode"] == "data"
