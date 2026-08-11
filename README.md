# ATF — Another Test Framework

**Preconditions are declared as data rather than executed as setup code.** Declaring them buys a
graph the framework holds — what depends on what, and which tests need which things — and that graph
is what no other test framework has.

```python
# resources.py
from atf import sql      # your suite's adapter, not ATF's


@todo.owner()
class Owner:
    email: str


@todo.list(depends_on=[Owner])
class TodoList:
    slug: str


primary   = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

```gherkin
Scenario: a list shows under its owner
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"
```

Nothing says "owners before lists". `depends_on` does, and one sentence pulls the whole chain: the
owner is made, then the list, then the test runs.

## The same thing as a pytest function

```python
def test_a_list_shows_under_its_owner(groceries: TodoList, shell):
    result = shell(f"todo show {groceries.owner.email}")
    assert "groceries" in result["output"]
```

Neither is a re-implementation of the other. **A resource is a pytest fixture**, and the scenario and
the function reach the same engine — which is the claim the project is built to keep.

## What that buys

Because the dependency is declared rather than executed, these answer without running a test:

```console
$ atf status local          # present · absent · unreachable, asked of the environment now
$ atf impact groceries      # what breaks if that changes, resources and tests together
$ atf unused                # what nothing asks for
$ atf run --select +primary # only the tests that reach it
```

**Presence is asked, never remembered.** There is no state file, so a row deleted by hand or a
database reset overnight gives the right answer immediately.

## Getting started

```console
$ atf init                  # a manifest, an empty resources.py, an empty specs/
$ atf status local          # where each resource stands
$ atf make local            # make what is missing
$ atf run                   # run the tests, record the run
$ atf edit                  # the same answers, in a browser
```

Three exit codes and no fourth: `0` passed, `1` a test failed, `2` the run never started. The reason
travels in the message, and `--json` carries a machine-readable code for anything that wants to
branch on why.

## The systems it ships

`file`, `directory`, `tree`, `page`, `process`, `rest` and `sql`. **There is no backend and never
was** — ATF is pointed at whatever a team already has. `sql` is the one exception the argument
allows: every documentation example declares rows in a table, so the rows in a table are shipped.
It takes a `path` to a database file or a `url` to one elsewhere, and reads the driver off the
scheme. Anything else is an adapter somebody writes:

```python
@adapter("redis")
class Redis:
    def find(self, resource): ...
    def create(self, resource): ...
    def update(self, resource, found, changes): ...
    def delete(self, resource, found): ...
```

That ships `@redis(...)` with it, and the editor renders it — a catalogue entry, a graph node, a
composer sentence — without a line of editor code changing. `@sql.row` throughout the documentation
is exactly this: the worked example, living in the suite that uses it.

`atf verify-adapter <resource>` puts one through the contract — create, read back, update, delete,
and delete again — against a copy it marks and removes.

## How ATF tests itself

ATF's own suite is an ATF suite. `atf.yaml` at the root, `tests/resources.py`, scenarios under
`tests/specs`. It scaffolds a small suite on disk, starts `atf edit` over it, opens a page in a real
browser and drives the `atf` command against it — using four of the five shipped systems and no
adapter of its own.

```console
$ atf run
62 passed
```

Run it twice. One green run says nothing about residue.

## Conventions

Four, and they are conventions rather than tests. Some were tests that read ATF's own source with a
regular expression, which is a linter's job wearing a test's costume.

- **No hardcoded credentials, and no blanket `type: ignore`.** Enforced by ruff (`S105`–`S107`,
  `PGH`), named in `pyproject.toml`.
- **No literal `http://` or `https://` under `src/atf/`.** A host belongs in a manifest, behind a
  `*_env` pointer. Review's job.
- **The scaffold must run green.** CI scaffolds a suite with `atf init` and runs it with nothing
  else set up, because that is what a newcomer is handed.
- **A comment says what a scope is or what a function does.** Not why it is that way, not what it
  replaced, not what else was considered. A decision that needs recording is a commit message, where
  it is read by whoever asks why rather than by everyone who asks what. Enforced mechanically for
  length and for the phrases that always mean rationale — `uv run python scripts/prose.py`, in CI
  beside `ruff check`, which itself holds a docstring to a one-line summary (`D200`, `D205`, `D400`)
  — and the rest is review's job.

The documentation is MkDocs Material, organised by [Diátaxis](https://diataxis.fr), and built with
`--strict` in CI.

## Reading further

- [Documentation](docs/index.md) — the model, a tutorial, how-to guides, and reference
- [`docs/advanced/how-atf-tests-itself.md`](docs/advanced/how-atf-tests-itself.md) — the suite above,
  shown whole
- [`examples/`](examples) — a SQLite suite, the same domain over HTTP, and the shipped systems alone

```console
$ uv run --group docs mkdocs serve
```
