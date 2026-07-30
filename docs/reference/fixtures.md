# Fixtures reference

One of four pages on the pytest surface `atf.spec.plugin` adds: this one covers the pytest fixtures
the plugin generates, and what happens after a scenario ends. See also
[provisioning](provisioning.md), [acting](acting.md) and [assertions](assertions.md).

## Fixtures {#fixtures}

| Fixture | Scope | Value |
|---|---|---|
| [`context`](#context) | function | An empty `atf.spec.context.Context`, the per-scenario scratchpad. |
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

It behaves exactly like the `types.SimpleNamespace` it used to be — `context.foo = x`,
`context.foo`, `del context.foo`, and an `AttributeError` for anything never set — so no existing
step changes. It additionally *describes* what is set on it:

| Member | Value |
|---|---|
| `values` | Everything a step put here, without ATF's own bookkeeping. |
| `slots` | A `Slot` per attribute: its `name`, `kind`, the `fields` it carries, a `count`, and the `resource_type` it is or looks like. |
| `note(name, …)` | Say what a slot is when the setter knows more than the value shows. The provisioning step uses it. |

A `Slot` never holds a value, only names, kinds and counts. What a scenario was holding when it
finished is reported to the run and kept in [run history](cli.md#atf-import-run) on disk, and a record
carries a token as readily as a title.

Two attribute names mean something to ATF:

- **`result`** — what a step produced. Only a suggested name:
  [any slot can be asserted on](assertions.md#slots) by the name a step gave it. `result` is what a
  suite with one action per scenario will use, and what the cockpit's composer offers first.
- **`_ephemeral`** — the ephemeral resources this scenario built, read by teardown and by an
  assertion on one of them. Attributes starting with `_` are ATF's own and are not described.

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

Deletion is best-effort: failures are logged under the `atf.engine.materializer` logger, never raised. A
test that passed has told you something true, and a broken deletion endpoint should not overturn
that verdict. Persistent resources are left in place.

## `Materializer` {#materializer}

The object behind the [`materializer`](#materializer-fixture) fixture, and the same object adapters
receive as `ctx`.

| Member | Signature | Description |
|---|---|---|
| `catalog` | `Catalog` | What the suite declares: `types`, `nodes`, `find(type, name)`, `spec(type)`, `resource_types`, `of_type(type)`. |
| `nodes` | `dict[str, Node]` | Every catalog node by id. |
| `types` | `dict[str, TypeSpec]` | The type registry. |
| `spec` | `(type) -> TypeSpec` | One resource type. Raises `UnknownResource`. |
| `env` | `str` | The active environment. |
| `reload` | `() -> None` | Re-reads the catalog and clears caches. |
| `resolve_id` | `(type, name) -> str` | The node id for a type and instance name. Raises `UnknownResource`. |
| `ensure` | `(type, name) -> Record` | Provisions the resource and its closure; returns its record. Raises `ProvisioningError` naming the offending node. |
| `ensure_closure` | `(type, name) -> tuple[Record, dict[str, Record]]` | The same, plus every record provisioned on the way — what the generated fixtures use, so ephemerals reached through a dependency can be torn down. |
| `find_existing` | `(node) -> Record \| None` | Looks a node up without creating it. Returns `None` for ephemeral nodes. |
| `status` | `(collection=None) -> Statuses` | Where every node stands. Never raises. |
| `closure` | `(node_id) -> list[str]` | That node plus every transitive dependency. |
| `materialize` | `(subset, keep_going=False) -> ProvisionOutcome` | Provisions an iterable of node ids, and their dependencies, in dependency order. |
| `create_closure` | `(node_id, keep_going=False) -> ProvisionOutcome` | `materialize` over that node and its dependencies. |
| `create_all` | `(keep_going=False) -> ProvisionOutcome` | `materialize` over the whole catalog. |
| `teardown` | `(records) -> None` | Deletes the ephemeral resources among `records`. Never raises. |

`Statuses` maps a node id to a `ResourceStatus` — `state`, `detail`, `identity`, `record`, plus
`present`, `blocking`, `missing` and `tone`. Ask it by id with `of(node_id)`, `state(node_id)` or
`identity(node_id)`: a node it was not asked about reads as `unknown` rather than raising.

`ProvisionOutcome` carries `results`, `records` and `failures`. Each `ProvisionResult` has
`node_id`, `action`, `ok`, `detail`, `record` and `state`, where `action` is one of `created`,
`exists`, `reference`, `observed`, `error`, `unsupported`, `blocked`. A pass stops at the first
failure unless `keep_going`, which instead reports a failure's dependents as `blocked` and continues
with independent subtrees.

`ensure` never continues past a failure: the spec needs that one resource, so there is nothing to
continue toward.

## Exceptions {#exceptions}

| Exception | Module | Raised when |
|---|---|---|
| `ConfigError` | `atf.model.manifest` | The manifest is missing, invalid, or names an unset environment variable. |
| `CatalogError` | `atf.model.catalog` | The catalog fails validation. Carries `.problems`, a list of every problem found. |
| `ProvisioningError` | `atf.engine.materializer` | `ensure` could not provision a resource. Carries `.node_id` and `.detail`. |
| `UnknownResource` | `atf.engine.materializer` | A type and name do not match any node. Subclasses `LookupError`. |
| `Unresolved` | `atf.model.placeholders` | A `${...}` placeholder cannot be resolved. Carries `.expression`. |
| `AuthError` | `atf.adapters.http` | An auth scheme is unknown or incomplete, or a session login failed. |

## Timeouts {#timeouts}

| Operation | Limit | Constant |
|---|---|---|
| Discovery (`pytest --collect-only`) | 300 s | `atf.suite.discovery._COLLECT_TIMEOUT` |
| A synchronous run (`atf run`) | 1800 s | `atf.run.runner.DEFAULT_TIMEOUT` |
| A cockpit background run | 1800 s | `atf.run.jobs.DEFAULT_JOB_TIMEOUT` |

None are settable from the manifest. A run that exceeds its limit is killed, reported as timed out,
and releases the environment's run slot.

## Concurrency {#concurrency}

**Single-worker only.** The session materializer, its listing cache and get-or-create are not safe
under parallel workers: two workers can each find a resource absent and each create it. Do not
enable `pytest-xdist`.

If you need parallelism, split by environment — one worker per environment, never several per
environment. For the same reason, avoid two pipelines provisioning one environment at once.

## Where to go next

- [Provisioning reference](provisioning.md) — what sets `context.<resource_type>` in the first place.
- [Acting reference](acting.md) — steps that write their own slots onto `context`.
- [Assertions reference](assertions.md) — reading a slot or a resource back.
- [Life of a run](../explanation/life-of-a-run.md) — where teardown sits in the sequence.
- [Catalog reference](catalog.md) — the nodes `materializer` resolves against.
