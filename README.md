# ATF — Another Test Framework

A test is a readable spec that declares the resources it needs, and the framework makes those
resources exist before the test runs.

```gherkin
Scenario: A list belongs to its owner
  Given the owner "primary"
  And the todo_list "groceries"
  When I list the owner's lists
  Then the list "groceries" is among them
```

`Given the owner "primary"` is not something you wrote. The owner is a node in a YAML catalog;
ATF resolves it, provisions its whole dependency chain into the target environment, and hands the
record to your step. Add a resource and it is a YAML node. Add a spec and it is Gherkin. Tests
and fixtures follow automatically.

## The four moving parts

- **Catalog** — resources declared as plain YAML with dependency lineage. Purely declarative.
- **Materializer** — provisions a resource and its closure into an environment, idempotently,
  delegating the *how* to a pluggable adapter per backend.
- **Specs** — pytest-bdd scenarios. Each resource type becomes a generated pytest fixture; one
  generic step provisions any resource named in a scenario.
- **Cockpit** — a FastAPI + htmx web app that discovers the catalog, specs, tests and fixtures,
  shows how they link, runs tests with live progress, and answers *"can I ship?"*

The engine, spec plumbing, discovery and cockpit are generic. A project supplies only content
(catalog + specs), adapters (how to talk to its systems), and a manifest.

## Documentation

A tutorial, how-to guides, reference and explanation live in [`docs/`](docs/index.md). New to ATF?
Start with [Write your first spec](docs/tutorial/write-your-first-spec.md).

To read them as a site, with navigation and search:

```sh
uv run --group docs mkdocs serve      # http://127.0.0.1:8000/atf/
```

## Install

ATF is not on PyPI yet; install it from the repository:

```sh
uv add git+https://github.com/mde-pach/atf     # or: pip install git+https://github.com/mde-pach/atf
```

## Start a suite

```sh
atf init my-suite
cd my-suite
```

That writes a manifest, a starter catalog, an adapter stub, and a working spec:

```
my-suite/
  atf.yaml                    # config: environments, adapters, mutable_envs
  catalog/
    resources.yaml            # resource types
    accounts.yaml             # instances
  adapters.py                 # custom adapters (optional)
  specs/
    features/*.feature        # scenarios
    steps/test_*.py           # scenarios() binding + your When/Then vocabulary
    api.py                    # the system-under-test client
  conftest.py                 # pytest_plugins = ["atf.plugin"]
```

## Commands

```sh
atf status dev      # what exists in the environment, per resource
atf seed dev        # make the absent resources exist
atf run             # run the specs; nonzero exit on failure (use as a CI guard)
atf serve           # the cockpit on http://127.0.0.1:8000
```

## How a spec gets what it needs

```yaml
# catalog/resources.yaml — the type
todo_list:
  system: rest
  path: /lists
  natural_key: [owner_id, slug]

# catalog/lists.yaml — an instance
groceries:
  resource: todo_list
  represents: The primary owner's shopping list.
  depends_on: [owners.primary]
  body:
    slug: groceries
    owner_id: ${owners.primary.id}      # resolved at provision time
```

`Given the todo_list "groceries"` walks the dependency graph, get-or-creates the owner, resolves
`${owners.primary.id}` to the real identity, get-or-creates the list, and stashes the record on
`context.todo_list`. The only code you write is the vocabulary:

```python
@when("I list the owner's lists")
def _(context, api):
    context.result = api.lists_of(context.owner)
```

## Adapters

An adapter is how ATF talks to one backend. Two ship built in:

- **`rest`** — configurable get-or-create over a JSON API: natural keys (single, composite or
  scoped), pagination, `none`/`header`/`bearer`/`session` auth, retries, custom identity fields.
- **`reference`** — find-only, for resources that must already exist.

Anything else is one class and one registered factory:

```python
class GuestAdapter:
    def find(self, node, ctx): ...      # the live record, or None
    def create(self, node, body, ctx):  # may run any multi-step chain
        ...
    def delete(self, node, record, ctx): ...   # best-effort teardown

register("guest", GuestAdapter)
```

A new backend is one adapter plus manifest config. The engine never changes.

## Lifecycles

- **persistent** (default) — find-or-created, reported present/absent, left in place.
- **ephemeral** — built fresh every run, returned from `ensure`, and torn down best-effort when
  the scenario ends.

## Security

The cockpit performs mutating actions against real environments and has **no built-in
authentication**. It binds `127.0.0.1` by default, gates every mutation behind the manifest's
`mutable_envs` allow-list (other environments render read-only and their routes return 409), and
requires a confirmation token for destructive actions. For shared access, put it behind an
authenticating reverse proxy.

## Limits

v1 is **single-worker**. The session materializer, its listing cache and get-or-create are not
safe under parallel workers, and the cockpit serializes runs with one active job per environment.
Do not enable `pytest-xdist`.

## The example

`examples/todo/` is a complete suite exercising every seam — REST resources with composite,
scoped and datetime natural keys; a reference resource; a custom ephemeral adapter with teardown;
two feature files; a read-only environment — against a tiny in-process fake API, so it runs with
no backend:

```sh
cd examples/todo
uv run pytest -q            # 8 passed
```

## Developing ATF

```sh
uv sync
uv run ruff check
uv run ty check             # strict, zero suppressions
uv run pytest -q            # the framework's own tests; no network
```

ATF is tested at two layers:

- **`tests/`** — unit and integration tests for each part (catalog validation, placeholder
  resolution, the materializer against a fake adapter, the REST adapter against a loopback stub,
  discovery, jobs, the cockpit). No network.
- **`selftest/`** — ATF tested *with* ATF: an ATF suite whose resources are real consuming suites
  on disk and whose system under test is the `atf` CLI. See `selftest/README.md`; the suite is
  itself mutation-tested, so a regression in ATF turns it red.
