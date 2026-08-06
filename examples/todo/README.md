# The todo suite

The canonical domain, as a suite that loads. It is the worked example the documentation is written
against: a 25-line command line over SQLite, an adapter the suite owns, and the resources a test
needs.

## What is here

`todo.py`
:   The product under test. Not part of ATF.

`adapters/sqlite.py`
:   The worked example of an adapter. `sqlite` is **not** part of ATF — ATF ships `command`,
    `browser`, `filesystem` and `process`, and nothing that binds it to one database.
    `@adapter("sqlite")` ships the `@sqlite(...)` decorator with it, which is why `resources.py`
    imports one line and gets a decorator.

`resources.py`
:   What must exist before a test runs. Every dependency is written with `depends_on` — including
    `Report`'s, which has no field to hold an owner and needs one anyway.

`atf.yaml`
:   Five top-level keys, and `mutable` per environment. `local` says ATF may change it; `staging`
    does not say so, so it may not.

## Reading the graph

Nothing below touches the database, or any network. Declaring is data, so the graph is answerable
before anything exists.

```bash
cd examples/todo
uv run python -c "
from atf import load_suite, closure, dependents, unused, name_of
suite = load_suite()
print('kinds    :', sorted(suite.kinds))
print('instances:', sorted(suite.instances))
print('closure  :', [name_of(r) for r in closure(suite.resource('laundry'))])
print('impact   :', [name_of(r) for r in dependents(suite.resource('primary'), suite.instances.values())])
print('unused   :', [name_of(r) for r in unused(suite.instances.values())])
print('order    :', [name_of(r) for r in suite.order])
print('unmet    :', [str(u) for u in suite.unmet])
"
```

```text
kinds    : ['Guest', 'Owner', 'Plan', 'Report', 'Task', 'TodoList']
instances: ['free', 'groceries', 'laundry', 'primary', 'quarterly', 'visitor']
closure  : ['primary', 'groceries', 'laundry']
impact   : ['groceries', 'laundry', 'quarterly']
unused   : ['laundry', 'quarterly', 'free', 'visitor']
order    : ['primary', 'groceries', 'laundry', 'quarterly', 'free', 'visitor']
unmet    : []
```

`closure laundry` is the ordering nobody wrote down. Nothing in the suite says "owners before
lists"; the graph does, off `depends_on`.

## Making it, for real

```bash
cd examples/todo
python todo.py show nobody@example.com   # the app creates its own tables on first run
uv run python -m atf make local
```

```text
primary    present  created  changes: email
groceries  present  created  changes: slug
laundry    present  created  changes: done, slug
quarterly  present  created  changes: body, slug
free       absent  left alone  (it is declared `when_absent="require"`, and local does not have it)
visitor    present  created  changes: nickname
```

`free` is a `Plan`, and the `plans` table is deliberately left empty: `when_absent="require"` is for
something the environment owns, so ATF names it rather than making one. The exit code is `1`.

Run it again and every line reads `unchanged` — **reconciliation is silent when nothing differs**,
because presence is asked rather than remembered.

## Reconciliation, and what an immutable environment refuses

Change a value behind ATF's back, the way the product would:

```bash
uv run python -c "import sqlite3; d=sqlite3.connect('todo.db'); d.execute(
  \"UPDATE tasks SET done=1 WHERE slug='laundry'\"); d.commit()"

uv run python -m atf status local laundry     # laundry  present  updated  changes: done
uv run python -m atf make readonly laundry    # left alone  (the readonly environment is not mutable)
uv run python -m atf make local laundry       # updated  changes: done
```

`readonly` is the same database with no `mutable: true`. It says what *would* change and changes
nothing — which is the answer the editor shows before anything is pressed.

## Two surfaces, one engine

`specs/` holds the same behaviour written both ways.

```gherkin
Scenario: a list shows under its owner
  Given the todo_list "groceries"
  When I run "show primary@example.com"
  Then the result field "exit_code" is "0"
  And the result field "output" contains "groceries"
```

```python
def test_a_list_shows_under_its_owner(groceries: TodoList, shell):
    result = shell(f"show {groceries.owner.email}")
    assert result["exit_code"] == 0
    assert "groceries" in result["output"]
```

Neither is a re-implementation of the other. `Given the todo_list "groceries"` and the `groceries`
parameter both end in the same `reconcile.ensure`.

```bash
cd examples/todo
python todo.py show x            # the app creates its own tables on first run
uv run pytest                    # 14 passed
uv run pytest                    # 14 passed again — persistent resources are recognised, not remade
```

Run it twice on purpose. One green run says nothing about residue: the function-scoped `visitor` has
to be gone afterwards and `groceries` has to still be there, and only the second run proves it.

## What the collection pass refuses

`refused/` holds mistakes ATF catches **before a single test body runs** — an ambiguous parameter in
a scenario and in a function, and a kind with no factory. See its README for the messages.

## What does not work yet

The command line proper — `atf` rather than `python -m atf`, with `--json`, `--select`, the report
registry and history — is Phase 4. The editor is Phase 6.
