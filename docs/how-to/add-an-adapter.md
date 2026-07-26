# How to add an adapter

Teach ATF to provision resources in a system the built-in adapters cannot reach — a queue, a
database, an SDK, or an API whose creation flow takes more than one call.

If your backend is a JSON API, try configuring the built-in `rest` adapter first — see the
[manifest reference](../reference/manifest.md). Write an adapter when the *how* cannot be expressed
as configuration.

## Write the class

An adapter is any object with three methods. Put it in a module of your own — `adapters.py` at the
root of your suite is the convention:

```python
from atf.adapters import register


class QueueAdapter:
    def __init__(self, settings):
        self.client = QueueClient(settings["broker_url"], token=settings["token"])

    def find(self, node, ctx):
        found = self.client.describe(node["body"]["name"])
        return found or None

    def create(self, node, body, ctx):
        return self.client.declare(**body)

    def delete(self, node, record, ctx):
        self.client.remove(record["id"])
```

What each method owes the engine:

- **`find`** returns the live record, or `None` if it does not exist. ATF calls this before every
  create, so idempotency lives here.
- **`create`** provisions the resource and returns its record. The `body` you receive already has
  its `${...}` placeholders resolved.
- **`delete`** removes it. Only ephemeral resources are torn down, so if nothing you provision is
  ephemeral, make this a no-op — but do not omit it.

The record you return must carry the resource's identity under the node's `id_field` (`id` unless
the type says otherwise). That is what other resources interpolate with `${…​.id}`.

## Register a factory

Register a **factory**, not an instance — ATF calls it with the settings for whichever environment
is active, so one adapter serves dev, staging and production:

```python
register("queue", QueueAdapter)
```

Any callable taking a settings dict works. Use a function when construction needs more than the
class does:

```python
def _build(settings):
    return QueueAdapter(_resolve_broker(settings), retries=settings.get("retries", 3))


register("queue", _build)
```

## Wire it up

Name the module in your manifest so ATF imports it at startup, and give the system its settings per
environment:

```yaml
adapters:
  - adapters                      # the dotted module path, imported for its register() call

environments:
  dev:
    adapters:
      queue:
        broker_url: amqp://localhost
        token_env: QUEUE_TOKEN    # `*_env` reads an environment variable — never inline a secret
```

Then point a resource type at it:

```yaml
work_queue:
  system: queue
  name_prefix: test
```

Every key in the type except `system`, `mode`, `lifecycle` and `id_field` arrives on the node as
`node["config"]`, so `node["config"]["name_prefix"]` is how your adapter reads per-type options.

## Check it

```sh
atf status dev
```

If the system has no registered adapter, the catalog refuses to load and names it. If the adapter
raises while looking something up, that resource shows as `error` with the message — status never
crashes the command.

Then provision one for real:

```sh
atf seed dev --type work_queue --name main
```

Run it twice. The second run must report `exists`, not `created` — if it reports `created` both
times, `find` is not recognising what `create` made.

## Multi-step provisioning

If creating the resource means several calls — sign up, then activate, then wait for a downstream
system to catch up — put the whole chain in `create`. That is what the seam is for:

```python
    def create(self, node, body, ctx):
        record = self.client.sign_up(**body)
        self.client.activate(record["id"])
        return self._await_ready(record["id"])
```

The catalog still treats it as one resource, so specs say `Given the guest "visitor"` and know
nothing about the three calls. Resources built this way are usually ephemeral — see
[About lifecycles](../explanation/lifecycles.md). There is a worked example in
`examples/todo/adapters.py`.

## Reuse the materializer's cache

If your backend lists records, memoise the listing so a scenario touching ten resources does not
fetch it ten times. The `ctx` argument gives you the cache:

```python
    def find(self, node, ctx):
        records = ctx.cached("queues", self.client.list_queues)
        return next((r for r in records if r["name"] == node["body"]["name"]), None)
```

ATF invalidates the cache after every create, so you cannot serve a stale listing to the next
lookup. Ignore `ctx` entirely if you do not need it.

For the exact protocol — every method signature, the `Node` fields, and what `ctx` offers — see the
[adapter SPI reference](../reference/adapter-spi.md).
