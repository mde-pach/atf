# Adapter SPI reference

`atf.adapters` defines the interface between the provisioning engine and a backend, and the registry
that binds a system name to an implementation.

An adapter is the only part of a suite that knows a particular backend exists. The engine never
branches per system; it calls the three methods below and nothing else.

## `Record` {#record}

```python
Record = dict[str, Any]
```

A backend record. It must carry the resource's identity under the node's
[`id_field`](catalog.md#id_field).

## `Adapter` {#adapter}

A protocol. Any object with these three methods is an adapter; inheritance is not required.

```python
class Adapter(Protocol):
    def find(self, node: Node, ctx: Context) -> Record | None: ...
    def create(self, node: Node, body: Record, ctx: Context) -> Record: ...
    def delete(self, node: Node, record: Record, ctx: Context) -> None: ...
```

### `find(node, ctx)` {#find}

Returns the live record for `node`, or `None` when it does not exist. Called before every create,
and by [`atf status`](cli.md#atf-status).

Idempotency lives here: `find` is what stops a second run creating a duplicate, so it must recognise
what `create` made.

ATF never calls `find` for an ephemeral node — it is short-circuited to `None` before dispatch, so
an adapter serving only ephemeral types may return `None` unconditionally.

An exception is reported as that node's `error` result, which ends the provisioning pass unless
`keep_going` was asked for, and shows as the `error` status in `atf status`. It is never allowed to
crash the command.

### `create(node, body, ctx)` {#create}

Provisions the resource and returns its record. `body` is `node.body` with all `${...}`
placeholders resolved; the returned record must carry the identity under `node.id_field`.

`create` may do whatever it takes — several calls, a polling loop, an SDK. The catalog still treats
the result as one resource. It is not called for `mode: reference` types; a reference resource that
`find` cannot locate is reported as a failure.

### `delete(node, record, ctx)` {#delete}

Removes the resource. Called only for ephemeral resources, at the end of the scenario that created
them, and by `Materializer.teardown`.

Exceptions are logged and swallowed — teardown never fails a run. If nothing you provision is
ephemeral, make this a no-op, but do not omit it.

### `close()` {#close}

Optional. An adapter holding a connection, session or browser may define `close()`; ATF calls it
through `Materializer.close()` when the environment is torn down, and swallows any error.

```python
class QueueAdapter:
    def close(self) -> None:
        self.connection.close()
```

### `act(node, record, action, ctx)` {#act}

Optional. Does to a resource what its type says that action means, and returns the record as it is
afterwards — or `None` when the system says nothing useful.

ATF could always create and delete, because those are what a catalog is for. Everything else a
system can do — complete a task, close an account, retry a job — was a step some project had to
write, including the ones that are one call the adapter already knew how to make.

```python
class QueueAdapter:
    def act(self, node, record, action, ctx):
        declared = node.config["actions"][action]
        return self.client.send(record["id"], **ctx.resolve(declared))
```

The declaration is yours to interpret: it reaches you under `node.config["actions"][action]`, and
ATF has only checked that it is a mapping. An adapter without `act` says so when a scenario reaches
for a declared action, rather than failing obscurely.

`delete` never arrives here — it is in the required SPI, so ATF calls it directly.

### `browse(node, ctx, limit)` {#browse}

Optional. Every record of this type the environment holds. Reachable from a scenario as
`When I list every <type>`, and from the cockpit when writing a catalog from an environment.

### `unavailable()` {#unavailable}

Optional. Returns why this adapter cannot work here, or `""` when it can.

Some systems are not a matter of configuration: a browser adapter needs a browser installed, a
device farm needs the farm reachable. A scenario that needs one should **skip** on a machine
without it — not fail, which reads as a broken suite, and not pass, which is a lie.

```python
class ViewAdapter:
    def unavailable(self) -> str:
        if browser_available():
            return ""
        return "no browser installed — `uv run playwright install chromium`"
```

Say which tag needs the system with [`requires`](manifest.md#requires) in the manifest. The reason
is required, not optional prose: a skip nobody can act on is a skip nobody ever removes. An
exception raised here is itself treated as a reason to skip.

## `Context` {#context}

A protocol describing what the materializer offers an adapter. The object passed as `ctx` is the
`Materializer` itself.

### `env` {#ctx-env}

`str` — the active environment name. Useful in error messages; an adapter that branches on it is
usually a sign the difference belongs in the manifest instead.

### `resolve(value)` {#ctx-resolve}

`(value: Any) -> Any` — resolves `${...}` placeholders in a string, list or mapping. Raises
`atf.model.placeholders.Unresolved` when a referenced identity is unknown.

`create` receives an already-resolved body. `find` does not — it is given only `node`, whose `body`
is raw — so an adapter matching on body fields must resolve them itself.

### `cached(key, loader)` {#ctx-cached}

`(key: str, loader: Callable[[], Any]) -> Any` — returns `loader()` the first time a key is seen and
the memoised value thereafter.

Use it for listings, so a pass touching ten resources of one type fetches the collection once. The
cache is shared across every adapter the materializer drives, so include the backend in the key.

### `invalidate_cache()` {#ctx-invalidate-cache}

`() -> None` — drops every memoised value. Called automatically after each create, so a stale
listing can never be served to the next lookup.

## `AdapterFactory` {#adapterfactory}

```python
AdapterFactory = Callable[[dict[str, Any]], Adapter]
```

Receives the settings for one system in one environment — the mapping at
[`environments.<env>.adapters.<system>`](manifest.md#env-adapters), with `*_env` pointers already
resolved — and returns an adapter. A class whose `__init__` takes that mapping satisfies the type.

Registering a factory rather than an instance is what lets one adapter serve dev, staging and
production with different URLs and credentials.

## The registry {#registry}

Importing `atf.adapters` registers `rest` and `reference`. Project factories are registered when
bootstrap imports the modules named in the manifest's [`adapters`](manifest.md#adapters) list.

### `register(system, factory)` {#register}

Binds a system name to a factory. Re-registering replaces the previous binding.

### `build(system, settings)` {#build}

Calls the registered factory. Raises `KeyError` naming the system and listing those registered.

### `registered_systems()` {#registered_systems}

The registered system names. Catalog validation checks each type's `system` against this set, which
is why an unregistered system is a load error rather than a runtime one.

### `unregister(system)` {#unregister}

Removes a binding. Absent names are ignored.

## `NoopDelete` {#noopdelete}

A mixin supplying a `delete` that does nothing, for backends without deletion.

## The `node` mapping {#node}

Documented in full in the [catalog reference](catalog.md#node-fields). The fields an adapter reads
most often:

| Field | Description |
|---|---|
| `node.id` | `<collection>.<name>`, for error messages. |
| `node.body` | The instance body, **unresolved** — see [`resolve`](#ctx-resolve). |
| `node.config` | Type keys other than `system`, `mode`, `lifecycle` and `id_field`. This is where your adapter's per-type options arrive. |
| `node.id_field` | The field the returned record must carry the identity under. |
| `node.lifecycle` | `persistent` or `ephemeral`. |
| `node.key_criteria(ctx.resolve)` | `{the field the backend spells it as: the value expected there}`, or `None` when the question cannot be asked yet. |

## HTTP helpers {#http-helpers}

`atf.adapters.http` holds the plumbing the built-in adapters use. It is public, and it applies the same auth
schemes the manifest describes — so an adapter building its own client authenticates the same way
the `rest` adapter does.

### `build_client(...)` {#build_client}

`(base_url, auth=None, timeout=30.0, headers=None, verify=True) -> httpx.Client`

A client with the manifest's [auth scheme](manifest.md#auth) applied and redirects followed.

### `request(...)` {#request}

`(client, method, url, retries=0, backoff=0.2, **kwargs) -> httpx.Response`

One request, retrying transport errors and 5xx with exponential backoff. Only idempotent methods are
retried; see [`retries`](manifest.md#retries).

### `list_records(...)` {#list_records}

`(client, url, params=None, pagination=None, retries=0) -> list[dict]`

A whole collection, following offset [pagination](manifest.md#pagination) when configured.

### `SessionAuth` and `AuthError` {#sessionauth}

`SessionAuth` is a public `httpx.Auth` implementing the manifest's
[`session` scheme](manifest.md#auth-session). `AuthError` is raised for an unknown or incomplete
scheme, and for a failed login.

## Minimal implementation {#minimal}

```python
from atf.adapters import register


class ThingAdapter:
    def __init__(self, settings):
        self.client = ThingClient(settings["base_url"])

    def find(self, node, ctx):
        return self.client.get(node.body["name"])

    def create(self, node, body, ctx):
        return self.client.create(**body)

    def delete(self, node, record, ctx):
        self.client.delete(record["id"])


register("thing", ThingAdapter)
```

## Where to go next

- [How to add an adapter](../how-to/add-an-adapter.md) — the same surface, as a recipe.
- [Catalog reference](catalog.md#node-fields) — the node structure and per-type config.
- [Manifest reference](manifest.md#env-adapters) — where a system's settings are declared.
- [Life of a run](../explanation/life-of-a-run.md#find-or-create) — when each method is called.
