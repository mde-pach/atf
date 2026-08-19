# Somewhere ATF has not heard of

*Your things live in a queue, a CRM, an internal service — somewhere none of the shipped systems
reach.*

ATF ships `filesystem`, `shell`, `sql`, `http` and `browser`. You write a system when your things
have an interface of their own worth going through: an application's service layer, a client
library, an internal API. It is written once, by one person.

Two classes. `src/atf/systems/filesystem.py` is one of ATF's own, and it has the driver and the
shared shape both.

## The driver

```python
class Filesystem(Driver):
    """One root, and everything the three resources over it need to reach inside it."""

    class Settings(TypedDict):
        """What an environment configures, once, for all three."""

        root: str

    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings["root"]).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
```

A driver is the machinery: a connection, a client, a browser, a shell. Subclassing registers it
under its own class name, so `Filesystem` is `filesystem` and `Sql` is `sql`. One is built per
environment from the `atf.yaml` block of that name, which arrives as `settings` and is checked
against `Settings` before a run.

A driver is also what a step or a Python test can ask for by parameter name.

## The resource

```python
class Under(Resource):
    """What the three share: a root, and one path inside it."""

    #: A thing under a root is its path. There is no second way to recognise one.
    path: Resource.Key[str]

    filesystem = DriverProperty[Filesystem]("filesystem")

    def _resolve(self) -> Path:
        ...


class File(Under):
    """One file, and the text in it."""

    text: Any = ""

    def find(self) -> Payload | None:
        path = self._resolve()
        if not path.is_file():
            return None
        return {"path": self._here(path), "kind": "file", "text": path.read_text(encoding="utf-8")}
```

`create`, `update` and `delete` sit beside it and are the same shape: do the thing, and answer
with the record. All four read `self` — a system reads its own declared fields the plain way,
`self.path`, exactly as a suite does.

`register_system(File, Filesystem, "file")`, called once at the bottom of the module, is what
`class Under(Resource)` on its own is not: `Under` names no driver and stays undeclared — a base
other resources build on, not a thing a suite can make — while `File`, `Directory` and `Tree` each
register themselves as `filesystem.file`, `filesystem.directory`, `filesystem.tree`. A suite then
subclasses one of those, from `atf.resources.filesystem`, and names both the shape and the system
at once: `class Note(File): ...`.

`find` is the one every resource answers. It returns the record, or `None` where there is nothing
there; raising `Unreachable` is the third answer, held apart from absence so a service that is down
never reads as a service with nothing in it. `create`, `update` and `delete` are what a thing ATF
makes needs — a thing that is only ever looked at writes `find` and stops.

`DriverProperty[Filesystem]("filesystem")` is how `self.filesystem` resolves to the actual driver
built for whichever environment the suite is running against — read off the active run, so nothing
threads a driver through by hand.

## What recognises one

```python
path: Resource.Key[str]
```

Said once, on the field, in the vocabulary of the thing that has to honour it — a `Resource.Key`
here, a `Row.Key` for a database row, the same mechanism either way. A composite key is more than
one field marked this way. `sql.row` used to work this out for itself, asking the database what it
held unique; that dynamic discovery is gone now — a suite declares `Row.Key[str]` the same as
everywhere else, and a table that once needed no schema-reading now needs none read either.

## The rest of what a resource carries

`self.meta` is where the two things ATF itself computes about the thing live, off to one side of
the suite's own fields: `meta.key` is the `Key` field's value (or a dict, for a composite one), and
`meta.body` is the declared fields with a parent flattened to what it was last found or made as.
They live under one name rather than two bare ones on purpose: a suite field called `key` or `body`
is entirely plausible — a license key, a request body — in a way `find`/`create` rarely are. Only
five names are reserved on every declared class: the four methods, and `meta`.

A URL path or a table name is a different kind of thing — one system's own setting, not ATF's, so
it does not live under `meta` at all. `Record`/`Row` each declare a plain `at: ClassVar[str]` and
their own `__init_subclass__` to catch `at=` off the class statement, exactly the way `id_field`
and `parent_suffix` are declared — `class Owner(Record, at="/owners")` reads the same as before,
but nothing about `at` is written into `declare.py`. A system inventing its own per-class setting
follows the identical pattern, and never has to touch ATF's own code to do it.

A record with a quirk overrides one of the four methods directly, next to its own declaration,
rather than a system growing another option to anticipate it — an API whose listings come back
wrapped, say, overrides `find` (or, narrower, whichever private method it builds `find` from) once,
in the suite, without anyone else's declaration knowing.

## The rest, when you need it

Four more methods are read off the class where you write them, and each one buys something:
`browse` makes `Then there are 2 files` say something; `find_many` answers about several in one
round trip; `check` refuses a declaration before a run; `begin` and `rollback` wrap a test in a
transaction on the *driver*, not the resource.

## Does it hold?

The behaviour every resource is held to ships with ATF as a feature file, run like any other test:

```console
$ atf run --contract -k contract
0 failed, 1 passed, 0 skipped   (r-7b6833)
```

For one thing of every kind the environment owns, it checks that a thing nothing made reads as
absent, that `create` answers with the record it wrote, that what `create` wrote is what `find`
reads back, that `update` writes what it is handed, that `delete` takes the thing away, and that
deleting a record already gone stays quiet — which is what a killed run leaves behind for the next
one.

It works on a copy marked with a value nothing else uses and removes that copy either way. It
writes, so it needs an environment ATF owns and each copy's lineage present in it; a kind whose
parent is absent is reported as such by name.
