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

## The example is the one you are given

There is no sample project in this repository, deliberately. A checked-in example is a second thing
to keep green, it drifts from what the tool actually produces, and a fake API proves nothing about a
real one. What `atf init` writes *is* the worked example — a manifest, a two-level catalog with a
placeholder, a custom adapter, a feature and a stand-in backend — and it is the one thing that
cannot drift, because it is what every new suite starts as:

```sh
mkdir my-suite && cd my-suite
atf init
atf run            # green as it stands, against the stand-in backend
atf serve          # the cockpit, over your own suite
```

Then point `ATF_URL` at something real and delete `fake_backend.py`.

## Developing ATF

```sh
uv sync
uv run ruff check
uv run ty check             # strict, zero suppressions
uv run pytest -q            # the framework's own tests; no network
```

`tests/` is one directory holding both layers, and one `pytest` run covers them together:

- **An ATF suite whose system under test is ATF** — its resources are real consuming suites on
  disk and a running cockpit, and its scenarios drive the real `atf` command against them. See
  `tests/README.md`. It is itself mutation-tested, so a regression in ATF turns it red.
- **Python tests for what a scenario cannot watch** — a parser, a truth table, a run observed
  while it is in flight, a request refused. Every one of those modules opens with a docstring
  saying which it is and why it did not become a scenario; that split is the rule, not a habit.

### Constraints the tests enforce

Four, and each has an acceptance test because each has caught a real mistake:

- **No `type: ignore` and no `noqa: F...` anywhere under `src/atf/`.** A suppression is a claim
  nobody checks.
- **No literal `http://` or `https://` under `src/atf/` except `scaffold.py`.** A host belongs in a
  manifest, behind a `*_env` pointer.
- **No Node, no build step, one semantic CSS file.** The cockpit is server-rendered with htmx
  vendored into `src/atf/cockpit/static/`. A build step is a thing that breaks between you and a
  green suite.
- **The scaffold must run green.** CI scaffolds a suite with `atf init` and runs it with nothing
  else set up, because that is what a newcomer is handed.

The documentation is MkDocs Material, organised by [Diátaxis](https://diataxis.fr), and built with
`--strict` in CI:

```sh
uv run --group docs mkdocs build --strict
```
