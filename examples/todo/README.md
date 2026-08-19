# The Todo API

The example the documentation is written against. A FastAPI application over SQLAlchemy models on
SQLite, and the ATF suite that tests it.

```bash
uv run --project ../.. atf run
```

Nothing has to be started first. The API is a declared thing, so the run starts it, waits for the
port, and stops it at the end.

## The application

`models.py`
:   Three SQLAlchemy models — owners, lists, tasks — and `open_database`, which creates the tables.

`api.py`
:   The routes. Owners and lists are created, filtered, patched and deleted over HTTP; tasks have no
    endpoint at all.

## The suite

`atf.yaml`
:   `local` says `owner: atf`, so ATF may make things there. `theirs` inherits it with `owner: them`,
    so ATF may only look.

`atf/things.py`
:   `Owner` and `TodoList` subclass `Record`, the shape an HTTP API owns. `Task` is the row the API
    has no endpoint for, so it subclasses `Row` instead. Both come from `atf.resources`, both ship
    with ATF, and both are configured in the same environment. `Owner`/`TodoList` also share a small
    override, `Listed`, for the one thing this particular API does its own way: a listing comes back
    wrapped as `{"items": [...]}`.

`atf/words.py`
:   One `@act` and one `@check` — the sentences this suite adds.

`atf/lists.feature`
:   Eight scenarios and two phrases.

`atf/test_lists.py`
:   Three Python tests, arranging through the same resolver the scenarios do.

## Two systems, one domain

`Task.todo_list` points at a `TodoList` the API owns, so arranging a task creates its list over HTTP
and then writes the row. Teardown runs the other way: the row goes, then the list, then the process.
