# Teach ATF a new system

Write a [driver](../reference/arrange.md#driver) and an [adapter](../reference/arrange.md#adapter) so
resources can live in a system ATF does not ship for — a cache, a queue, a service with its own
protocol. The driver holds the machinery and the environment's settings. The adapter is one *kind of
thing* made through it, and answers up to four questions: is it there, make it, change it, remove it.
Only the first is required.

**Name the adapter after the thing, never after the technology.** `file`, `directory` and `tree` are
three adapters over one `filesystem` driver, because a file and a directory do not answer the same
questions.

You have been using both since the first page. ATF ships `@filesystem.file`, `@filesystem.directory`, `@filesystem.tree`, `@browser.page`,
`@shell.process`, `@http.record` and `@sql.row`, over the `filesystem`, `browser`, `shell`, `process`, `http` and
`sql` drivers — and nothing that binds it to a database. `@sql.row`, the decorator on every
declaration in these guides, is written in the suite that uses it. Here is the file.

## The shortest path

**Go through the thing's own interface, not behind its back.** The suite this documentation uses
tests a todo app, and its adapter calls the application's own API — the same one the product's
command line calls — so arranging a resource exercises the code that makes one.

```python
# adapters/todo.py
from typing import TypedDict

from todo import Todo                       # the product under test

from atf import adapter, driver


@driver("todo")
class App:
    """The machinery: the application, opened once per environment."""

    class Settings(TypedDict):              # what atf.yaml supplies under `todo:`
        path: str

    def __init__(self, settings: Settings):
        self.app = Todo(settings["path"])


@adapter("owner", driver="todo")
class Owners:
    """One kind of thing. Registered `todo.owner`, and said as `@todo.owner(...)`."""

    recognised_by = ("email",)              # an owner is its email; a declaration says nothing

    def __init__(self, todo: App):          # the driver, asked for by name
        self.app = todo.app

    def find(self, resource):
        return self.app.find_owner(resource.identity["email"])

    def create(self, resource):
        return self.app.create_owner(resource.values["email"])

    def delete(self, resource, found):
        self.app.delete_owner(found["email"])


@adapter("list", driver="todo")
class Lists:
    """A list carries nothing but its identity, so there is no `update` to write."""

    recognised_by = ("slug",)

    def __init__(self, todo: App):
        self.app = todo.app

    def find(self, resource):
        return self.app.find_list(resource.identity["slug"])

    def create(self, resource):
        """The owner arrives already made, as the key it was made under."""
        owner = resource.parents.get("owner")
        return self.app.create_list(owner.key if owner else None, resource.values["slug"])

    def delete(self, resource, found):
        self.app.delete_list(found["slug"])

    def browse(self, resource):
        return self.app.every_list()
```

```yaml
environments:
  local:
    todo: { path: ./todo.db }
```

```python
# resources.py
from adapters.todo import todo


@todo.owner()
class Owner:
    email: str


@todo.list(depends_on=[Owner])
class TodoList:
    slug: str
```

That is the whole of it. Provisioning an owner, writing a list's owner, tearing a guest down — all
of it is those methods over an API you already have.

**Reach for `@sql.row` only where a thing has no interface of its own.** ATF ships it, and it writes
rows directly; that is the bottom of the stack, not the normal case.

Four things in there are the contract, and each is one line to get wrong.

- **`resource`** carries `.kind`, `.name`, `.options`, `.identity` — the
  [recognition](../reference/arrange.md#recognition) fields and their values — `.values`, the
  declared scalars, and `.parents`, the lineage as `{field: Parent(kind, key)}` where `key` is what
  that parent was made as. **An adapter never looks a parent up again**, and never imports anything
  of ATF's to read a resource.
- **`recognised_by`** is the adapter's answer to what identifies one of these. Declare it where
  there is only one answer — an owner is its email — and a declaration then writes no `unique_by`.
  Leave it out where the suite must choose, as `@sql.row` does: a row could be any column.
- **`changes`** is a mapping ATF computed. The adapter never diffs; it applies what it is handed. That
  is what lets `atf make --dry-run` and the editor show a pending update before it runs.
- **`find` returns `None` for absent** and raises `atf.Unreachable` when the system did not answer at
  all. Nothing else can tell a missing row from a dead server.
- **`delete` must tolerate a record that is already gone.** Function-scoped teardown runs after a test
  that may itself have removed it.

**Options are the adapter's, vary per resource, and are written on the decorator. Settings are the
driver's, vary per environment, and are written in the manifest.** `TodoList` maps to the same table everywhere; the database file differs
between dev and CI. Both are typed, so `atf check` rejects an unknown or missing key before a run
rather than raising during one.

The cost is that `update` is not optional. A system with no partial update has to implement it as
delete-and-recreate, and should say so in a docstring rather than quietly losing a field.
[Extending ATF](../reference/extending-atf.md#registering-an-adapter) has every signature, every
attribute, and the reconciliation rules those methods sit inside.

## Register it

`@driver("todo")` registers the machinery, claims the `todo:` block in each environment, and binds
the class into its module under that name. `@adapter("owner", driver="todo")` registers `todo.owner`
and hangs the decorator off the driver, so a declaration reads `@todo.owner(...)`. Name
the module under `extensions:` in `atf.yaml`, then import the decorator where you declare resources —
`from atf import sql`, the line at the top of every `resources.py` in these guides.

An adapter that needs several drivers takes several parameters; there is no list to keep in step. A
driver an adapter asks for that the environment does not configure fails at load, naming both.

```yaml
extensions: [./adapters/todo.py]
```

That same name is the key an environment configures under, validated against `Settings`:
`sql: { path: ./todo.db }`. One `Sqlite` instance is built per system, per environment, so the
connection lives on `self`. Nothing is passed to your methods except the resource in front of them:
no context object.

## The same shape, for a system that is not a database

Nothing above is about SQL. A `Guest` held as a Redis hash is the same methods against a
different client, with an `Options` of its own:

```python
# adapters/redis_store.py
@adapter("redis")
class Redis:
    class Settings(TypedDict):
        url: str

    class Options(TypedDict):
        key: str                      # a template over the resource's fields
        ttl: NotRequired[int]

    def key(self, resource, values) -> str:
        return resource.options["key"].format(**values)

    def find(self, resource):
        try:
            record = self.client.hgetall(self.key(resource, resource.identity))
        except RedisError as failure:
            raise Unreachable(f"redis at {self.url}: {failure}")
        return record or None
```

Here `.identity` is built from the fields the `key` template names, where the todo adapter fixed
its own with `recognised_by`. Declare against it exactly as you declare against `todo`:

```python
@redis(key="guest:{nickname}", ttl=3600, scope="function", depends_on=[TodoList])
class Guest:
    nickname: str
```

`scope`, `when_absent` and `depends_on` are ATF's, available on every system decorator. `key` and
`ttl` are this adapter's `Options`. `groceries` is provisioned first, by the todo adapter, because
`depends_on` is an edge like any other. Neither adapter knows the other exists.

## The optional method

`browse` unlocks `When I list every <type>` and `Then the environment has N <type>`.

```python
    def browse(self, resource):
        rows = self.db.execute(f"SELECT * FROM {self.table(resource)}").fetchall()
        return [dict(row) for row in rows]
```

Leave it out where the system cannot do it cheaply: `atf check` then refuses the sentences that need
it and names the adapter.

There is no method for domain verbs. `When the task "laundry" field "done" becomes "1"` reaches
`update`, which you have already written because it is required, and
[a phrase](teach-atf-a-sentence.md) over that sentence is what makes it read
`When I complete the task "laundry"`. Every adapter gets that the moment it exists.

## What you get with no further work

- **`atf status <env>`** lists the resources as `present`, `absent` or `unreachable`.
- **`atf make <env>`** provisions them in lineage order.
- **`atf impact` and `atf unused`** include them. The graph is built from field types.
- **In the editor**, they appear beside every other system's, with their fields and their state, and
  a pending `update` shows as a diff before it is applied.
- **To an agent** (`atf edit --mcp`), the same resources and states are exposed as structure.
  `Options` and `Settings` are the schema.

[One engine, two surfaces](../explanation/one-engine-two-surfaces.md) explains why one class reaches
all of these.

## When it goes wrong

**`unknown key "keys" in Guest`.** The declaration does not match `Options`.

**`unknown key "uri" in local.redis`.** The environment block does not match `Settings`.

**Everything reports `absent`.** `find` returns something falsy for records that exist. Check the
table name or the key template.

**Everything reports `absent` when the server is down.** You swallowed the connection error. Raise
`Unreachable`.

**A resource is updated on every run.** `find` returns a shape that never matches the declaration — a
number as a string, a field missing. ATF compares what you returned.

**A test fails on teardown.** `delete` is not tolerating an already-gone record.

**`redis is not configured for environment "staging"`.** A resource declares the system; the
environment does not configure it.

**`the 'redis' adapter asks for the cache driver, and the 'local' environment configures none`.**
The adapter's `__init__` names a driver nothing registered or nothing configured.

**`Thing: the 'redis' adapter has no 'update', so one is never changed`.** Reconciliation found a
record differing from its declaration and the adapter cannot write. Add `update`, or declare the
resource `when_absent="observe"` if it is only ever looked at.

## Where to go next

- [Extending ATF](../reference/extending-atf.md#registering-an-adapter) — the adapter contract in
  full, beside the other extension points.
- [Configure an environment](configure-an-environment.md) — where your `Settings` block goes.
- [Add a resource](add-a-resource.md) — declaring against your new system.
