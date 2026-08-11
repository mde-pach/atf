# Declare what it needs

Write the four things an arrange is made of — a **resource**, a **factory**, an **action** and a
**variation** — and watch ATF provision an owner that no test asked for. Keep `todo.py` and the
suite from chapter 2. Everything here goes in `resources.py`, which `atf.yaml` names under
`resources:`.

## A resource is a class

An owner is a thing with an email address, and it lives in a table:

```python
from adapters.todo import todo


@todo.owner()
class Owner:
    email: str
```

The class is the shape. The decorator is the **system**: the thing that holds this resource in an
environment and knows how to look for one, make one and remove one. `@todo.owner` means a row in a
SQLite table, and it comes from the suite's own `adapters/todo.py`. ATF ships `@filesystem.file`,
`@filesystem.directory`, `@filesystem.tree`, `@browser.page`, `@shell.process`, `@http.record` and
`@sql.row`.

`unique_by` is **recognition**: the field that decides whether a
record ATF finds is the record it declared. Give it `email` and ATF looks for a row with that email
before making one, so the second run finds the owner the first run left. Name a field the database
does not keep unique and the second run makes a duplicate. Pick the field with the constraint on it
— [chapter 4](4-point-it-at-your-own-system.md) has what that costs when you pick wrong.

That is the whole declaration: no create function, no fixture, no teardown, no SQL.

## An instance is a name

```python
primary = Owner(email="primary@example.com")
```

**Construction declares. It does not touch anything.** Importing `resources.py` writes nothing to
`todo.db`; provisioning happens when a test asks. The resource's name is the variable's name, the
same way a pytest fixture takes the name of its function, and any test can ask for it:

```python
def test_a_new_owner_has_no_lists(shell, primary: Owner):
    result = shell("todo show primary@example.com")
    assert "no lists" in result["output"]
```

Or as a scenario. Put this in `specs/declarations.feature`, where the rest of this chapter goes too:

```gherkin
Feature: declarations

  Scenario: a new owner has no lists
    Given the owner "primary"
    When I run "todo show primary@example.com"
    Then the result field "output" contains "no lists"
```

Run it. The owner is in `todo.db` afterwards, because the test asked for it and it was not there.

## One resource that needs another

A list has a slug, and it belongs to an owner:

```python
@todo.list(depends_on=[Owner])
class TodoList:
    slug: str


groceries = TodoList(owner=primary, slug="groceries")
```

`depends_on=[Owner]` is the statement that a list cannot exist before an owner does. `owner=primary`
says which owner this one has, and is the value the adapter writes — so the requirement is answered
by it rather than said twice. This is dbt's `ref()`. Ask for the list, and only the list:

```gherkin
Scenario: a list shows up under its owner
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"
  And the owner "primary" exists
```

Delete `todo.db` and run it. It passes. **Nothing in the scenario mentions `primary`.** ATF followed
the edge from `groceries` to `primary`, found the owner absent, made it, then made the list.
What you pay is that no file shows you that order, so ask the graph instead: `atf impact primary`.
[Declared, not executed](../explanation/declared-not-executed.md) is the trade in full, including
where it loses.

## Any owner will do

`Given the owner "primary"` says *that* owner. Most tests care only that there is one. Give each
resource a factory, starting at the top of `resources.py`:

```python
from typing import Self

from faker import Faker

faker = Faker()
```

Then a method on each of the two classes you already have:

```python
# in class Owner
    @classmethod
    def factory(cls) -> Self:
        return cls(email=faker.email())

# in class TodoList
    @classmethod
    def factory(cls, owner: Owner) -> Self:
        return cls(owner=owner, slug=faker.slug())
```

This is factory_boy's `SubFactory`, typed — except the sub-factory is inferred from `owner: Owner`
rather than declared. Now the indefinite article works on both surfaces:

```gherkin
Given an owner
Given a todo_list
```

```python
def test_show_reports_no_lists(shell, owner: Owner):     # any owner, not primary
```

A dependency the factory is not given is built by that resource's own factory, recursively, so
`Given a todo_list` produces a fresh list under a fresh owner. It runs against a different email
every time, which finds the tests that only ever passed because the email was
`primary@example.com` — and costs you knowing what a failing one ran with. Name an instance where
the identity matters; use a factory where it genuinely does not.

## A verb of its own

Tasks live on lists, and a task can be completed. `todo.py` has no table for them, so add one to its
`executescript`:

```sql
CREATE TABLE IF NOT EXISTS Task (id INTEGER PRIMARY KEY, slug TEXT UNIQUE,
                                 todo_list_id INTEGER REFERENCES lists(id),
                                 done INTEGER DEFAULT 0);
```

And declare it:

```python
from adapters.todo import todo


@sql.row(table="tasks", unique_by="slug")
class Task:
    todo_list: TodoList
    slug: str
    done: int


laundry = Task(todo_list=groceries, slug="laundry", done=0)
```

Nothing declares a verb. One built-in sentence moves any field of any resource:

```gherkin
Scenario: completing a task
  Given the task "laundry"
  When the task "laundry" field "done" becomes "1"
  Then the task "laundry" field "done" is "1"
```

To say it in the domain's own words, write a phrase over it — Gherkin, in the same `.feature` file,
no Python:

```gherkin
  @phrase
  Scenario: I complete the task "{name}"
    When the task "{name}" field "done" becomes "1"
```

```gherkin
  When I complete the task "laundry"
```

`complete` is now a verb the suite understands, for every task, on both surfaces, and a reader can
see what it means without opening a Python file.

That sentence writes a row; it does not run `todo.py`. It reaches a state cheaply, so a scenario
about *your application* completing a task must still act through the interface —
`When I run "todo done laundry"`. A claim about its own effect is a claim about the database.

## One test, one difference

Sometimes a single test needs the canonical resource, slightly wrong. A list whose owner was deleted
should not appear under anyone:

```gherkin
Scenario: a list with no owner belongs to nobody
  Given the todo_list "groceries" but "owner" is "null"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "no lists"
```

**A variation is one field per sentence.** The field you name takes the value you give it, every
field you do not name keeps the declared one, and `"null"` removes the field altogether. Here the
varied list has no owner, so the closure has nothing to follow and `primary` is not provisioned for
this test. A second difference is a second sentence:

```gherkin
Given the todo_list "groceries" but "slug" is "shopping"
And "owner" is "null"
```

The `And` line carries no resource name: it is still talking about the list the `Given` named.

The variation belongs to the test that wrote it, and `groceries` is untouched everywhere else. The
cost is that a varied resource has no name, so nothing else can refer to it. When two or three tests
want the same variation, it wants a declaration instead:

```python
weekly = TodoList(owner=primary, slug="weekly")
```

## Run everything

Four new scenarios, plus the two features and the pytest file from chapters 1 and 2. Delete
`todo.db` first, so nothing is left over from an earlier run:

```console
$ rm todo.db
$ atf run
```

```text
specs/declarations.feature

  Scenario: a new owner has no lists
    ...

  Scenario: a list shows up under its owner
    passed   Given the todo_list "groceries"
    passed   When I run "todo show primary@example.com"
    passed   Then the result field "output" contains "groceries"
    passed   And the owner "primary" exists

  Scenario: completing a task
    ...

  Scenario: a list with no owner belongs to nobody
    ...

specs/ownership.feature
  ...

specs/showing-a-list.feature
  ...

specs/test_ownership.py
  ...

7 tests, 7 passing
```

An empty database at the start and seven green at the end, and nowhere in the suite did anybody say
that owners come before lists.

## Where to go next

- [Point it at your own system](4-point-it-at-your-own-system.md) — the same declarations against the
  database and command line you actually ship, and what ATF does when it finds a record that is
  nearly right.
- [Vary a resource for one test](../how-to/vary-a-resource-for-one-test.md) — `but` on a field of a
  field, and when to stop varying and declare.
- [Arrange](../reference/arrange.md) — every option a declaration takes, in one table, when you need
  the one this chapter did not use.
