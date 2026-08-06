# What ATF is

ATF is a test framework in which the preconditions of a test are **declared as typed data rather
than executed as setup code**. A resource — an owner, a list, a browser session — is a class with
typed fields and a system behind it. A test names the resources it needs, ATF makes them exist,
creating what is missing and updating what differs, and then the test runs.

Declaring them buys a graph: what depends on what, and which tests need which things. ATF holds that
graph before anything runs, and can read, order, draw and query it. ATF is pointed at whatever a
team already has — a command line, a browser, a database, an HTTP API, a queue. There is no backend
to install.

## An example

Two files. The first declares what exists; nothing in it touches anything.

```python
# resources.py
from adapters.sqlite import sqlite      # this suite's adapter, not ATF's

@sqlite(table="owners", unique_by="email")
class Owner:
    email: str

@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner          # the dependency, and the foreign key
    slug: str

primary   = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

The second uses it, from a pytest function:

```python
def test_show_lists_the_list(groceries: TodoList, shell):
    result = shell(f"todo show {groceries.owner.email}")
    assert "groceries" in result["output"]
```

`shell` is the built-in fixture for [running a command line](reference/act.md#shell), through the
prefix the environment gives it.

…and from a Gherkin scenario:

```gherkin
Scenario: show lists the owner's lists
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"
```

Neither one creates an owner. Both get one, because `groceries` is typed as belonging to `primary`
and the closure follows the field. The two surfaces compile to the same thing: the same resources,
the same order, the same failure messages.

A resource *is* a pytest fixture — the parameter name resolves, the annotation types. Because its
dependency is a typed field rather than a fixture body, these answer without running a test:

```sh
atf status staging          what is present, absent or unreachable, right now
atf impact groceries        which tests break if this list does
atf unused                  what nothing asks for
atf docs                    the specs as markdown, carrying the last verdict
```

The cost: a resource can only express what a system can find, create, update and delete. Setup that
is genuinely a computation stays a pytest fixture, and plain fixtures keep working beside resources.

## Where to go

- **[Run a suite](tutorial/1-run-a-suite.md)** — four chapters, from running a suite someone handed
  you to pointing ATF at your own system.
- **[The model](orientation/the-model.md)** — the whole map on one page: five bands, every concept
  named once, and what each one sits next to.
- **[Coming from another tool](orientation/coming-from-another-tool.md)** — the route in for pytest fixtures,
  factory_boy, Cucumber, Terraform, dbt, Playwright or Django.
- **[Reference](reference/arrange.md)** — every definition, one page per band. Start with Arrange.
- **[Declared, not executed](explanation/declared-not-executed.md)** — the argument for the bet
  above, at length, including what it costs.
- **[One engine, two surfaces](explanation/one-engine-two-surfaces.md)** — why a pytest function and
  a Gherkin scenario are the same test written twice.
