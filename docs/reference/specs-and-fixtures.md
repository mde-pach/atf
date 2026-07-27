# Specs and fixtures reference

`atf.plugin` is a pytest plugin. It is enabled from a `conftest.py` at the root of a suite — pytest
only honours `pytest_plugins` there:

```python
pytest_plugins = ["atf.plugin"]
```

At import it loads the manifest, builds the adapters for the active environment, and loads the
catalog. A configuration or catalog error therefore surfaces during **collection**, not as a failing
test. See [Life of a run](../explanation/life-of-a-run.md#collect).

## The provisioning step {#the-provisioning-step}

```gherkin
Given the <resource_type> "<name>"
```

Provisions the named resource and its whole [closure](../explanation/glossary.md#closure), and
assigns the resulting record to `context.<resource_type>`.

`Given the account "primary"` sets `context.account`. A scenario may provision any number of
resources; each lands under its own type name.

There is one such step, not one per type: it is matched by
`parsers.parse('the {resource_type} "{name}"')`, with the type captured as a parameter. A
`resource_type` that is not in the catalog fails the test and lists the known types. A `name` with
no matching instance raises `UnknownResource`.

Ephemeral resources provisioned by this step are recorded on `context._ephemeral` and deleted when
the scenario ends.

### Scenario Outlines {#scenario-outlines}

pytest-bdd substitutes `<placeholders>` from the `Examples` table before the step is matched, so
`Given the account "<who>"` receives the concrete name and each row becomes its own test.

### Background {#background}

`Background:` steps run before every scenario in the feature, and ATF treats them as part of each
scenario: the resources they name are that scenario's resources, they appear in the cockpit's
Gherkin, and they count towards its [readiness](cockpit.md#readiness).

```gherkin
Feature: Lists
  Background:
    Given the account "primary"

  Scenario: A list belongs to its account
    Given the todo_list "groceries"
    Then the list belongs to the account
```

Every scenario in such a feature exercises `accounts.primary`.

### Tags {#tags}

Scenario tags are available as pytest markers. Two are read by ATF itself:

| Tag | Effect |
|---|---|
| `@skip` | The scenario's state becomes `skipped`, and it is listed under the cockpit's [gaps](cockpit.md#overview-gaps). |
| `@wip` | The same. |

Neither tag skips the test on its own — pytest does not know them until you register the marker and
act on it. To actually skip, add a hook in your `conftest.py`:

```python
def pytest_collection_modifyitems(items):
    for item in items:
        if "wip" in {mark.name for mark in item.iter_markers()}:
            item.add_marker(pytest.mark.skip(reason="work in progress"))
```

## Fixtures {#fixtures}

| Fixture | Scope | Value |
|---|---|---|
| [`context`](#context) | function | An empty `SimpleNamespace`, the per-scenario scratchpad. |
| [`<resource_type>`](#resource-type-fixtures) | function | `Callable[[str], Record]` — provisions that type by instance name. |
| [`materializer`](#materializer-fixture) | session | The `Materializer` for the active environment. |
| [`env`](#env) | session | The active environment name. |
| [`client_config`](#client_config) | function | `environments.<env>.clients`, with `*_env` pointers resolved. |

Everything else in a suite is your own. Type names are validated against these names when the
catalog loads; see [reserved type names](catalog.md#reserved-names).

### `context` {#context}

The per-scenario scratchpad, and the only channel between steps. ATF sets
`context.<resource_type>` for each provisioned resource and `context._ephemeral` for teardown; every
other attribute belongs to your suite.

The record assigned is whatever the adapter returned, untouched. Its field names are the suite's
contract with its own backend — ATF neither defines nor validates them.

### `<resource_type>` {#resource-type-fixtures}

One fixture is generated per type in the catalog, named after the type. It is a callable taking an
instance name and returning that resource's record, provisioning the closure if needed and tracking
any ephemeral resources it created for teardown.

Because it is an ordinary fixture, it works in a plain pytest test as well as behind a Gherkin step:

```python
def test_plan(account):
    assert account("primary")["plan"] == "standard"
```

### `materializer` {#materializer-fixture}

The [provisioning engine](#materializer) for the active environment, session-scoped. Reach for it
when you need something the generic step does not express — provisioning inside a `When`, or reading
status.

### `env` {#env}

The active environment name: `ATF_ENV` if set, else the manifest's `default_env`. Useful for a step
that must behave differently against staging, though needing it often means the difference belongs
in the manifest instead.

### `client_config` {#client_config}

The mapping under `environments.<env>.clients`, with `*_env` pointers resolved. ATF does not
interpret it; your own fixture consumes it:

```python
@pytest.fixture
def api(client_config):
    return MyClient(**client_config["api"])
```

For that fixture to be visible to specs, import it in a `conftest.py` at or above the specs
directory.

## Teardown {#teardown}

An autouse, function-scoped fixture calls `materializer.teardown(context._ephemeral)` after every
test.

Deletion is best-effort: failures are logged under the `atf.materializer` logger, never raised. A
test that passed has told you something true, and a broken deletion endpoint should not overturn
that verdict. Persistent resources are left in place.

## `Materializer` {#materializer}

The object behind the [`materializer`](#materializer-fixture) fixture, and the same object adapters
receive as `ctx`.

| Member | Signature | Description |
|---|---|---|
| `nodes` | `dict[str, Node]` | Every catalog node by id. |
| `types` | `dict[str, dict]` | The type registry. |
| `env` | `str` | The active environment. |
| `reload` | `() -> None` | Re-reads the catalog and clears caches. |
| `resolve_id` | `(type, name) -> str` | The node id for a type and instance name. Raises `UnknownResource`. |
| `ensure` | `(type, name) -> Record` | Provisions the resource and its closure; returns its record. Raises `ProvisioningError` naming the offending node. |
| `ensure_closure` | `(type, name) -> tuple[Record, dict[str, Record]]` | The same, plus every record provisioned on the way — what the generated fixtures use, so ephemerals reached through a dependency can be torn down. |
| `find_existing` | `(node) -> Record \| None` | Looks a node up without creating it. Returns `None` for ephemeral nodes. |
| `status` | `(collection=None) -> dict[str, dict]` | Per-node `{status, detail, identity?}`. Never raises. |
| `closure` | `(node_id) -> list[str]` | That node plus every transitive dependency. |
| `materialize` | `(subset, keep_going=False) -> dict` | Provisions an iterable of node ids, and their dependencies, in dependency order. Returns `{"results": [...], "records": {...}}`. |
| `create_closure` | `(node_id, keep_going=False) -> dict` | `materialize` over that node and its dependencies. |
| `create_all` | `(keep_going=False) -> dict` | `materialize` over the whole catalog. |
| `teardown` | `(records) -> None` | Deletes the ephemeral resources among `records`. Never raises. |

`materialize` results are `{"id", "action", "ok"}` with `"detail"` when `ok` is `False`. `action` is
one of `created`, `exists`, `reference`, `error`, `unsupported`, `blocked`. It stops at the first
failure unless `keep_going`, which instead reports a failure's dependents as `blocked` and continues
with independent subtrees.

`ensure` never continues past a failure: the spec needs that one resource, so there is nothing to
continue toward.

## Exceptions {#exceptions}

| Exception | Module | Raised when |
|---|---|---|
| `ConfigError` | `atf.config` | The manifest is missing, invalid, or names an unset environment variable. |
| `CatalogError` | `atf.catalog` | The catalog fails validation. Carries `.problems`, a list of every problem found. |
| `ProvisioningError` | `atf.materializer` | `ensure` could not provision a resource. Carries `.node_id` and `.detail`. |
| `UnknownResource` | `atf.materializer` | A type and name do not match any node. Subclasses `LookupError`. |
| `Unresolved` | `atf.placeholders` | A `${...}` placeholder cannot be resolved. Carries `.expression`. |
| `AuthError` | `atf.http` | An auth scheme is unknown or incomplete, or a session login failed. |

## Timeouts {#timeouts}

| Operation | Limit | Constant |
|---|---|---|
| Discovery (`pytest --collect-only`) | 300 s | `atf.discovery._COLLECT_TIMEOUT` |
| A synchronous run (`atf run`) | 1800 s | `atf.runner.DEFAULT_TIMEOUT` |
| A cockpit background run | 1800 s | `atf.jobs.DEFAULT_JOB_TIMEOUT` |

None are settable from the manifest. A run that exceeds its limit is killed, reported as timed out,
and releases the environment's run slot.

## Concurrency {#concurrency}

**Single-worker only.** The session materializer, its listing cache and get-or-create are not safe
under parallel workers: two workers can each find a resource absent and each create it. Do not
enable `pytest-xdist`.

If you need parallelism, split by environment — one worker per environment, never several per
environment. For the same reason, avoid two pipelines provisioning one environment at once.

## Where to go next

- [How to add a scenario](../how-to/add-a-scenario.md) — this surface, used.
- [Life of a run](../explanation/life-of-a-run.md) — what the provisioning step sets in motion.
- [Catalog reference](catalog.md) — the nodes the step resolves against.
- [About the model](../explanation/the-model.md) — why resources, specs, tests and fixtures are
  separate things.
