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
- **Cockpit** — a FastAPI + htmx web app that renders the catalog, the scenarios and the run
  history, provisions what is missing, runs tests with live progress, and answers *"can I ship?"*

The engine, spec plumbing, discovery and cockpit are generic. A project supplies only content
(catalog + specs), adapters (how to talk to its systems), and a manifest.

## Documentation

The full documentation — a three-lesson tutorial, how-to guides, reference and explanation — lives
in [`docs/`](docs/index.md) and is published at <https://mde-pach.github.io/atf/>.

| If you want to… | Read |
|---|---|
| Get something running in ten minutes | [Your first spec](docs/tutorial/your-first-spec.md) |
| Know what the words mean | [Glossary](docs/explanation/glossary.md) |
| Understand what actually happens | [Life of a run](docs/explanation/life-of-a-run.md) |
| Look up a key or a flag | [Reference](docs/index.md#reference) |
| Work out why something is red | [Find out why an environment is red](docs/how-to/find-out-why-an-environment-is-red.md) |

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
atf run
```

`atf init` writes a manifest, a starter catalog, an adapter stub, a working spec, and a stand-in for
the system under test — so the suite runs before you have a service to point it at.

```sh
atf status dev      # what exists in the environment, per resource
atf seed dev        # make the absent resources exist
atf run             # run the specs; nonzero exit on failure (use as a CI guard)
atf serve           # the cockpit on http://127.0.0.1:8000
```

Every command and flag is in the [CLI reference](docs/reference/cli.md).

## Security

The cockpit performs mutating actions against real environments and has **no built-in
authentication**. It binds `127.0.0.1` by default, gates every mutation behind the manifest's
`mutable_envs` allow-list, and requires a confirmation token. For shared access, put it behind an
authenticating reverse proxy. See the [cockpit reference](docs/reference/cockpit.md#security).

## Limits

v1 is **single-worker**: the session materializer, its listing cache and get-or-create are not safe
under parallel workers, and the cockpit serializes runs with one active job per environment. Do not
enable `pytest-xdist`. See [concurrency](docs/reference/specs-and-fixtures.md#concurrency).

## The example

`examples/todo/` is a complete suite exercising every seam — REST resources with composite, scoped
and datetime natural keys; a reference resource; a custom ephemeral adapter with teardown; two
feature files; a read-only environment — against a tiny in-process fake API, so it runs with no
backend:

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

The documentation is MkDocs Material, organised by [Diátaxis](https://diataxis.fr), and built with
`--strict` in CI:

```sh
uv run --group docs mkdocs build --strict
```
