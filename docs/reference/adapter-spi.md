# Adapter SPI reference

`atf.adapters` defines the interface between the provisioning engine and a backend, and the registry
that binds a system name to an implementation.

## `Record`

```python
Record = dict[str, Any]
```

A backend record. Carries the resource's identity under the node's `id_field`.

## `Adapter`

A protocol. Any object with these three methods is an adapter; inheritance is not required.

```python
class Adapter(Protocol):
    def find(self, node: Node, ctx: Context) -> Record | None: ...
    def create(self, node: Node, body: Record, ctx: Context) -> Record: ...
    def delete(self, node: Node, record: Record, ctx: Context) -> None: ...
```

### `find(node, ctx)`

Returns the live record for `node`, or `None` when it does not exist. Called before every create,
and by `atf status`.

ATF never calls `find` for an ephemeral node — it is short-circuited to `None` before dispatch, so
an adapter serving only ephemeral types can return `None` unconditionally. Exceptions propagate to
`status` as the `error` state and abort a materialize pass.

### `create(node, body, ctx)`

Provisions the resource and returns its record. `body` is `node["body"]` with all `${...}`
placeholders resolved. The returned record must carry the identity under `node["id_field"]`.

Not called for `mode: reference` types; a reference resource that `find` cannot locate is reported
as a failure.

### `delete(node, record, ctx)`

Removes the resource. Called only for ephemeral resources, at the end of the scenario that created
them, and by `Materializer.teardown`. Exceptions are logged and swallowed — teardown never fails a
run.

## `Context`

A protocol describing what the materializer offers an adapter. The object passed as `ctx` is the
`Materializer` itself.

| Member | Signature | Description |
|---|---|---|
| `env` | `str` | The active environment name. |
| `resolve` | `(value: Any) -> Any` | Resolves `${...}` placeholders in a string, list or mapping. Raises `atf.placeholders.Unresolved` when a referenced identity is unknown. |
| `cached` | `(key: str, loader: Callable[[], Any]) -> Any` | Returns `loader()` the first time a key is seen and the memoised value thereafter. |
| `invalidate_cache` | `() -> None` | Drops every memoised value. Called automatically after each create. |

## `AdapterFactory`

```python
AdapterFactory = Callable[[dict[str, Any]], Adapter]
```

Receives the settings for one system in one environment — the mapping at
`environments.<env>.adapters.<system>`, with `*_env` pointers already resolved — and returns an
adapter. A class whose `__init__` takes that mapping satisfies the type.

## Registry functions

| Function | Signature | Description |
|---|---|---|
| `register` | `(system: str, factory: AdapterFactory) -> None` | Binds a system name to a factory. Re-registering replaces the previous binding. |
| `build` | `(system: str, settings: dict) -> Adapter` | Calls the registered factory. Raises `KeyError` naming the system and listing those registered. |
| `registered_systems` | `() -> set[str]` | The registered system names. Catalog validation checks each type's `system` against this set. |
| `unregister` | `(system: str) -> None` | Removes a binding. Absent names are ignored. |

Importing `atf.adapters` registers `rest` and `reference`. Project factories are registered when
bootstrap imports the modules named in the manifest's `adapters` list.

## Optional `close()`

An adapter holding a connection, session or browser may define `close()`; ATF calls it through
`Materializer.close()` when the environment is torn down, and swallows any error.

```python
class QueueAdapter:
    def close(self) -> None:
        self.connection.close()
```

## `NoopDelete`

A mixin supplying a `delete` that does nothing, for backends without deletion.

## Node

The mapping passed as `node`. Documented in full in the [catalog reference](catalog.md#node-fields).
The fields an adapter reads most often:

| Field | Description |
|---|---|
| `node["id"]` | `<collection>.<name>`, for error messages. |
| `node["body"]` | The instance body, **unresolved** — `find` only receives `node`, so it must call `ctx.resolve()` itself. `create` receives a resolved copy as `body`. |
| `node["config"]` | Type keys other than `system`, `mode`, `lifecycle` and `id_field`. |
| `node["id_field"]` | The field the returned record must carry the identity under. |
| `node["lifecycle"]` | `persistent` or `ephemeral`. |

## HTTP helpers

`atf.http` holds the plumbing the built-in adapters use. It is public and applies the same auth
schemes the manifest describes.

| Function | Signature | Description |
|---|---|---|
| `build_client` | `(base_url, auth=None, timeout=30.0, headers=None, verify=True) -> httpx.Client` | A client with the manifest's auth scheme applied. |
| `request` | `(client, method, url, retries=0, backoff=0.2, **kwargs) -> httpx.Response` | One request, retrying transport errors and 5xx with exponential backoff. |
| `list_records` | `(client, url, params=None, pagination=None, retries=0) -> list[dict]` | A whole collection, following offset pagination when configured. |

`SessionAuth` is a public `httpx.Auth` implementing the manifest's `session` scheme, for adapters
building their own client. `AuthError` is raised for an unknown or incomplete auth scheme.

## Minimal implementation

```python
from atf.adapters import register


class ThingAdapter:
    def __init__(self, settings):
        self.client = ThingClient(settings["base_url"])

    def find(self, node, ctx):
        return self.client.get(node["body"]["name"])

    def create(self, node, body, ctx):
        return self.client.create(**body)

    def delete(self, node, record, ctx):
        self.client.delete(record["id"])


register("thing", ThingAdapter)
```

## See also

- [How to add an adapter](../how-to/add-an-adapter.md).
- [Catalog reference](catalog.md) — the node structure and per-type config.
- [Manifest reference](manifest.md) — where a system's settings are declared.
