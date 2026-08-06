# Depend on another resource

Declare that one resource needs another, and get the provisioning order without writing it down.

## The shortest path

Write it in `depends_on`.

```python
# resources.py
from adapters.sqlite import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug", depends_on=[Owner])
class TodoList:
    slug: str


primary = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

Two lines are doing two different jobs, and it is worth seeing which is which.

`depends_on=[Owner]` says **a list needs an owner** — any owner. It is the edge, and it is true of
every `TodoList` there will ever be.

`owner=primary` says **this list's owner is that one**. It is also the value the adapter writes, so
the kind-level requirement is answered by it rather than repeated. That is what
[lineage](../reference/arrange.md#lineage) means by *nobody writes a dependency twice*: dbt's
`ref()`, said once, wherever there is somewhere to say it.

## When there is nowhere to put the parent

A report written per owner might store only its own slug and a rendered body. There is no `owner`
field to pass, and it still needs an owner:

```python
@sqlite(table="reports", unique_by="slug", depends_on=[Owner])
class Report:
    slug: str
    body: str


quarterly = Report(slug="quarterly", body="<html/>", depends_on=[primary])
```

`depends_on` on the instance says which one. **This is why the graph is not read off the shape.** A
dependency is not always a value the resource carries, and one that has nowhere to live is still a
dependency.

## The ordering nobody wrote down

Ask for the list.

```gherkin
Scenario: a list shows under its owner
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"
```

`primary` is provisioned first, then `groceries`, with the owner's record handed to the adapter so
it can write whatever a list calls its owner. Nothing in the suite says "owners before lists". A
pytest function asking for `groceries: TodoList` gets the same two records in the same order.

Depth does not change anything. A `Task` that depends on a `TodoList` gives a three-link closure
from one name.

```python
@sqlite(table="tasks", unique_by="slug", depends_on=[TodoList])
class Task:
    slug: str


laundry = Task(todo_list=groceries, slug="laundry")
```

`Given the task "laundry"` now provisions an owner, a list and a task.

The cost is that the closure is not optional. Naming `laundry` provisions three records even when
the scenario claims about one, and every test that names it pays for all three. Where something is
really only a value the test happens to know — a slug, a code — hold it as an ordinary field and buy
no edge.

## What the graph then answers

`depends_on` is the edges, so three commands read them:

- `atf impact groceries` — what depends on it, and every test that touches it.
- `atf run --select +groceries` — only those tests, including ones that name `laundry` and never
  mention the list.
- `atf unused` — the instances no test reaches, so they can be deleted rather than provisioned
  forever.

[Run only what a change touched](run-only-what-a-change-touched.md) works all three, and
[the command](../reference/the-command.md#impact) has the full selection syntax.

## Variations

**Two parents of the same kind.** Pass both. Each value that is a resource is its own edge.

```python
@sqlite(table="lists", unique_by="slug", depends_on=[Owner])
class TodoList:
    slug: str


groceries = TodoList(owner=primary, reviewer=secondary, slug="groceries")
```

A test that then asks for `owner: Owner` by kind is ambiguous, because the closure put two owners in
scope — and ATF says so [at collection](../reference/arrange.md#asking-for-one), before anything
runs. Name the one you mean.

**A parent nobody named.** Leave it out, and the [factory](../reference/arrange.md#factory) builds
one:

```python
scratch = TodoList(slug="scratch")     # depends_on=[Owner] is met by Owner.factory()
```

A kind with no factory and nothing named is an error, and it is also caught at collection.

**A dependency in another system.** `depends_on` reads the same whether the two resources live in
one table, in different systems, or one in a database and one on a filesystem. Ordering follows the
declaration, not the storage.

**A dependency the environment owns.** Depend on a resource declared `when_absent="require"`, and
the closure stops there rather than trying to create it. See
[Require something you cannot create](require-something-you-cannot-create.md).

## When it goes wrong

**A cycle.** Two resources that each need the other cannot be ordered.

```python
default = TodoList(owner=primary, slug="default")
primary = Owner(email="primary@example.com", depends_on=[default])   # and default needs primary
```

```console
$ atf impact primary
CycleError: a resource cannot need itself: default:TodoList -> primary:Owner -> default:TodoList
$ echo $?
2
```

The way round is in the message, and no environment was touched to find it: the graph is data, so
the failure arrives before anything is asked. It exits `2` — the question could not be answered —
rather than `1`, because a suite that cannot be ordered has no answer to give.

Break it by keeping the edge on the side that cannot exist without the other — a list needs an
owner, so `TodoList` keeps it. Express the other direction as an ordinary field holding the
recognition value, or as an [action](../reference/act.md#action) performed once both records exist.

```python
primary = Owner(email="primary@example.com", default_list_slug="default")   # a value, not an edge
```

**`depends_on holds …, which is neither a declared resource nor one of their kinds`.** `depends_on`
takes classes a system decorator has seen and instances of them, and nothing else. A bare string or
a type ATF has never been shown is refused when the module loads.

**A parent must be declared above the resource that needs it.** `depends_on=[Owner]` is ordinary
Python: the name has to exist. There is no forward reference and no string form, which is the other
half of not reading the graph off annotations — a name that cannot be resolved is a `NameError` from
Python, at the line that wrote it, rather than a missing edge nobody noticed.

**A dependency that is provisioned but empty.** ATF provisions the record, not the state a test
wants it in. If a list needs to be non-empty, that is either a `Task` in the closure or an action in
the `When`.

## Where to go next

- [Vary a resource for one test](vary-a-resource-for-one-test.md) — including removing a dependency
  for a single test with `but "owner" is "null"`.
- [Run only what a change touched](run-only-what-a-change-touched.md) — `--select` and `atf impact`
  used in anger, in CI.
- [Arrange](../reference/arrange.md#lineage) — what lineage means across two systems.
