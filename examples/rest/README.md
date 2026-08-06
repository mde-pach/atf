# The same domain, owned by an HTTP API

`examples/todo` declares `Owner` and `TodoList` against SQLite. This declares the same two against a
REST API. **Read the two `resources.py` side by side**: `depends_on` is identical, `unique_by` is
identical, and only the decorator and its options differ. That is the whole claim a system makes.

## Uniqueness and lookup are two different questions

`api.py` is deliberately awkward in one way: an owner is *unique* by email and *fetchable* only by a
numeric id nobody writing a test knows.

```python
@rest(path="/owners", unique_by="email", list_filter=["email"], collection_key="items")
class Owner:
    email: str
```

`unique_by` says which owner this is. `list_filter` says the API will take that field as a query
parameter, so `find` asks `GET /owners?email=…` and matches. Declare `read_path` instead and it
reads the address directly; declare neither and it scans the collection, which needs the API to
support nothing at all.

## Running it

The API is itself a declared resource, so nothing has to be started by hand.

```bash
cd examples/rest
uv run python -m atf run          # 3 passed
uv run python -m atf run          # 3 passed — recognised, not made again
```

```python
@process(command="python api.py", port=8799, scope="session")
class Api:
    """Started for the run, stopped when it ends."""
```

`port=8799` is what makes it safe: the process is not *made* until the port answers, so nothing
downstream races it. `scope="session"` means it is gone afterwards — check with `pgrep -f api.py`.

## Reconciliation over HTTP

```bash
uv run python -m atf make local
curl -s -X PATCH localhost:8799/lists/1 -d '{"colour":"blue"}' -H 'Content-Type: application/json'
uv run python -m atf make local          # unchanged — `colour` is nobody's declaration
```

A declaration is a partial specification: the fields you named must hold, and `colour` survives
untouched. Rename `slug` instead — the recognised field — and ATF reports the resource `absent`,
because a renamed recognised value is a different resource, not the same one renamed.
