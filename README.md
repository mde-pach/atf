# ATF

**What a test needs to exist is declared as typed data, and the graph comes with it.**

A suite says what must be there — an owner, a list, a row, a file, a running server — as ordinary
Python classes and module-level variables. ATF reads that and answers the rest: what order things
are made in, how long each one lives, what teardown takes away, which tests can run at the same
time, which tests a change reaches, and why the thing under a failing assertion was there.

## A whole suite, on one screen

`examples/todo` is a FastAPI application over SQLAlchemy on SQLite, and the suite that tests it.

Where to run, in `atf.yaml`:

```yaml
environments:
  local:
    owner: atf                 # ATF may make things here. `them` means it may only look.
    http:  { base_url: "http://127.0.0.1:8801" }
    sql:   { path: ./todo.db }
    shell: { cwd: . }
```

What has to exist, in `atf/things.py`:

```python
from atf import needs
from atf.resources.process import Process
from atf.resources.rest import Record
from atf.resources.sql import Row


class Api(Process, lives="the run"):
    """The API under test, started for the run and stopped when it ends."""

    command: Process.Key[str] = "python api.py"
    port: int = 8801


class Listed(Record):
    """This API answers a listing as `{"items": [...]}` — its own shape, not ATF's."""

    def _collection(self, params=None):
        url = type(self)._path()
        return self.http.client.get(url, params=dict(params or {})).json().get("items", [])


class Owner(Listed, at="/owners"):
    api: Api = needs()
    email: Record.Key[str] = needs(an_email)


class TodoList(Listed, at="/lists"):
    owner: Owner = needs()
    slug: Record.Key[str]


class Task(Row, at="tasks"):
    todo_list: TodoList = needs()
    slug: Row.Key[str]
    done: bool


serving = Api()
primary = Owner(api=serving, email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
laundry = Task(todo_list=groceries, slug="laundry", done=False)
```

Identity is named once, on the field: `Record.Key[str]`/`Row.Key[str]` say what tells one of these
apart, the way `known_by=`/`list_filter=` used to on the decorator. `Owner`/`TodoList` share one
override, `Listed`, for the one thing this API does its own way — a wrapped listing — written
where the two declarations that need it are.

`needs()` says how a field is filled when nobody gave it a value. On `TodoList.owner` that names the
lineage; on `Owner.email` it names a function you wrote. ATF produces no values itself.

The tests, in `atf/lists.feature`:

```gherkin
  Scenario: a list shows under its owner
    Given the todo_list "groceries"
    When I ask for the lists of "primary"
    Then the answer names "groceries"
```

And the same arrangement in Python, through one resolver, in `atf/test_lists.py`:

```python
def test_lineage_comes_along(groceries: TodoList):
    """Asking for the list made its owner first, because the field says `needs()`."""
    assert groceries.owner.email == "primary@example.com"
```

```console
$ atf run
0 failed, 11 passed, 0 skipped   (r-83579b)
```

Nothing was started first. ATF started the API, waited for the port, made an owner and a list over
HTTP, wrote a task row into the database, ran everything, took it all back, and stopped the API.

## What the graph answers

Two tests that share nothing permanent cannot interfere, so a run lays itself out concurrently with
no flag and no marker on a test — and says which sentence forced anything to go alone:

```console
$ atf run --explain
11 tests
  7 can run beside something else, in 1 sets
  4 run alone
         3  "a Python test body" has an effect nothing declares
         1  "I ask for the lists of "primary"" has an effect nothing declares
```

Nobody types how long a thing lives. Each one earns the weakest span that is still safe, and the
command says which rule gave it:

```console
$ atf plan --lives
  how long each thing lives
  anyone     the run   it is resolved rather than declared
  primary    the run   it cannot outlive serving
  serving    the run   written on the declaration — ATF cannot see this one
  groceries  the test  some scenario changes it
  laundry    the test  some scenario changes it
```

And a failure prints the chain that put the subject of the claim there:

```text
atf/lists.feature:9  Scenario: a list shows under its owner
  Then the answer names "vegetables"

  the answer: it named groceries

  groceries            present, the test
    └ primary              present, the run
      └ serving              present, the run

  → atf enter "a list shows under its owner"
```

## Six commands

`atf init` starts you off. `atf plan` says whether the suite is sound and what will happen. `atf run`
runs it and records a run. `atf enter` puts you inside a failure. `atf explain` tells you everything
about one thing. `atf edit` serves all of it on a page.

The exit code is `0` when there is nothing wrong, `1` when a test failed or the suite has a fault in
it, and `2` when the run never started — in which case nothing was recorded.

## Getting going

```console
$ git clone https://github.com/mde-pach/atf
$ pip install ./atf
$ cd ~/my-project && atf init
found nothing already here — the scaffold declares a file, which always works
wrote atf.yaml
wrote atf/things.py
wrote atf/hello.feature

0 failed, 1 passed, 0 skipped   (r-b60d1c)

green. Write the next scenario in atf/hello.feature.
```

`atf init` looks around for a compose file, an `.env`, a database URL and a command on your path,
writes a manifest naming what it found, writes one scenario, runs it, and prints green. ATF needs
Python 3.11 or newer.

## Documentation

[Start](docs/index.md) is one path end to end. After that there is one guide per thing somebody
wants to do — [arranging](docs/guides/arranging.md), [environments](docs/guides/environments.md),
[cleanup](docs/guides/cleanup.md), [failures](docs/guides/failures.md),
[choosing](docs/guides/choosing.md), [your own words](docs/guides/words.md) and
[your own system](docs/guides/systems.md) — plus the generated
[sentences](docs/reference/sentences.md) and [commands](docs/reference/commands.md).
