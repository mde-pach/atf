# Teach ATF a new system

Write an [adapter](../reference/arrange.md#adapter) so resources can live in a system ATF does not
ship for — a cache, a queue, a service with its own protocol. An adapter answers four questions about
a resource: is it there, make it, change it, remove it. Two more are optional: do this to it, and list
them all.

You have been using one since the first page. ATF ships `@command`, `@browser`, `@filesystem` and
`@process` — the systems it needs to test itself — and nothing that binds it to a database. `@sqlite`,
the decorator on every declaration in these guides, is an adapter somebody wrote, living in the suite
that uses it. Here is the file.

## The shortest path

```python
# adapters/sqlite.py
import sqlite3
from typing import Any, NotRequired, TypedDict

from atf import Unreachable, adapter


@adapter("sqlite")
class Sqlite:
    """Ships the @sqlite(...) decorator with it."""

    class Settings(TypedDict):        # what an environment configures
        path: str

    class Options(TypedDict):         # what the decorator takes, per resource
        unique_by: str
        table: str                    # named on the decorator, never guessed

    def __init__(self, settings: Settings):
        self.path = settings["path"]
        try:
            self.db = sqlite3.connect(self.path)
        except sqlite3.Error as failure:
            raise Unreachable(f"sqlite at {self.path}: {failure}")
        self.db.row_factory = sqlite3.Row

    def table(self, resource) -> str:
        return resource.options.get("table") or f"{resource.kind.lower()}s"

    def flatten(self, values) -> dict[str, Any]:
        record = {}
        for name, value in values.items():
            if isinstance(value, dict):       # a field typed as another resource
                record[f"{name}_id"] = value["id"]
            else:
                record[name] = value
        return record

    def find(self, resource):
        where = " AND ".join(f"{field} = ?" for field in resource.identity)
        try:
            row = self.db.execute(
                f"SELECT * FROM {self.table(resource)} WHERE {where}",
                tuple(resource.identity.values()),
            ).fetchone()
        except sqlite3.Error as failure:
            raise Unreachable(f"sqlite at {self.path}: {failure}")
        return dict(row) if row else None

    def create(self, resource):
        record = self.flatten(resource.values)
        placeholders = ", ".join("?" * len(record))
        self.db.execute(
            f"INSERT INTO {self.table(resource)} ({', '.join(record)}) VALUES ({placeholders})",
            tuple(record.values()),
        )
        self.db.commit()
        return self.find(resource)

    def update(self, resource, found, changes):
        applied = self.flatten(changes)
        assignments = ", ".join(f"{field} = ?" for field in applied)
        self.db.execute(
            f"UPDATE {self.table(resource)} SET {assignments} WHERE id = ?",
            (*applied.values(), found["id"]),
        )
        self.db.commit()
        return {**found, **applied}

    def delete(self, resource, found):
        self.db.execute(f"DELETE FROM {self.table(resource)} WHERE id = ?", (found["id"],))
        self.db.commit()
```

That is the whole of `@sqlite(table="owners", unique_by="email")`. Provisioning an owner, writing a list's foreign
key, tearing a guest down — all of it is those four methods and the two helpers above them.

Four things in there are the contract, and each is one line to get wrong.

- **`resource`** carries `.name`, `.kind`, `.options`, `.identity` — the
  [recognition](../reference/arrange.md#recognition) fields and their values — and `.values`, every
  declared field with lineage resolved. Which fields make up `.identity` is an option you define:
  `unique_by` above.
- **`changes`** is a mapping ATF computed. The adapter never diffs; it applies what it is handed. That
  is what lets `atf make --dry-run` and the editor show a pending update before it runs.
- **`find` returns `None` for absent** and raises `atf.Unreachable` when the system did not answer at
  all. Nothing else can tell a missing row from a dead server.
- **`delete` must tolerate a record that is already gone.** Function-scoped teardown runs after a test
  that may itself have removed it.

**Options vary per resource and are written on the decorator. Settings vary per environment and are
written in the manifest.** `TodoList` maps to the same table everywhere; the database file differs
between dev and CI. Both are typed, so `atf check` rejects an unknown or missing key before a run
rather than raising during one.

The cost is that `update` is not optional. A system with no partial update has to implement it as
delete-and-recreate, and should say so in a docstring rather than quietly losing a field.
[Extending ATF](../reference/extending-atf.md#registering-an-adapter) has every signature, every
attribute, and the reconciliation rules the four methods sit inside.

## Register it

`@adapter("sqlite")` registers the class and defines a decorator of that name in the same module. Name
the module under `extensions:` in `atf.yaml`, then import the decorator where you declare resources —
`from adapters.sqlite import sqlite`, the line at the top of every `resources.py` in these guides.

```yaml
extensions: [./adapters/sqlite.py]
```

That same name is the key an environment configures under, validated against `Settings`:
`sqlite: { path: ./todo.db }`. One `Sqlite` instance is built per system, per environment, so the
connection lives on `self`. Nothing is passed to your methods except the resource in front of them:
no context object.

## The same shape, for a system that is not a database

Nothing above is about SQL. A `Guest` held as a Redis hash is the same four methods against a
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

Here `.identity` is built from the fields the `key` template names, where sqlite's came from
`unique_by`. Declare against it exactly as you declare against sqlite:

```python
@redis(key="guest:{nickname}", ttl=3600, scope="function")
class Guest:
    nickname: str
    todo_list: TodoList
```

`scope` and `when_absent` are ATF's, available on every system decorator. `key` and `ttl` are this
adapter's `Options`. `groceries` is provisioned first, by the sqlite adapter, because
`todo_list: TodoList` is an edge like any other. Neither adapter knows the other exists.

## The two optional methods

`act` unlocks `When I <verb> the <type> "<name>"`, for every entry in a resource's `actions`.
`browse` unlocks `When I list every <type>` and `Then the environment has N <type>`.

```python
    @dataclass
    class Update:                     # one of this adapter's action types
        done: bool

    def act(self, resource, found, action):
        if isinstance(action, self.Update):
            self.update(resource, found, {"done": action.done})
        return self.find(resource)

    def browse(self, resource):
        rows = self.db.execute(f"SELECT * FROM {self.table(resource)}").fetchall()
        return [dict(row) for row in rows]
```

A `Task` declared `actions={"complete": Sqlite.Update(done=True)}` now answers
`When I complete the task "laundry"`, and no step was written for it. Leave both methods out where the
system cannot do them cheaply: without a `browse`, `atf check` refuses the sentences that need it and
names the adapter.

## What you get with no further work

- **`atf status <env>`** lists the resources as `present`, `absent` or `unreachable`.
- **`atf make <env>`** provisions them in lineage order.
- **`atf impact` and `atf unused`** include them. The graph is built from field types.
- **In the editor**, they appear beside every other system's, with their fields, their state and their
  actions, and a pending `update` shows as a diff before it is applied.
- **To an agent** (`atf edit --mcp`), the same resources and states are exposed as structure.
  `Options`, `Settings` and the action classes are the schema.

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

**`adapter "redis" has no act()`.** Something declared `actions` without the method to run them.

**`adapter "redis" has no update()`.** `update` is required. Reconciliation needs it.

## Where to go next

- [Extending ATF](../reference/extending-atf.md#registering-an-adapter) — the adapter contract in
  full, beside the other extension points.
- [Configure an environment](configure-an-environment.md) — where your `Settings` block goes.
- [Add a resource](add-a-resource.md) — declaring against your new system.
