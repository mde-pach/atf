# Specs and fixtures reference

`atf.plugin` is a pytest plugin. It is enabled from a `conftest.py` at the root of a suite:

```python
pytest_plugins = ["atf.plugin"]
```

At import it loads the manifest, builds the adapters for the active environment, and loads the
catalog. A configuration or catalog error therefore surfaces during collection.

## The provisioning step

```gherkin
Given the <resource_type> "<name>"
```

Provisions the named resource and everything it transitively depends on (its *dependency closure*),
and assigns the resulting record to `context.<resource_type>`.

`Given the account "primary"` sets `context.account`. A scenario may provision any number of
resources; each lands under its own type name.

The step is matched by `parsers.parse('the {resource_type} "{name}"')`. A `resource_type` that is
not in the catalog fails the test, listing the known types. A `name` with no matching instance
raises `UnknownResource`.

In a `Scenario Outline`, pytest-bdd substitutes `<placeholders>` from the `Examples` table before the
step is matched, so `Given the account "<who>"` receives the concrete name.

Ephemeral resources provisioned by this step are recorded on `context._ephemeral` and deleted when
the scenario ends.

## Background

`Background:` steps run before every scenario in the feature, and ATF treats them as part of each
scenario: the resources they name are that scenario's resources, and they appear in the cockpit's
Gherkin, graph and coverage figures.

```gherkin
Feature: Lists
  Background:
    Given the account "primary"

  Scenario: A list belongs to its account
    Given the todo_list "groceries"
    Then the list belongs to the account
```

Both scenarios in such a feature exercise `accounts.primary`.

## Tags

Scenario tags are available as pytest markers. Two are read by ATF itself:

| Tag | Effect |
|---|---|
| `@skip` | The spec is reported as skipped and listed under the cockpit's coverage gaps. |
| `@wip` | The same. |

Neither tag skips the test on its own — pytest does not know them until you register the marker and
act on it. To actually skip, add a hook in your `conftest.py`:

```python
def pytest_collection_modifyitems(items):
    for item in items:
        if "wip" in {mark.name for mark in item.iter_markers()}:
            item.add_marker(pytest.mark.skip(reason="work in progress"))
```

## Fixtures

| Fixture | Scope | Value |
|---|---|---|
| `context` | function | An empty `SimpleNamespace`, the per-scenario scratchpad. |
| `<resource_type>` | function | `Callable[[str], Record]` — provisions that type by instance name. One is generated per type in the catalog. |
| `materializer` | session | The `Materializer` for the active environment. |
| `env` | session | The active environment name. |
| `client_config` | function | `environments.<env>.clients` from the manifest, with `*_env` pointers resolved. |

A generated factory calls `materializer.ensure(type, name)`, so it may be used directly in a plain
pytest test:

```python
def test_plan(account):
    assert account("primary")["plan"] == "standard"
```

Type names are validated against reserved fixture names when the catalog loads; see the
[catalog reference](catalog.md#resourcesyaml).

## `context`

State passes between steps only through `context`. ATF sets `context.<resource_type>` for each
provisioned resource and `context._ephemeral` for teardown; every other attribute belongs to the
suite.

The record assigned is whatever the adapter returned. Its field names are the suite's contract with
its own backend — ATF neither defines nor validates them.

## `client_config`

The mapping under `environments.<env>.clients`. ATF does not interpret it; a suite's own fixture
consumes it:

```python
@pytest.fixture
def api(client_config):
    return MyClient(**client_config["api"])
```

For that fixture to be visible to specs, import it in a `conftest.py` beside them.

## Teardown

An autouse, function-scoped fixture calls `materializer.teardown(context._ephemeral)` after every
test. Deletion is best-effort: failures are logged, never raised. Persistent resources are left in
place.

## `Materializer`

The object behind the `materializer` fixture.

| Member | Signature | Description |
|---|---|---|
| `nodes` | `dict[str, Node]` | Every catalog node by id. |
| `types` | `dict[str, dict]` | The type registry. |
| `env` | `str` | The active environment. |
| `reload` | `() -> None` | Re-reads the catalog and clears caches. |
| `resolve_id` | `(type, name) -> str` | The node id for a type and instance name. Raises `UnknownResource`. |
| `ensure` | `(type, name) -> Record` | Provisions the resource and its closure; returns its record. Raises `ProvisioningError` naming the offending node on failure. |
| `find_existing` | `(node) -> Record \| None` | Looks a node up without creating it. Returns `None` for ephemeral nodes. |
| `status` | `(collection=None) -> dict[str, dict]` | Per-node `{status, detail, identity?}`. Never raises. |
| `materialize` | `(subset, keep_going=False) -> dict` | Provisions an iterable of node ids, and their dependencies, in dependency order. Returns `{"results": [...], "records": {...}}`. Stops at the first failure unless `keep_going`, which instead reports a failure's dependents as `blocked` and continues with independent ones. |
| `create_closure` | `(node_id, keep_going=False) -> dict` | `materialize` over that node and its dependencies. |
| `create_all` | `(keep_going=False) -> dict` | `materialize` over the whole catalog. |
| `teardown` | `(records) -> None` | Deletes the ephemeral resources among `records`. Never raises. |

`materialize` results are `{"id", "action", "ok"}` with `"detail"` when `ok` is `False`. `action` is
one of `created`, `exists`, `reference`, `error`, `unsupported`, `blocked`.

`ensure` never continues past a failure: the spec needs that one resource, so there is nothing to
continue toward.

## Exceptions

| Exception | Module | Raised when |
|---|---|---|
| `ConfigError` | `atf.config` | The manifest is missing, invalid, or names an unset environment variable. |
| `CatalogError` | `atf.catalog` | The catalog fails validation. Carries `.problems`, a list of every problem found. |
| `ProvisioningError` | `atf.materializer` | `ensure` could not provision a resource. Carries `.node_id` and `.detail`. |
| `UnknownResource` | `atf.materializer` | A type and name do not match any node. Subclasses `LookupError`. |
| `Unresolved` | `atf.placeholders` | A `${...}` placeholder cannot be resolved. Carries `.expression`. |
| `AuthError` | `atf.http` | An auth scheme is unknown or incomplete, or a session login failed. |

## Timeouts

| Operation | Limit | Constant |
|---|---|---|
| Discovery (`pytest --collect-only`) | 300 s | `atf.discovery._COLLECT_TIMEOUT` |
| A synchronous run (`atf run`) | 1800 s | `atf.runner.DEFAULT_TIMEOUT` |
| A cockpit background run | 1800 s | `atf.jobs.DEFAULT_JOB_TIMEOUT` |

None are settable from the manifest. A run that exceeds its limit is killed, reported as timed out,
and releases the environment's run slot.

## Concurrency

Single-worker only. The session materializer, its listing cache and get-or-create are not safe under
parallel workers; `pytest-xdist` is unsupported.

## See also

- [Write your first spec](../tutorial/write-your-first-spec.md).
- [Catalog reference](catalog.md).
- [About the model](../explanation/the-model.md) — how resources, specs, tests and fixtures relate.
