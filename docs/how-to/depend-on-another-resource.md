# Depend on another resource

Declare that one resource needs another, and get the provisioning order without writing it down.

## The shortest path

Type a field as the other resource.

```python
# resources.py
from adapters.sqlite import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner          # the dependency, and the foreign key
    slug: str


primary = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

That field is the whole declaration. It is [lineage](../reference/arrange.md#lineage): dbt's `ref()`,
written as a type instead of a function call.

## The ordering nobody wrote down

Ask for the list.

```gherkin
Scenario: a list shows under its owner
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"
```

`primary` is provisioned first, then `groceries`, with the owner's row id written into the list's
foreign key. Nothing in the suite says "owners before lists". A pytest function asking for
`groceries: TodoList` gets the same two records in the same order.

Depth does not change anything. A `Task` typed against a `TodoList` gives a three-link closure from
one name.

```python
@sqlite(table="tasks", unique_by="slug")
class Task:
    todo_list: TodoList
    slug: str


laundry = Task(todo_list=groceries, slug="laundry")
```

`Given the task "laundry"` now provisions an owner, a list and a task.

The cost is that the closure is not optional. Naming `laundry` provisions three records even when the
scenario claims about one, and every test that names it pays for all three. Where a field is really
only a value the test happens to know — a slug, a code — hold it as an ordinary field rather than
buying an edge you did not want.

## What the graph then answers

The typed fields are edges, so three commands read them:

- `atf impact groceries` — what depends on it, and every test that touches it.
- `atf run --select +groceries` — only those tests, including ones that name `laundry` and never
  mention the list.
- `atf unused` — the instances no test reaches, so they can be deleted rather than provisioned
  forever.

[Run only what a change touched](run-only-what-a-change-touched.md) works all three, and
[the command](../reference/the-command.md#impact) has the full selection syntax.

## Variations

**Two fields of the same kind.** Both are provisioned, and both are distinct dependencies.

```python
@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    reviewer: Owner
    slug: str
```

A test that then asks for `owner: Owner` by kind is ambiguous, because the closure put two owners in
scope. Name the one you mean.

**A dependency in another system.** The field is typed the same way whether the two resources live in
one table, in different systems, or one in a database and one on a filesystem. Ordering follows the
field.

**A dependency the environment owns.** Type the field against a resource declared with
`when_absent="require"`, and the closure stops there rather than trying to create it. See
[Require something you cannot create](require-something-you-cannot-create.md).

## When it goes wrong

**A cycle.** Two resources that each need the other cannot be ordered.

```python
@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
    default_list: "TodoList"      # and TodoList.owner is still typed Owner
```

```console
$ atf check
cycle: Owner.default_list -> TodoList.owner -> Owner
```

`atf check` finds it without touching an environment, so the failure arrives at declaration time.

Break it by keeping the typed field on the side that cannot exist without the other — a list needs an
owner, so `TodoList.owner` stays. Express the other direction as an ordinary field holding the
recognition value, or as an [action](../reference/act.md#action) performed once both records exist.

```python
@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
    default_list_slug: str        # a value, not a dependency
```

**`unknown resource "TodoList"`.** A forward reference in quotes is resolved after the module is
imported. If the name never appears in a listed module, the field types against nothing.

**A dependency that is provisioned but empty.** ATF provisions the record, not the state a test wants
it in. If a list needs to be non-empty, that is either a `Task` in the closure or an action in the
`When`.

## Where to go next

- [Vary a resource for one test](vary-a-resource-for-one-test.md) — including removing a dependency
  for a single test with `but "owner" is "null"`.
- [Run only what a change touched](run-only-what-a-change-touched.md) — `--select` and `atf impact`
  used in anger, in CI.
- [Arrange](../reference/arrange.md#lineage) — what lineage means across two systems.
