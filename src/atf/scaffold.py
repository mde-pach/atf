"""Templates written by `atf init` (§15)."""

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
        base_url: https://dev.example.com
        # Secrets are pointers, never literals: `*_env` names an environment variable.
        auth: { header: X-Actor, value_env: ATF_ACTOR }
        # pagination: { results_key: results, count_key: count }
        timeout: 30
    clients:
      api:
        base_url: https://dev.example.com
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
"""Custom adapters for this suite.

Register a factory per system; `bootstrap` imports this module and hands each factory the
environment's settings from the manifest. Delete this file if the built-in `rest` and
`reference` adapters cover everything.
"""

from typing import Any

from atf.adapters import Context, Record, register
from atf.catalog import Node


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
"""

README = """\
# {name}

An ATF suite. The catalog declares the resources specs need; ATF makes them exist before a
test runs.

```sh
export ATF_ACTOR=...          # whatever your manifest's *_env pointers name
atf status dev                # what exists in the environment
atf seed dev                  # make the absent resources exist
atf run                       # run the specs (nonzero exit on failure — use this as a CI guard)
atf serve                     # the cockpit, on http://127.0.0.1:8000
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
