"""Scaffolds a complete consuming project on disk for plugin / discovery / runner / cockpit tests.

Everything is in-process and network-free: the project's own adapter keeps records in a JSON file
next to the manifest, and the system-under-test client reads that same file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MANIFEST = """
catalog: ./catalog
specs: ./specs
default_env: dev

adapters:
  - suite_adapters

mutable_envs: [dev]

# A scenario tagged `@ephemeral` cannot run where the `ephemeral` system is unavailable. Nothing
# reports it unavailable unless a test says so, so this is inert by default.
requires:
  ephemeral: ephemeral

environments:
  dev:
    adapters:
      store:
        path: ./store.json
      ephemeral:
        path: ./store.json
    clients:
      api:
        path: ./store.json
  locked:
    adapters:
      store:
        path: ./store.json
      ephemeral:
        path: ./store.json
    clients:
      api:
        path: ./store.json

display:
  systems:
    store: { label: Store, color: "#2f6be0" }
    ephemeral: { label: Ephemeral, color: "#7857d8" }
"""

TYPES = """
account:
  system: store
  collection: accounts
  natural_key: email
project:
  system: store
  collection: projects
  natural_key: [account_id, slug]
external_widget:
  system: store
  mode: reference
  collection: widgets
  natural_key: name
  ref_field: label
badge:
  system: store
  collection: badges
  natural_key: slug
visitor:
  system: ephemeral
  lifecycle: ephemeral
  collection: visitors
  natural_key: email
"""

CATALOG = {
    "accounts.yaml": """
primary:
  resource: account
  represents: The account every other resource hangs off.
  body:
    email: primary@example.test
    plan: standard
    notes: ""                      # present and empty — what `is empty` is a claim about
secondary:
  resource: account
  represents: A second account used to prove isolation.
  body:
    email: secondary@example.test
    plan: trial
""",
    "projects.yaml": """
alpha:
  resource: project
  represents: A project under the primary account.
  depends_on:
    - accounts.primary
  body:
    slug: alpha
    account_id: ${accounts.primary.id}
""",
    "visitors.yaml": """
walkin:
  resource: visitor
  represents: An anonymous visitor built fresh for each run.
  body:
    email: walkin@example.test
""",
    "badges.yaml": """
welcome:
  resource: badge
  represents: A badge whose owner is ephemeral, so teardown must reach through the dependency.
  depends_on:
    - visitors.walkin
  body:
    slug: welcome
    visitor_id: ${visitors.walkin.id}
""",
    "widgets.yaml": """
imported:
  resource: external_widget
  represents: A widget that must already exist in the environment.
  body:
    name: imported
""",
}

ADAPTERS = '''
"""Project adapters: a JSON-file store and an ephemeral variant with teardown."""

import json
import os
from pathlib import Path

from atf.adapters import register


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def write(self, data):
        self.path.write_text(json.dumps(data, indent=2))

    def collection(self, node):
        return node["config"].get("collection", node["resource"] + "s")


class StoreAdapter(Store):
    def find(self, node, ctx):
        keys = node["config"]["natural_key"]
        keys = [keys] if isinstance(keys, str) else keys
        ref_field = node["config"].get("ref_field")
        criteria = {}
        for key in keys:
            if key not in node["body"]:
                return None
            remote = ref_field if (ref_field and len(keys) == 1) else key
            criteria[remote] = ctx.resolve(node["body"][key])
        for record in self.read().get(self.collection(node), []):
            if all(str(record.get(k)) == str(v) for k, v in criteria.items()):
                return record
        return None

    def create(self, node, body, ctx):
        data = self.read()
        bucket = data.setdefault(self.collection(node), [])
        record = dict(body)
        record[node["id_field"]] = f"{node['resource']}-{len(bucket) + 1}"
        bucket.append(record)
        self.write(data)
        return record

    def delete(self, node, record, ctx):
        data = self.read()
        key = node["id_field"]
        bucket = data.get(self.collection(node), [])
        data[self.collection(node)] = [r for r in bucket if r.get(key) != record.get(key)]
        self.write(data)


class EphemeralAdapter(StoreAdapter):
    """Multi-step provisioning: create, then mark ready. Never reused across runs.

    This one browses and `StoreAdapter` does not, which is the shape a real pair often has: `find`
    answers "is this one there?" and is meaningless here, while "what is there at all?" is exactly
    how you check that teardown left nothing behind.
    """

    def browse(self, node, ctx, limit=200):
        return list(self.read().get(self.collection(node), []))[:limit]

    def unavailable(self):
        """Optional SPI: why this system cannot work here. Driven by the environment, for a test."""
        return os.environ.get("SAMPLE_EPHEMERAL_DOWN", "")

    def find(self, node, ctx):
        return None

    def create(self, node, body, ctx):
        record = super().create(node, body, ctx)
        data = self.read()
        for item in data[self.collection(node)]:
            if item[node["id_field"]] == record[node["id_field"]]:
                item["state"] = "ready"
                record = item
        self.write(data)
        return record


def _resolve(settings, root=None):
    path = Path(settings["path"])
    return path if path.is_absolute() else (Path(__file__).parent / path)


register("store", lambda settings: StoreAdapter(_resolve(settings)))
register("ephemeral", lambda settings: EphemeralAdapter(_resolve(settings)))
'''

CONFTEST = '''
import json
from pathlib import Path

import pytest

pytest_plugins = ["atf.plugin"]

STORE = Path(__file__).parent / "store.json"


@pytest.fixture(scope="session", autouse=True)
def _seed_environment():
    """Stands in for a live environment: the reference widget must already exist."""
    data = json.loads(STORE.read_text()) if STORE.exists() else {}
    data.setdefault("widgets", [])
    if not any(w.get("label") == "imported" for w in data["widgets"]):
        data["widgets"].append({"id": "widget-seed", "label": "imported"})
    STORE.write_text(json.dumps(data, indent=2))


def pytest_collection_modifyitems(items):
    for item in items:
        if "wip" in {mark.name for mark in item.iter_markers()}:
            item.add_marker(pytest.mark.skip(reason="work in progress"))
'''

PYTEST_INI = """[pytest]
markers =
    wip: not ready to run yet
"""

API = '''
"""The system under test, as the specs see it. Reads the same store the adapters write."""

import json
from pathlib import Path

import pytest


class Api:
    def __init__(self, path):
        self.path = Path(path)

    def _data(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def projects_of(self, account):
        return [p for p in self._data().get("projects", []) if p["account_id"] == account["id"]]

    def plan_of(self, account):
        return account["plan"]

    def state_of(self, visitor):
        for record in self._data().get("visitors", []):
            if record["id"] == visitor["id"]:
                return record.get("state")
        return None


@pytest.fixture
def api(client_config):
    settings = dict(client_config["api"])
    path = Path(settings["path"])
    if not path.is_absolute():
        path = Path(__file__).parent.parent / path
    return Api(path)
'''

FEATURE = """Feature: Accounts
  Accounts carry a plan and own projects.

  Scenario: A standard account reports its plan
    Given the account "primary"
    When I read its plan
    Then the plan is "standard"

  Scenario: A project belongs to its account
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the project "alpha" is listed

  Scenario Outline: Accounts report their own plan
    Given the account "<who>"
    When I read its plan
    Then the plan is "<plan>"

    Examples:
      | who       | plan     |
      | primary   | standard |
      | secondary | trial    |

  @wip
  Scenario: A skipped behaviour
    Given the account "primary"
    Then the plan is "standard"
"""

VISITOR_FEATURE = """Feature: Visitors
  Visitors are built fresh for every run and torn down afterwards.

  Scenario: A visitor is ready once provisioned
    Given the visitor "walkin"
    When I read its state
    Then the state is "ready"

  Scenario: A badge is issued to a visitor
    Given the badge "welcome"
    Then the badge has a visitor

  Scenario: A referenced widget is available
    Given the external_widget "imported"
    Then the widget is present
"""

STEPS = '''
from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/accounts.feature")


@when("I read its plan")
def _(context, api):
    context.result = api.plan_of(context.account)


@when("I list the projects of the account")
def _(context, api):
    context.result = api.projects_of(context.account)


@then(parsers.parse('the plan is "{expected}"'))
def _(context, expected):
    assert context.result == expected


@then(parsers.parse('the project "{name}" is listed'))
def _(context, name):
    assert any(p["slug"] == name for p in context.result)
'''

VISITOR_STEPS = '''
from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/visitors.feature")


@when("I read its state")
def _(context, api):
    context.result = api.state_of(context.visitor)


@then(parsers.parse('the state is "{expected}"'))
def _(context, expected):
    assert context.result == expected


@then("the badge has a visitor")
def _(context):
    assert context.badge["visitor_id"]


@then("the widget is present")
def _(context):
    assert context.external_widget["id"]
'''


def write_sample_project(root: Path) -> Path:
    """Write the reference consuming project into `root` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "atf.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "suite_adapters.py").write_text(ADAPTERS, encoding="utf-8")
    (root / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (root / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")

    catalog = root / "catalog"
    catalog.mkdir(exist_ok=True)
    (catalog / "resources.yaml").write_text(TYPES, encoding="utf-8")
    for name, text in CATALOG.items():
        (catalog / name).write_text(text, encoding="utf-8")

    specs = root / "specs"
    features = specs / "features"
    steps = specs / "steps"
    features.mkdir(parents=True, exist_ok=True)
    steps.mkdir(parents=True, exist_ok=True)
    (specs / "api.py").write_text(API, encoding="utf-8")
    (specs / "conftest.py").write_text("from api import api  # noqa: F401\n", encoding="utf-8")
    (features / "accounts.feature").write_text(FEATURE, encoding="utf-8")
    (features / "visitors.feature").write_text(VISITOR_FEATURE, encoding="utf-8")
    (steps / "test_accounts.py").write_text(STEPS, encoding="utf-8")
    (steps / "test_visitors.py").write_text(VISITOR_STEPS, encoding="utf-8")
    return root


def run_pytest(project: Path, *args: str, env: str = "dev") -> subprocess.CompletedProcess[str]:
    """The plugin bootstraps at import, so a suite always runs in its own process."""
    environment = {
        **os.environ,
        "ATF_MANIFEST": str(project / "atf.yaml"),
        "ATF_ENV": env,
        "PYTHONPATH": str(REPO / "src"),
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


def write_spec(project: Path, name: str, feature: str, steps: str = "") -> None:
    """Add one more feature to a sample project, with whatever step code it needs of its own."""
    (project / "specs" / "features" / f"{name}.feature").write_text(feature, encoding="utf-8")
    binding = f'from pytest_bdd import scenarios\n\nscenarios("../features/{name}.feature")\n'
    (project / "specs" / "steps" / f"test_{name}.py").write_text(binding + steps, encoding="utf-8")
