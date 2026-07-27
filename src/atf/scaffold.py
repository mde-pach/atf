"""The file templates `atf init` writes into a new suite."""

from __future__ import annotations

from pathlib import Path

MANIFEST = """\
catalog: ./catalog
specs: ./specs
default_env: dev

# Dotted modules imported for their `register()` side-effects.
adapters:
  - adapters

# Only these environments may be seeded, created into or run from the cockpit.
mutable_envs: [dev]

environments:
  dev:
    adapters:
      rest:
        # Hosts and secrets are pointers, never literals: `*_env` names an environment variable.
        # Until ATF_URL points at a real service, `adapters.py` stands one in.
        base_url_env: ATF_URL
        auth: { header: X-Actor, value_env: ATF_ACTOR }
        # pagination: { results_key: results, count_key: count }
        timeout: 30
    clients:
      api:
        base_url_env: ATF_URL
        auth: { header: X-Actor, value_env: ATF_ACTOR }

display:
  systems:
    rest: { label: API, color: "#2f6be0" }
"""

RESOURCES = """\
# The resource-type registry. Universal keys: system, mode, lifecycle, id_field.
# Everything else is passed to that system's adapter as `config`.

account:
  system: rest
  path: /accounts
  natural_key: email

project:
  system: rest
  path: /projects
  natural_key: [account_id, slug]
"""

ACCOUNTS = """\
primary:
  resource: account
  represents: The account the rest of the catalog hangs off.
  body:
    email: primary@example.com
"""

PROJECTS = """\
alpha:
  resource: project
  represents: A project under the primary account.
  depends_on:
    - accounts.primary
  body:
    slug: alpha
    account_id: ${accounts.primary.id}
"""

ADAPTERS = '''\
"""Custom adapters for this suite — and, until you have a backend, a stand-in for one.

Register a factory per system; `bootstrap` imports this module and hands each factory the
environment's settings from the manifest. The built-in `rest` and `reference` adapters cover
most catalogs: write one of your own when a resource takes more than a POST to exist.
"""

import os
import sys
from pathlib import Path
from typing import Any

from atf.adapters import Context, Record, register
from atf.catalog import Node

# ATF imports this module before it resolves the manifest's `*_env` pointers, so it is the one
# place that can stand a backend up for every entry point alike — `atf run`, `atf status`,
# `atf seed`, `atf serve`. Point ATF_URL at a real service and none of this runs.
if not os.environ.get("ATF_URL"):
    sys.path.insert(0, str(Path(__file__).parent))
    from fake_backend import FakeAPI

    os.environ.setdefault("ATF_ACTOR", "local")
    os.environ["ATF_URL"] = FakeAPI().start()
    print(f"no ATF_URL set — serving a stand-in API on {os.environ['ATF_URL']}")


class ExampleAdapter:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    def find(self, node: Node, ctx: Context) -> Record | None:
        """Return the live record, or None when it does not exist."""
        return None

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        """Provision it. `body` already has its ${...} placeholders resolved."""
        raise NotImplementedError

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        """Best-effort teardown; used for ephemeral resources."""


# register("example", ExampleAdapter)
'''

FAKE_BACKEND = '''\
"""A stand-in backend, so the suite runs before you have a service to point it at.

Collections are whatever you ask for: `POST /accounts` creates one and gives it an id,
`GET /accounts?email=...` lists them filtered by any query parameter, `DELETE /accounts/{id}`
removes it. In memory, loopback only, gone when the process exits. Delete this file — and the
block at the top of `adapters.py` — once ATF_URL names something real.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

ACTOR_HEADER = "X-Actor"


class FakeAPI:
    def __init__(self) -> None:
        self.data: dict[str, list[dict[str, Any]]] = {}
        self.counter = 0

    def start(self, port: int = 0) -> str:
        """Serve on a background thread and return the base URL."""
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                api.handle(self, "GET")

            def do_POST(self) -> None:
                api.handle(self, "POST")

            def do_DELETE(self) -> None:
                api.handle(self, "DELETE")

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        host, bound = server.server_address[0], server.server_address[1]
        return f"http://{host}:{bound}"

    def handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parsed = urlparse(handler.path)
        parts = [part for part in parsed.path.split("/") if part]
        # Any value will do — the point is that the manifest's auth pointer reaches the backend.
        if not handler.headers.get(ACTOR_HEADER):
            return send(handler, 401, {"detail": f"{ACTOR_HEADER} header required"})
        if not parts:
            return send(handler, 404, {"detail": "no route"})

        records = self.data.setdefault(parts[0], [])
        if method == "GET" and len(parts) == 1:
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            matching = [item for item in records if all(str(item.get(k)) == v for k, v in query.items())]
            return send(handler, 200, matching)
        if method == "POST" and len(parts) == 1:
            self.counter += 1
            record = {**body(handler), "id": f"{parts[0][:3]}-{self.counter}"}
            records.append(record)
            return send(handler, 201, record)
        if method == "DELETE" and len(parts) == 2:
            self.data[parts[0]] = [item for item in records if str(item.get("id")) != parts[1]]
            return send(handler, 204, None)
        send(handler, 404, {"detail": "no route"})


def body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    payload = json.loads(handler.rfile.read(length)) if length else {}
    return payload if isinstance(payload, dict) else {}


def send(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    raw = b"" if payload is None else json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    if raw:
        handler.wfile.write(raw)
'''

CONFTEST = """\
pytest_plugins = ["atf.plugin"]
"""

SPECS_CONFTEST = """\
from api import api  # noqa: F401  — makes the SUT client fixture available to every spec
"""

API = '''\
"""The system under test, as the specs see it."""

import httpx
import pytest


class Api:
    def __init__(self, base_url: str, auth: dict | None = None) -> None:
        headers = {auth["header"]: auth["value"]} if auth and "header" in auth else {}
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=30)

    def projects_of(self, account: dict) -> list[dict]:
        response = self.http.get("/projects", params={"account_id": account["id"]})
        response.raise_for_status()
        return response.json()


@pytest.fixture
def api(client_config):
    """The SUT client. Its base URL and auth come from `environments.<env>.clients.api`."""
    return Api(**client_config["api"])
'''

FEATURE = """\
Feature: Accounts
  An account owns the projects created under it.

  Scenario: A project belongs to its account
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the project "alpha" is listed
"""

STEPS = '''\
from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/accounts.feature")

# `Given the <type> "<name>"` is provided by ATF. Everything below is your vocabulary:
# each step reads its subject from `context` and writes the outcome back.


@when("I list the projects of the account")
def _(context, api):
    context.result = api.projects_of(context.account)


@then(parsers.parse('the project "{name}" is listed'))
def _(context, name):
    assert any(project["slug"] == name for project in context.result)
'''

GITIGNORE = """\
__pycache__/
.pytest_cache/
.report.json
.atf/
"""

README = """\
# {name}

An ATF suite. The catalog declares the resources specs need; ATF makes them exist before a
test runs.

```sh
atf run                       # run the specs (nonzero exit on failure — use this as a CI guard)
atf serve                     # the cockpit, on http://127.0.0.1:8000
atf status dev                # what exists in the environment
atf seed dev                  # make the absent resources exist
```

That works as it stands: with `ATF_URL` unset, `adapters.py` starts `fake_backend.py` in process, so
the suite runs against a stand-in backend. Point it at the real thing when you have one — the
stand-in then never starts, and you can delete it:

```sh
export ATF_URL=https://dev.example.com
export ATF_ACTOR=...          # every other *_env pointer in atf.yaml wants one too
```

## Adding things

- **A resource** — a node in `catalog/*.yaml`, plus its type in `catalog/resources.yaml`.
- **A spec** — a `Scenario` in `specs/features/*.feature`, bound by `scenarios(...)` in a
  `specs/steps/test_*.py` module.
- **A behaviour** — one `When`/`Then` in that steps module.

Tests and fixtures follow automatically: each resource type becomes a pytest fixture, and
`Given the <type> "<name>"` provisions any resource in the catalog.
"""


def scaffold(root: Path, name: str) -> list[Path]:
    """Write a new consuming project. Never overwrites an existing file."""
    files = {
        "atf.yaml": MANIFEST,
        "catalog/resources.yaml": RESOURCES,
        "catalog/accounts.yaml": ACCOUNTS,
        "catalog/projects.yaml": PROJECTS,
        "adapters.py": ADAPTERS,
        "fake_backend.py": FAKE_BACKEND,
        "conftest.py": CONFTEST,
        "specs/conftest.py": SPECS_CONFTEST,
        "specs/api.py": API,
        "specs/features/accounts.feature": FEATURE,
        "specs/steps/test_accounts.py": STEPS,
        ".gitignore": GITIGNORE,
        "README.md": README.format(name=name),
    }

    written: list[Path] = []
    for relative, content in files.items():
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
