# Adopt ATF in an existing suite

Add ATF to a repository that already has hundreds of pytest tests, convert the setup one directory
shares into resources, and keep every existing test working.

## The shortest path

Install it, and write a manifest that points at one directory.

```sh
pip install atf
atf init
```

```yaml
# atf.yaml
resources: [./tests/lists/resources.py]
specs: ./specs
extensions: [./adapters/sqlite.py]
default_env: local

environments:
  local:
    mutable: true
    sqlite:  { path: ./todo.db }
    command: { prefix: "python todo.py" }
```

Take the fixture that directory's tests all share:

```python
# tests/lists/conftest.py — before
@pytest.fixture
def primary(db):
    db.execute("INSERT INTO owners (email) VALUES (?)", ("primary@example.com",))
    db.commit()
    return db.execute(
        "SELECT * FROM owners WHERE email = ?", ("primary@example.com",)
    ).fetchone()
```

…and declare the same thing as data:

```python
# tests/lists/resources.py — after
from adapters.sqlite import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


primary = Owner(email="primary@example.com")
```

Delete the fixture. Every test that took `primary` still takes `primary`, and nothing else in those
files changes.

```python
def test_show_lists_nothing_yet(primary: Owner, shell):
    result = shell(f"todo show {primary.email}")
    assert result["output"].strip() == "no lists"
```

**A resource is a pytest fixture.** The parameter name resolves and the annotation types — pytest's
own rule, applied to declared data. So an existing test consumes a resource by adding a parameter,
and needs no other change: no base class, no decorator, no marker, no rewrite, no feature file.

## Do one directory at a time

ATF imports the modules listed under `resources:` and nothing else. There is no scan. A directory
you have not listed is a directory ATF has never heard of, and its tests run exactly as they did
yesterday.

```yaml
resources: [./tests/lists/resources.py, ./tests/billing/resources.py]
```

A second directory is a second line, added when you are ready for it. The trade-off is the one
[Add a resource](add-a-resource.md) names: a file you forget to list is invisible, and the missing
entry reads as a missing name.

`atf run` collects your pytest tests where pytest already finds them, and the scenarios under
`specs:`. A directory with no resources in it contributes tests to the run and nothing to the graph.

## What to convert first

The setup everything in that directory shares. It is usually one or two fixtures near the top of a
`conftest.py`, taken by most of the tests below it, inserting rows so that the rest can act.

Convert the root of that chain first — `Owner` — then the thing that needs it:

```python
@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner          # the dependency, and the foreign key
    slug: str


groceries = TodoList(owner=primary, slug="groceries")
```

The ordering you used to write down goes away. A test asking for `groceries` gets `primary` because
the field says so, and the fixture that built an owner and passed it into a list-building fixture
has nothing left to do. That is the conversion paying for itself: not one fixture replaced by one
declaration, but a chain of them replaced by [lineage](../reference/arrange.md#lineage).

Convert in this order and stop when it stops being obvious. Half a directory converted is a working
directory.

## What not to convert

Setup that is genuinely a computation stays a fixture. A resource can be found, created, updated and
deleted, and that is all of it — no `yield`, no arbitrary code, no `autouse`, no parametrisation.

A frozen clock, a captured log, a temporary directory, a built request payload, a mock, a client for
your own product: all fixtures, all unchanged, and all still working beside resources in the same
signature.

```python
def test_a_list_is_dated_today(groceries: TodoList, frozen_clock, shell):
    result = shell(f"todo show {groceries.owner.email}")
    assert frozen_clock.today.isoformat() in result["output"]
```

`groceries` is a resource and `frozen_clock` is one of yours. pytest resolves both the same way,
because to pytest they are the same kind of thing.

The test for whether something should be a resource is whether a system can find it. A row, a file,
a screen: yes. A value your test computes: no.

## The graph grows as parameters appear

A fixture parameter is a declaration, so the graph includes plain pytest tests without a feature
file anywhere near them.

```console
$ atf impact groceries
TodoList groceries
  depends on
    Owner primary
  depended on by
    Task laundry
  tests that touch it
    tests/lists/test_show.py::test_show_lists_nothing_yet
    tests/lists/test_show.py::test_a_list_is_dated_today
  2 tests, 2 resources
```

Nothing in those two tests is ATF-shaped except the annotation. The same edge drives selection:

```sh
atf run --select +groceries
```

That is the return on converting a directory. Every test that takes the parameter is on the graph
from the moment it takes it, and [Run only what a change
touched](run-only-what-a-change-touched.md) works on the suite you already had.

## Gherkin is optional

You can adopt the resource model and never write a `Scenario:` line. `atf status`, `atf make`,
`atf impact` and `atf unused` read the resource graph, and the graph does not care whether the tests
above it are prose or Python.

Keep the empty `specs/` directory `atf init` wrote — `atf check` faults on a `specs` path that is
not there — and leave it empty for as long as you like. Scenarios earn their place when the tests
are read by people who do not write Python; [One engine, two
surfaces](../explanation/one-engine-two-surfaces.md) makes the case both ways.

## When it goes wrong

**`unknown resource "primary"`.** Either `tests/lists/resources.py` is not listed under `resources:`
in `atf.yaml`, or the instance is not at module level. An instance built inside a function has no
variable name ATF can read.

**The test passes but nothing was declared.** The old fixture is still in `conftest.py`. pytest
resolves the nearest one, so a leftover fixture silently wins over the resource of the same name and
the graph stays empty. Delete the fixture — `atf impact` naming no tests is the tell.

**`two owners in scope: primary, deputy`.** A test asked for `owner: Owner` where two instances were
arranged. Name the one you mean. pytest would never have complained, which is the point.

**A test that used to get a clean row now gets a dirty one.** Fixtures rebuilt per test; resources
are [`persistent`](../reference/arrange.md#scope) unless you say otherwise, so a record a test
mutates stays mutated. Either give that resource `scope="function"` and pay the create and delete,
or have the test put back what it changed — [Make something fresh for each
test](make-something-fresh-for-each-test.md).

**`Owner: unique_by names "email", which is not a field`.** `atf check` catches it without touching
an environment. Run it after each declaration you move.

## Where to go next

- [Depend on another resource](depend-on-another-resource.md) — the typed field that replaces a
  chain of fixtures calling one another.
- [Make something fresh for each test](make-something-fresh-for-each-test.md) — what to do about the
  fixtures you converted that tests were mutating.
- [Run only what a change touched](run-only-what-a-change-touched.md) — the first thing the graph
  buys you once one directory is converted.
