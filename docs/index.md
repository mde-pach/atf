# Start

You have an application and you want a test against it. Here is the shortest path from nothing to a
green suite, and then to a red one and back.

## Something green

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

`atf init` looks around — a compose file, an `.env`, a database URL, a command on your path — writes
a manifest naming what it found, writes one scenario, runs it, and says whether it went green. ATF
needs Python 3.11 or newer.

Three files. One says where to run:

```yaml
environments:
  local:
    # ATF may make things here. `them` means it may only look.
    owner: atf
    filesystem: { root: . }
    shell: { prefix: "" }
```

One says what has to exist:

```python
from atf import needs
from atf.resources.filesystem import File


class Note(File):
    path: File.Key[str]
    text: str = needs(lambda: "written by atf init\n")


hello = Note(path="atf-hello.txt", text="hello from atf\n")
```

And one is the test:

```gherkin
Feature: the suite runs

  Scenario: a declared file is there before the test
    Given the note "hello"
    Then the note "hello" text is "hello from atf\n"
```

`Given the note "hello"` is what makes the file exist. Nothing else set it up.

## A suite over a real application

The rest of this page is `examples/todo` in the repository: a FastAPI application over SQLAlchemy
models on SQLite, and the suite that tests it.

```console
$ cd atf/examples/todo
$ atf run
0 failed, 11 passed, 0 skipped   (r-83579b)
```

Nothing was started first. Between those two lines ATF started the API, waited for its port, created
an owner and a list over HTTP, wrote a task row into the database, ran eight scenarios and three
Python tests, took back everything it had made, and stopped the API.

It knew what to do because the suite says what has to exist:

```python
from atf import needs
from atf.resources.process import Process
from atf.resources.rest import Record


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


serving = Api()
primary = Owner(api=serving, email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

The path a system reads for is named once, on the field: `Record.Key[str]` says what tells one
`Owner` apart from another, the way `File.Key[str]` did above for a `Note`. `Owner`/`TodoList`
share one override, `Listed`, for the one thing this API does its own way — a listing comes back
wrapped, not bare — written where the two declarations that need it are, not as an option every
other API would carry.

And the scenarios ask for things by name:

```gherkin
  Scenario: a list shows under its owner
    Given the todo_list "groceries"
    When I ask for the lists of "primary"
    Then the answer names "groceries"
```

`Given the todo_list "groceries"` makes the owner first and then the list, because `TodoList.owner`
says `needs()`. That is the whole of how ATF knows the order.

## It went red

Change the claim so it does not hold, and run again:

```console
$ atf run
atf/lists.feature:9  Scenario: a list shows under its owner
  Then the answer names "vegetables"

  the answer: it named groceries

  groceries            present, the test
    └ primary              present, the run
      └ serving              present, the run

  → atf enter "a list shows under its owner"

1 failed, 10 passed, 0 skipped   (r-30dd5e)
```

The sentence that stopped, what came back, then the chain that put the subject of the claim there —
each link with what the environment says about it and how long it lives. The last line is the
command that takes you back inside.

## Inside it

```console
$ atf enter
  a list shows under its owner · arranged, replayed to the failing line

    ✓ Given the todo_list "groceries"
    ✓ When I ask for the lists of "primary"
    ✗ Then the answer names "vegetables"
      the answer: it named groceries
>>> primary
      a owner · present · lives the run
      email 'primary@example.com', id 2
>>> I ask for the lists of "primary"
      items [{'id': 1, 'slug': 'groceries', 'owner_id': 2}]
>>> done
```

Bare `atf enter` takes the last thing that failed, arranges it again, replays to the line that
stopped, and leaves a prompt there. Any sentence the suite knows runs for real; a thing's name reads
it from the environment now; `?` lists the rest. It writes what a run writes, and takes it away when
you type `done`.

The API did answer with `groceries`, so the claim was wrong about the word. Put it back:

```console
$ atf run
0 failed, 11 passed, 0 skipped   (r-32e9b6)
```

## Next

- [Arranging what a test needs](guides/arranging.md) — declaring things, and how one needs another.
- [Running it somewhere else](guides/environments.md) — environments, and what ATF may write in each.
- [Leaving nothing behind](guides/cleanup.md) — how long things live, and what a run takes back.
- [When it goes red](guides/failures.md) — reading a failure, and getting inside one.
- [Running less of it](guides/choosing.md) — selection, sharding, and what runs beside what.
- [Saying it in your own words](guides/words.md) — phrases, acts, checks, kinds, report formats.
- [Somewhere ATF has not heard of](guides/systems.md) — writing a system of your own.
- [Sentences](reference/sentences.md) and [Commands](reference/commands.md), both generated.
