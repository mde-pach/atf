"""Authoring the catalog from the cockpit.

Two invariants are load-bearing here and each has its own test: a change is never written unless
the whole catalog still loads afterwards, and a path is never taken from the form. The rest of the
file is about the feature the authoring UI exists for — turning records an environment already has
into the catalog that declares them.

None of it converts to a scenario, and the reason is the same one that makes it worth testing: every
line here is a *write*, or a write being refused. What it is about is the bytes in a catalog file
afterwards, not anything a page shows — and a page resource only ever GETs, so that nothing which
reads the interface can change it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from atf.accessible import Page
from atf.catalog import load_catalog
from atf.cockpit.app import create_app
from atf.cockpit.deps import Cockpit, set_cockpit
from atf.cockpit.routers.authoring import Proposal, apply, literal
from tests.sample_project import write_sample_project

REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

# A type whose listing is scoped to a parent, as `todo_list` is in the shipped example. Appended to
# the sample project's registry rather than baked into it, so only these tests carry the cost.
SCOPED_TYPE = """
note:
  system: store
  collection: notes
  natural_key: [account_id, slug]
  list_path: /accounts/{account_id}/notes
"""


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
    """A cockpit on the sample project.

    The suite's adapter module is dropped from `sys.modules` on the way out as well as on the way
    in: it registers systems into a process-wide registry, and another suite's module of the same
    name would otherwise never be imported at all.
    """
    import sys

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


class Browsing:
    """The sample project's store adapter, plus the optional `browse` capability.

    The project's own adapter cannot enumerate — which is the other case the type page has to
    handle — so a browsable one is swapped in where a test is about reading an environment.
    """

    def __init__(self, inner: Any, path: Path) -> None:
        self.inner = inner
        self.path = path

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def browse(self, node: dict[str, Any], ctx: Any, limit: int = 200) -> list[dict[str, Any]]:
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        collection = node["config"].get("collection", node["resource"] + "s")
        return list(data.get(collection, []))[:limit]


@pytest.fixture
def browsable(client, project):
    engine = client.cockpit.state("dev").materializer
    engine.adapters["store"] = Browsing(engine.adapters["store"], project / "store.json")
    return engine.adapters["store"]


def confirm(client) -> str:
    return client.cockpit.confirm_token


def seed(project: Path, collection: str, record: dict[str, Any]) -> dict[str, Any]:
    """Put a record in the environment without telling the catalog about it."""
    store = project / "store.json"
    data = json.loads(store.read_text()) if store.exists() else {}
    data.setdefault(collection, []).append(record)
    store.write_text(json.dumps(data, indent=2))
    return record


def form(**fields: Any) -> dict[str, Any]:
    return {"action": "create", "body_mode": "rows", **fields}


def provision(client, node_id: str) -> None:
    import time

    client.post("/provision", data={"confirm": confirm(client), "node": node_id})
    deadline = time.time() + 60
    while client.cockpit.active_job("dev") is not None and time.time() < deadline:
        time.sleep(0.05)


# ---- reading the environment ------------------------------------------------


def test_the_type_page_lists_what_the_environment_already_has(client, project, browsable):
    """One table: what the catalog declares, a divider, then what only the environment has."""
    seed(project, "accounts", {"id": "account-9", "email": "third@example.test", "plan": "trial"})

    page = Page(client.get("/catalog/type/account").text)
    assert page.says("not declared in the catalog")
    assert page.says("third@example.test")  # the record, labelled by its natural key
    assert page.says("plan trial")  # and the rest of what it carries
    assert page.controls("button", "Add to catalog") or page.says("Add to catalog")
    # The declared instances are rows of the *same* table rather than a second list of them, so the
    # one this suite declares is read before the one only the environment has. Said about the cells
    # in document order rather than about where their bytes fell.
    cells = [cell.name for cell in page.controls("cell")]
    assert cells.index("primary") < cells.index("third@example.test")


def test_a_record_the_catalog_already_declares_is_marked_not_offered(client, project, browsable):
    provision(client, "accounts.primary")

    body = client.get("/catalog/type/account").text
    assert 'class="known"' in body
    # The declared row links to its node instead of offering to declare it a second time.
    assert 'href="/catalog/node/accounts.primary?env=dev"' in body
    assert body.count("Add to catalog") == 0


def test_an_adapter_that_cannot_browse_says_so_instead_of_leaving_the_table_short(client):
    """The catalog's own instances are still listed — what is missing is the environment's half."""
    body = client.get("/catalog/type/account").text
    assert "cannot list what is out there" in body
    assert "implementing <code>browse</code>" in body
    assert "not declared in the catalog" not in body


def test_a_scoped_listing_asks_which_parent_to_look_inside(client, project, browsable):
    (project / "catalog" / "resources.yaml").write_text(
        (project / "catalog" / "resources.yaml").read_text() + SCOPED_TYPE, encoding="utf-8"
    )
    # The swapped-in adapter survives `invalidate`: only the catalog is re-read from disk.
    client.cockpit.invalidate("dev")
    assert client.cockpit.state("dev").materializer.adapters["store"] is browsable

    body = client.get("/catalog/type/note").text
    assert "listed per parent" in body
    assert "account_id" in body
    # The chooser is the accounts already in the catalog, and one that is absent cannot be entered.
    assert "provision it first" in body
    assert ">primary" in body


def test_browsing_inside_a_chosen_parent_lists_what_is_in_it(client, project, browsable):
    (project / "catalog" / "resources.yaml").write_text(
        (project / "catalog" / "resources.yaml").read_text() + SCOPED_TYPE, encoding="utf-8"
    )
    client.cockpit.invalidate("dev")
    provision(client, "accounts.primary")
    identity = client.cockpit.status("dev")["accounts.primary"]["identity"]
    seed(project, "notes", {"id": "note-1", "account_id": identity, "slug": "kept"})

    body = client.get("/catalog/type/note?scope=accounts.primary").text
    assert 'class="records instances"' in body
    assert "kept" in body  # the record, labelled by its natural key
    assert "identity=note-1" in body  # and carried into the form that would declare it
    assert "Add to catalog" in body


# ---- from a record to a node ------------------------------------------------


def test_a_record_out_there_becomes_a_node_that_finds_it_again(client, project, browsable):
    """The round trip that matters: derive a node from a record, write it, and ATF finds that record."""
    seed(project, "accounts", {"id": "account-9", "email": "third@example.test", "plan": "trial"})

    sheet = client.get("/authoring/new?type=account&identity=account-9").text
    assert 'name="name" value="third"' in sheet
    assert 'value="third@example.test"' in sheet
    # `id` is the backend's to assign, so the derived body must not declare it.
    assert "account-9" not in sheet

    written = client.post(
        "/authoring/write",
        data=form(
            type="account",
            name="third",
            file="accounts.yaml",
            represents="Imported from the environment.",
            body_key=["email", "plan"],
            body_value=["third@example.test", "trial"],
            confirm=confirm(client),
        ),
    )
    assert written.status_code == 200

    nodes = client.cockpit.state("dev").materializer.nodes
    assert "accounts.third" in nodes
    assert client.cockpit.status("dev", refresh=True)["accounts.third"]["status"] == "present"


def test_a_derived_node_points_at_the_catalog_rather_than_at_this_environment(client, project, browsable):
    """A foreign key becomes a `${...}` placeholder, which is what makes the node re-creatable."""
    provision(client, "accounts.primary")
    identity = client.cockpit.status("dev")["accounts.primary"]["identity"]
    seed(project, "projects", {"id": "project-9", "slug": "imported", "account_id": identity})

    sheet = client.get("/authoring/new?type=project&identity=project-9").text
    assert "${accounts.primary.id}" in sheet
    assert 'value="accounts.primary" selected' in sheet
    assert str(identity) not in sheet.split('name="body_value"')[1][:200]


# ---- the diff is shown first -----------------------------------------------


def test_the_proposed_change_is_shown_and_nothing_is_written_to_produce_it(client, project):
    path = project / "catalog" / "accounts.yaml"
    before = path.read_bytes()

    response = client.post(
        "/authoring/preview",
        data=form(type="account", name="third", file="accounts.yaml", body_key=["email"], body_value=["c@e.test"]),
    )
    assert response.status_code == 200
    assert 'class="diff"' in response.text
    assert 'class="add"' in response.text and "+third:" in response.text
    assert path.read_bytes() == before


def test_the_diff_explains_a_change_that_cannot_be_written(client):
    response = client.post(
        "/authoring/preview",
        data=form(type="account", name="primary", file="accounts.yaml", body_key=["email"], body_value=["x@y.test"]),
    )
    assert "there is already an account called" in response.text
    assert "accounts.primary" in response.text
    assert 'class="diff"' not in response.text


# ---- create, copy, edit ----------------------------------------------------


def test_a_created_resource_lands_in_the_file_the_form_names(client, project):
    response = client.post(
        "/authoring/write",
        data=form(
            type="badge",
            name="latecomer",
            file="badges.yaml",
            represents="A badge added from the cockpit.",
            body_key=["slug"],
            body_value=["latecomer"],
            confirm=confirm(client),
        ),
    )
    assert response.status_code == 200
    # The response is the whole catalog vertical again: that is what closes the form and moves the
    # selection to what was just written.
    assert 'id="catalog"' in response.text
    assert "Added the badge latecomer in catalog/badges.yaml." in response.text

    text = (project / "catalog" / "badges.yaml").read_text()
    assert "latecomer:" in text and "resource: badge" in text
    assert "welcome:" in text  # the entry that was already there is untouched
    assert "badges.latecomer" in client.cockpit.state("dev").materializer.nodes


def test_the_default_file_is_the_one_this_type_already_lives_in(client):
    sheet = client.get("/authoring/new?type=project").text
    assert 'name="file" value="projects.yaml"' in sheet


def test_a_type_with_no_instance_yet_defaults_to_a_file_named_for_it(client, project):
    (project / "catalog" / "widgets.yaml").write_text("", encoding="utf-8")
    client.cockpit.invalidate("dev")

    sheet = client.get("/authoring/new?type=external_widget").text
    assert 'name="file" value="external_widgets.yaml"' in sheet


def test_copying_suggests_a_new_name_and_keeps_everything_else(client):
    sheet = client.get("/authoring/copy/projects.alpha").text
    assert 'name="name" value="alpha_copy"' in sheet
    assert "${accounts.primary.id}" in sheet
    assert 'value="accounts.primary" selected' in sheet


def test_an_edit_changes_one_entry_and_leaves_the_rest_of_the_file_alone(client, project):
    path = project / "catalog" / "accounts.yaml"
    path.write_text("# accounts, oldest first — do not reorder\n" + path.read_text(), encoding="utf-8")
    client.cockpit.invalidate("dev")

    response = client.post(
        "/authoring/write",
        data=form(
            action="edit",
            type="account",
            node="accounts.primary",
            name="primary",
            represents="Now on the premium plan.",
            body_key=["email", "plan"],
            body_value=["primary@example.test", "premium"],
            confirm=confirm(client),
        ),
    )
    assert response.status_code == 200

    text = path.read_text()
    assert "# accounts, oldest first — do not reorder" in text
    assert "Now on the premium plan." in text and "premium" in text
    assert "secondary@example.test" in text  # the other entry survived
    nodes = client.cockpit.state("dev").materializer.nodes
    assert nodes["accounts.primary"]["body"]["plan"] == "premium"


def test_a_body_written_as_raw_yaml_keeps_its_structure(client, project):
    response = client.post(
        "/authoring/write",
        data={
            "action": "create",
            "type": "badge",
            "name": "nested",
            "file": "badges.yaml",
            "body_mode": "yaml",
            "body_yaml": "slug: nested\nmeta:\n  tier: gold\n  tags: [a, b]\n",
            "confirm": confirm(client),
        },
    )
    assert response.status_code == 200

    body = client.cockpit.state("dev").materializer.nodes["badges.nested"]["body"]
    assert body["meta"] == {"tier": "gold", "tags": ["a", "b"]}


def test_a_form_value_is_read_as_the_value_it_means():
    assert literal("false") is False
    assert literal("12") == 12
    assert literal("null") is None
    assert literal("1.5") == 1.5
    assert literal("${accounts.primary.id}") == "${accounts.primary.id}"
    assert literal("2024-01-01") == "2024-01-01"
    assert literal("primary@example.test") == "primary@example.test"


# ---- the catalog must never stop loading ------------------------------------


def test_a_change_that_would_break_the_catalog_is_refused_and_the_file_restored(client, project):
    """The write path itself: the file goes back byte-for-byte and the catalog still loads."""
    path = project / "catalog" / "accounts.yaml"
    before = path.read_bytes()

    proposal = Proposal(
        action="edit",
        name="primary",
        path=path,
        before=path.read_text(encoding="utf-8"),
        after="primary:\n  resource: no_such_type\n  body: {}\n",
    )
    with pytest.raises(HTTPException) as raised:
        apply("dev", proposal)

    assert raised.value.status_code == 409
    assert "unknown resource type" in str(raised.value.detail)
    assert path.read_bytes() == before
    load_catalog(project / "catalog", {"store", "ephemeral"})


def test_a_refused_change_to_a_new_file_leaves_no_file_behind(client, project):
    path = project / "catalog" / "strays.yaml"
    proposal = Proposal(action="create", name="stray", path=path, before="", after="stray:\n  resource: nope\n")

    with pytest.raises(HTTPException):
        apply("dev", proposal)
    assert not path.exists()


def test_the_route_refuses_a_body_that_references_a_resource_that_does_not_exist(client, project):
    path = project / "catalog" / "projects.yaml"
    before = path.read_bytes()

    response = client.post(
        "/authoring/write",
        data={
            "action": "create",
            "type": "project",
            "name": "orphan",
            "file": "projects.yaml",
            "body_mode": "yaml",
            "body_yaml": "slug: orphan\naccount_id: ${accounts.nope.id}\n",
            "confirm": confirm(client),
        },
    )
    assert response.status_code == 409
    assert "not a known node" in response.text
    assert path.read_bytes() == before


def test_a_name_that_is_already_taken_is_refused(client):
    response = client.post(
        "/authoring/write",
        data=form(
            type="account",
            name="primary",
            file="accounts.yaml",
            body_key=["email"],
            body_value=["again@example.test"],
            confirm=confirm(client),
        ),
    )
    assert response.status_code == 409
    assert "already" in response.text


# ---- delete ----------------------------------------------------------------


def test_delete_is_refused_while_something_depends_on_the_resource(client, project):
    sheet = client.get("/authoring/delete/accounts.primary").text
    assert "projects.alpha" in sheet
    assert "disabled" in sheet
    assert "depends_on pointing at nothing" in sheet

    path = project / "catalog" / "accounts.yaml"
    before = path.read_bytes()
    response = client.post("/authoring/remove", data={"node": "accounts.primary", "confirm": confirm(client)})

    assert response.status_code == 409
    assert "depend" in response.text
    assert path.read_bytes() == before


def test_deleting_a_resource_nothing_depends_on_removes_only_its_entry(client, project):
    response = client.post("/authoring/remove", data={"node": "accounts.secondary", "confirm": confirm(client)})
    assert response.status_code == 200

    text = (project / "catalog" / "accounts.yaml").read_text()
    assert "secondary" not in text
    assert "primary" in text
    assert "accounts.secondary" not in client.cockpit.state("dev").materializer.nodes


# ---- the gate is confirmation, not `mutable_envs` ---------------------------


@pytest.mark.parametrize("path", ["/authoring/write", "/authoring/remove"])
def test_authoring_without_the_confirmation_token_is_rejected(client, path):
    response = client.post(path, data={"node": "accounts.secondary", "type": "account", "name": "x"})
    assert response.status_code == 409
    assert "must be confirmed" in response.text


def test_a_read_only_environment_can_still_have_its_catalog_authored(client, project):
    """Editing the catalog is a source change: it is the same edit whichever environment is selected."""
    response = client.post(
        "/authoring/write?env=locked",
        data=form(
            type="badge",
            name="from_locked",
            file="badges.yaml",
            body_key=["slug"],
            body_value=["from_locked"],
            confirm=confirm(client),
        ),
    )
    assert response.status_code == 200
    assert "from_locked:" in (project / "catalog" / "badges.yaml").read_text()


def test_a_read_only_environment_still_refuses_to_be_provisioned(client):
    """The gate that does apply there is untouched by authoring."""
    response = client.post("/provision?env=locked", data={"confirm": confirm(client)})
    assert response.status_code == 409
    assert "read-only" in response.text


# ---- paths come from the manifest, never from the form ----------------------


@pytest.mark.parametrize(
    "name",
    ["../evil", "../../evil.yaml", "/etc/evil.yaml", "sub/evil.yaml", "resources.yaml", ".hidden", "Bad-Name"],
)
def test_a_file_outside_the_catalog_directory_is_refused(client, project, name):
    registry = (project / "catalog" / "resources.yaml").read_bytes()

    response = client.post(
        "/authoring/write",
        data=form(
            type="badge",
            name="stray",
            file=name,
            body_key=["slug"],
            body_value=["stray"],
            confirm=confirm(client),
        ),
    )
    assert response.status_code == 409

    assert (project / "catalog" / "resources.yaml").read_bytes() == registry
    assert not (project / "evil.yaml").exists()
    assert not (project.parent / "evil.yaml").exists()
    assert list((project / "catalog").glob("**/evil.yaml")) == []


def test_a_blank_file_falls_back_to_where_the_type_already_lives(client, project):
    """The one path the form may leave to the cockpit: it still lands in `catalog_dir`."""
    response = client.post(
        "/authoring/write",
        data=form(
            type="badge",
            name="defaulted",
            body_key=["slug"],
            body_value=["defaulted"],
            confirm=confirm(client),
        ),
    )
    assert response.status_code == 200
    assert "defaulted:" in (project / "catalog" / "badges.yaml").read_text()
