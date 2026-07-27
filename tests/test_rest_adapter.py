from __future__ import annotations

import pytest

from atf.adapters import build, registered_systems
from atf.adapters.reference import ReferenceAdapter
from atf.adapters.rest import RestAdapter
from atf.materializer import Materializer, ProvisioningError
from tests.stub_api import StubAPI

TYPES = """
account:
  system: rest
  path: /accounts
  natural_key: email
project:
  system: rest
  path: /projects
  natural_key: [account_id, slug]
  list_path: /accounts/{account_id}/projects
job_run:
  system: rest
  path: /runs
  natural_key: token
  id_field: uuid
widget:
  system: reference
  mode: reference
  path: /widgets
  natural_key: name
  ref_field: label
scheduled:
  system: rest
  path: /scheduled
  natural_key: due_at
"""

INSTANCES = {
    "accounts.yaml": """
primary:
  resource: account
  represents: Primary account.
  body:
    email: primary@example.test
""",
    "projects.yaml": """
alpha:
  resource: project
  represents: Alpha project.
  depends_on: [accounts.primary]
  body:
    slug: alpha
    account_id: ${accounts.primary.id}
""",
    "runs.yaml": """
nightly:
  resource: job_run
  represents: Nightly run.
  body:
    token: nightly
""",
    "widgets.yaml": """
imported:
  resource: widget
  represents: Must already exist.
  body:
    name: imported
""",
    "scheduled.yaml": """
tomorrow:
  resource: scheduled
  represents: A time-based natural key.
  body:
    due_at: ${now+1d 09:00}
""",
}


@pytest.fixture
def api():
    stub = StubAPI(id_fields={"runs": "uuid"})
    stub.base_url = stub.start()  # type: ignore[attr-defined]
    yield stub
    stub.stop()


@pytest.fixture
def catalog(write_catalog):
    return write_catalog({"resources.yaml": TYPES, **INSTANCES})


def engine(catalog, api, **settings) -> Materializer:
    base = {"base_url": api.base_url}
    adapters = {
        "rest": build("rest", {**base, **settings}),
        "reference": build("reference", {**base, **settings}),
    }
    return Materializer(catalog, "dev", adapters)


def test_builtin_systems_are_registered():
    assert {"rest", "reference"} <= registered_systems()


def test_get_or_create_is_idempotent(catalog, api):
    materializer = engine(catalog, api)
    first = materializer.ensure("account", "primary")
    assert first["id"] == "account-1"
    assert api.records["accounts"][0]["email"] == "primary@example.test"

    materializer.invalidate_cache()
    second = materializer.ensure("account", "primary")
    assert second["id"] == "account-1"
    assert len(api.records["accounts"]) == 1


def test_composite_and_scoped_keys(catalog, api):
    materializer = engine(catalog, api)
    project = materializer.ensure("project", "alpha")
    assert project["account_id"] == "account-1"

    materializer.invalidate_cache()
    again = materializer.ensure("project", "alpha")
    assert again["id"] == project["id"]
    assert len(api.records["projects"]) == 1
    # the scoped listing endpoint was used, not the bare collection
    assert any(path.startswith("/accounts/account-1/projects") for path in api.paths("GET"))


def test_non_default_id_field(catalog, api):
    materializer = engine(catalog, api)
    record = materializer.ensure("job_run", "nightly")
    assert record["uuid"] == "run-1"
    assert materializer.identity_of("runs.nightly") == "run-1"


def test_datetime_natural_key_matches_across_formats(catalog, api):
    materializer = engine(catalog, api)
    created = materializer.ensure("scheduled", "tomorrow")
    api.records["scheduled"][0]["due_at"] = str(created["due_at"]).replace("Z", "+00:00")

    materializer.invalidate_cache()
    assert materializer.ensure("scheduled", "tomorrow")["id"] == created["id"]
    assert len(api.records["scheduled"]) == 1


def test_reference_mode_errors_when_absent(catalog, api):
    materializer = engine(catalog, api)
    with pytest.raises(ProvisioningError) as err:
        materializer.ensure("widget", "imported")
    assert err.value.node_id == "widgets.imported"


def test_reference_mode_matches_ref_field(catalog, api):
    api.seed("widgets", {"id": "w-9", "label": "imported"})
    materializer = engine(catalog, api)
    assert materializer.ensure("widget", "imported")["id"] == "w-9"


def test_reference_adapter_refuses_to_create(catalog, api):
    adapter = ReferenceAdapter.from_settings({"base_url": api.base_url})
    materializer = engine(catalog, api)
    node = materializer.node("widgets.imported")
    with pytest.raises(ValueError, match="must already exist"):
        adapter.create(node, {}, materializer)
    assert adapter.delete(node, {"id": "x"}, materializer) is None


def test_pagination(catalog, api):
    api.paginate = True
    for index in range(250):
        api.seed("accounts", {"id": f"a-{index}", "email": f"user{index}@example.test"})
    api.seed("accounts", {"id": "target", "email": "primary@example.test"})

    materializer = engine(catalog, api, pagination={"results_key": "results", "count_key": "count", "page_size": 50})
    assert materializer.ensure("account", "primary")["id"] == "target"


def test_header_auth(catalog):
    stub = StubAPI(require_header=("X-Actor", "actor-1"))
    stub.base_url = stub.start()  # type: ignore[attr-defined]
    try:
        blocked = engine(catalog, stub)
        assert blocked.status("accounts")["accounts.primary"]["status"] == "error"

        allowed = engine(catalog, stub, auth={"header": "X-Actor", "value": "actor-1"})
        assert allowed.ensure("account", "primary")["id"] == "account-1"
    finally:
        stub.stop()


def test_bearer_auth(catalog):
    stub = StubAPI(require_bearer="t0ken")
    stub.base_url = stub.start()  # type: ignore[attr-defined]
    try:
        materializer = engine(catalog, stub, auth={"bearer": {"token": "t0ken"}})
        assert materializer.ensure("account", "primary")["id"] == "account-1"
    finally:
        stub.stop()


def test_session_auth_logs_in_once(catalog):
    stub = StubAPI(require_session=True)
    stub.base_url = stub.start()  # type: ignore[attr-defined]
    try:
        auth = {"session": {"login_path": "/login", "username": "user", "password": "pass"}}
        materializer = engine(catalog, stub, auth=auth)
        materializer.ensure("account", "primary")
        materializer.invalidate_cache()
        materializer.ensure("account", "primary")
        assert stub.paths("POST").count("/login") == 1
    finally:
        stub.stop()


def test_delete_removes_the_record(catalog, api):
    materializer = engine(catalog, api)
    record = materializer.ensure("account", "primary")
    node = materializer.node("accounts.primary")
    materializer.adapters["rest"].delete(node, record, materializer)
    assert api.records["accounts"] == []


def test_delete_uses_the_nodes_id_field(catalog, api):
    materializer = engine(catalog, api)
    record = materializer.ensure("job_run", "nightly")
    node = materializer.node("runs.nightly")

    materializer.adapters["rest"].delete(node, record, materializer)

    assert api.records["runs"] == []
    assert f"/runs/{record['uuid']}" in api.paths("DELETE")


def test_delete_tolerates_a_backend_without_deletion(catalog, api):
    materializer = engine(catalog, api)
    record = materializer.ensure("account", "primary")
    node = materializer.node("accounts.primary")
    node["config"]["deletable"] = False

    materializer.adapters["rest"].delete(node, record, materializer)
    assert api.paths("DELETE") == []


def test_unknown_auth_scheme_is_rejected(api):
    adapter = RestAdapter.from_settings({"base_url": api.base_url, "auth": {"magic": {}}})
    with pytest.raises(Exception, match="unknown auth scheme"):
        _ = adapter.client


def test_settings_require_a_base_url():
    with pytest.raises(ValueError, match="base_url"):
        RestAdapter.from_settings({})


def test_missing_path_or_natural_key_is_reported(write_catalog, api):
    catalog = write_catalog(
        {
            "resources.yaml": "thing:\n  system: rest\n",
            "things.yaml": "one:\n  resource: thing\n  body: {name: one}\n",
        }
    )
    materializer = engine(catalog, api)
    entry = materializer.status()["things.one"]
    assert entry["status"] == "error"
    assert "natural_key" in entry["detail"]


def test_status_reports_present_and_absent(catalog, api):
    api.seed("accounts", {"id": "a-1", "email": "primary@example.test"})
    materializer = engine(catalog, api)
    status = materializer.status()
    assert status["accounts.primary"] == {
        "status": "present",
        "detail": "",
        "identity": "a-1",
        # The record travels with the status: a caller offering an assertion on one of its fields
        # needs to know which fields there are without asking the backend a second time.
        "record": {"id": "a-1", "email": "primary@example.test"},
    }
    # alpha's natural key needs the account id, which resolves live
    assert status["projects.alpha"]["status"] == "absent"


def test_pagination_stops_on_a_short_page(catalog):
    """A backend with no `count_key` would otherwise page forever."""
    stub = StubAPI()
    stub.base_url = stub.start()  # type: ignore[attr-defined]
    try:
        for index in range(120):
            stub.seed("accounts", {"id": f"a-{index}", "email": f"user{index}@example.test"})
        stub.seed("accounts", {"id": "target", "email": "primary@example.test"})
        stub.paginate = True

        materializer = engine(catalog, stub, pagination={"results_key": "results", "page_size": 50})
        assert materializer.ensure("account", "primary")["id"] == "target"
    finally:
        stub.stop()


def test_pagination_gives_up_on_a_backend_that_ignores_the_offset(catalog, api):
    """Reproduces a loop that never terminated: same page returned for every request."""
    import atf.http as http_module

    def always_page_one(client, method, url, retries=0, backoff=0.2, **kwargs):
        class Response:
            status_code = 200
            content = b"x"

            @staticmethod
            def json():
                return {"results": [{"id": "a", "email": "x@y.test"}] * 50}

        return Response()

    original = http_module.request
    http_module.request = always_page_one  # type: ignore[assignment]
    try:
        materializer = engine(catalog, api, pagination={"page_size": 50, "max_pages": 5})
        entry = materializer.status("accounts")["accounts.primary"]
        assert entry["status"] == "error"
        assert "still paginating after 5 pages" in entry["detail"]
    finally:
        http_module.request = original  # type: ignore[assignment]


# ---- previously untested configuration surface ----------------------------


def test_record_key_unwraps_an_enveloped_create_response(write_catalog, api):
    """Some APIs return {"data": {...}}; without `record_key` the identity is invisible."""
    catalog = write_catalog(
        {
            "resources.yaml": "thing:\n  system: rest\n  path: /accounts\n  natural_key: email\n  record_key: data\n",
            "things.yaml": "one:\n  resource: thing\n  body: {email: one@example.test}\n",
        }
    )
    materializer = engine(catalog, api)

    import atf.http as http_module

    original = http_module.request

    def envelope(client, method, url, retries=0, backoff=0.2, **kwargs):
        response = original(client, method, url, retries=retries, backoff=backoff, **kwargs)
        if method != "POST":
            return response

        class Wrapped:
            status_code = response.status_code
            content = response.content

            @staticmethod
            def json():
                return {"data": response.json()}

        return Wrapped()

    http_module.request = envelope  # type: ignore[assignment]
    try:
        assert materializer.ensure("thing", "one")["id"] == "account-1"
    finally:
        http_module.request = original  # type: ignore[assignment]


def test_delete_path_template_is_used(catalog, api):
    materializer = engine(catalog, api)
    record = materializer.ensure("account", "primary")
    node = materializer.node("accounts.primary")
    node["config"]["delete_path"] = "/accounts/{id}"

    materializer.adapters["rest"].delete(node, record, materializer)
    assert f"/accounts/{record['id']}" in api.paths("DELETE")


def test_success_codes_reject_an_unexpected_status(catalog, api):
    materializer = engine(catalog, api, success_codes=[200])  # the stub answers 201
    outcome = materializer.create_closure("accounts.primary")
    assert outcome["results"][0]["ok"] is False
    assert "201" in outcome["results"][0]["detail"]


def test_custom_headers_are_sent(catalog):
    stub = StubAPI(require_header=("X-Tenant", "acme"))
    stub.base_url = stub.start()  # type: ignore[attr-defined]
    try:
        materializer = engine(catalog, stub, headers={"X-Tenant": "acme"})
        assert materializer.ensure("account", "primary")["id"] == "account-1"
    finally:
        stub.stop()


def test_custom_pagination_parameter_names(catalog, api):
    api.paginate = True
    for index in range(120):
        api.seed("accounts", {"id": f"a-{index}", "email": f"user{index}@example.test"})
    api.seed("accounts", {"id": "target", "email": "primary@example.test"})

    materializer = engine(
        catalog,
        api,
        pagination={"results_key": "results", "count_key": "count", "page_size": 25,
                    "limit_param": "limit", "offset_param": "offset"},
    )
    assert materializer.ensure("account", "primary")["id"] == "target"
    assert any("limit=25" in path for path in api.paths("GET"))


def test_a_create_is_never_retried(catalog, api):
    """Retrying a POST that already succeeded would duplicate the record."""
    import atf.http as http_module

    attempts: list[str] = []
    original = http_module.request

    def flaky(client, method, url, retries=0, backoff=0.2, **kwargs):
        attempts.append(method)
        if method == "POST":
            assert retries == 0, "POST must not be retried"

            class Failed:
                status_code = 503
                content = b""
                text = "unavailable"

                @staticmethod
                def json():
                    return {}

            return Failed()
        return original(client, method, url, retries=retries, backoff=backoff, **kwargs)

    http_module.request = flaky  # type: ignore[assignment]
    try:
        materializer = engine(catalog, api, retries=3)
        outcome = materializer.create_closure("accounts.primary")
        assert outcome["results"][0]["ok"] is False
    finally:
        http_module.request = original  # type: ignore[assignment]

    assert attempts.count("POST") == 1


def test_retries_do_apply_to_reads(api):
    """The retry knob is real for idempotent methods."""
    import httpx

    import atf.http as http_module

    calls: list[int] = []

    class Flaky(httpx.BaseTransport):
        def handle_request(self, request):
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(503, json={})
            return httpx.Response(200, json=[])

    client = httpx.Client(transport=Flaky(), base_url="http://stub.invalid")
    response = http_module.request(client, "GET", "/accounts", retries=3, backoff=0.001)
    assert response.status_code == 200
    assert len(calls) == 3
