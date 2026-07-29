# CLI reference

```
atf [-h] {init,serve,seed,status,run,lint,docs,import-run} ...
```

Every command except `init` locates the manifest as described in the
[manifest reference](manifest.md#resolution).

## Exit codes {#exit-codes}

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | The command ran and reported failure: a failing test, or a resource that could not be provisioned. |
| `2` | The command did not run: a configuration or catalog error, an unknown environment, a refused mutation, or invalid arguments. |
| `130` | Interrupted. |

## `atf init` {#atf-init}

```
atf init [directory]
```

Writes a starter suite: the manifest, a catalog with a small type registry and its instances, an
adapter stub, a `conftest.py` enabling the plugin, a `specs/` tree with one feature and its steps,
a client for the system under test, a stand-in for that system so the suite runs immediately, plus
a `.gitignore` and a `README.md`.

Existing files are never overwritten. Files already present are skipped, and the command reports
which were written.

### `directory` {#init-directory}

Where to write. Defaults to the current directory, and is created if absent. The directory name
becomes the suite name in the generated `README.md`.

`init` does not read [`ATF_MANIFEST`](#atf_manifest) — it writes a manifest rather than finding one.

## `atf serve` {#atf-serve}

```
atf serve [--env ENV] [--host HOST] [--port PORT]
```

Runs the [cockpit](cockpit.md) under uvicorn, printing a banner that names the URL, the absence of
authentication, and the environments listed in `mutable_envs`.

### `--env` {#serve-env}

The environment shown on first load. Defaults to [`ATF_ENV`](#atf_env), else the manifest's
`default_env`. Every page can switch environment afterwards.

### `--host` {#serve-host}

The interface to bind. Defaults to `127.0.0.1`. Any value other than `127.0.0.1`, `localhost` or
`::1` also prints a warning to stderr, because the cockpit has no authentication.

### `--port` {#serve-port}

The port to bind. Defaults to `8000`.

## `atf seed` {#atf-seed}

```
atf seed ENV [--type TYPE] [--name NAME] [--keep-going]
```

Provisions resources into `ENV`, dependencies first, printing one line per node with its action —
`created`, `exists`, `reference`, `blocked` — or its failure, then a tally.

Exits 1 when any resource failed to provision.

### `ENV` {#seed-env}

**Required.** The environment to provision into. It must appear in
[`mutable_envs`](manifest.md#mutable_envs); otherwise the command exits 2 and changes nothing,
naming the environments that are allowed.

### `--type` {#seed-type}

Restrict to one resource type. Exits 2 for a type that is not in the catalog, listing the ones that
are.

With neither `--type` nor `--name`, every **persistent** resource is provisioned and ephemeral ones
are skipped — nothing would tear them down, so seeding one creates an orphan. Naming an ephemeral
type explicitly provisions it anyway.

### `--name` {#seed-name}

Restrict to one instance of `--type`. Requires `--type`; exits 2 without it, and exits 2 when no
instance of that type has the name.

The selected resources are provisioned together with their dependencies, so naming a leaf pulls in
everything beneath it.

### `--keep-going` {#seed-keep-going}

Attempt independent resources after a failure instead of stopping at the first.

Without it, the first failure ends the pass and the remaining resources are not attempted; the
output says how many were skipped. That is the default because provisioning failures are usually
correlated — a bad token or an unreachable backend fails every resource, and reporting it once is
clearer than reporting it two hundred times.

With it, a failed resource's dependents are reported `blocked` and never attempted, while unrelated
resources are still provisioned. Use it when you believe the failures are independent.

To see every problem without changing anything, use [`atf status`](#atf-status) instead.

## `atf status` {#atf-status}

```
atf status ENV
```

Prints one line per resource with its status, then a summary counting present resources against the
persistent total.

Read-only, and permitted in any environment — it never provisions, so it is the safe first question
to ask about production.

### `ENV` {#status-env}

**Required.** The environment to inspect. Unlike `seed`, it need not be mutable.

### Status words {#status-words}

| Status | Meaning |
|---|---|
| `present` | Found in the environment. |
| `absent` | Not found. |
| `ephemeral` | Built per run; not looked up. |
| `unsupported` | No adapter is configured for that resource's system in this environment. |
| `error` | The adapter raised while looking it up. The message follows on the same line. |

## `atf run` {#atf-run}

```
atf run [paths ...] [--env ENV] [-k EXPR] [--tag TAG] [--failed] [--json PATH]
```

Runs the specs in a subprocess with the environment set, then prints one line per test with its
outcome and duration and a summary. For a test that failed, it also prints the **Gherkin step the
run reached** and the last line of the failure:

```
  [ failed] specs/steps/test_lists.py::test_completing_a_task_marks_it_done  0.03s
           at: Then the task "laundry" field "done" is "true"
           Failed: task 'laundry' field 'done' is false (a true/false value), not "true"
```

The results are added to the [run history](cockpit.md#run-history). Writing that history is
best-effort — a read-only checkout still runs.

Exits 1 if pytest exits non-zero — a failing test, but also a collection error, a missing step
definition or a usage error. Suitable as a CI gate; read the output to tell which.

### `paths` {#run-paths}

pytest node ids or paths to run. Defaults to the manifest's `specs` directory, which is the whole
suite.

```sh
atf run specs/steps/test_checkout.py
atf run 'specs/steps/test_checkout.py::test_a_basket_is_priced'
```

### `--env` {#run-env}

The environment to run against. Defaults to [`ATF_ENV`](#atf_env), else the manifest's
`default_env`.

### `-k EXPR` {#run-k}

Only scenarios whose name matches. **A plain phrase is read as a phrase** — the words a person would
actually type, flattened the way a scenario's title becomes a test name:

```sh
atf run -k 'belongs to its owner'      # runs A list belongs to its owner
```

Text containing `and`, `or`, `not` or a bracket is passed to pytest untouched, because that is
somebody deliberately writing an expression:

```sh
atf run -k 'lists and not slow'
```

### `--tag TAG` {#run-tag}

Only scenarios carrying the tag. Repeatable, and several tags mean **any** of them — `--tag smoke
--tag api` reads as *"the smoke ones and the api ones"*, which is a union. The `@` is how a tag is
written on a scenario rather than part of its name, so both spellings work.

```sh
atf run --tag smoke --tag @api
```

A choice that matches nothing says so, rather than leaving an exit code to be interpreted.

### `--failed` {#run-failed}

Only what did not pass in the **last run against this environment**, read from the
[run history](cockpit.md#run-history). The dev loop it exists for is: run everything, fix one thing,
run only that.

- Nothing failed last time → says so and exits `0`. A green suite must not look broken.
- Nothing has ever run here → exits `2` saying to run once first. Silently running everything
  would be a lie about what was asked for.
- It takes no `paths`: it already says which tests to run.

### `--json PATH` {#run-json}

Also writes the run to `PATH` as [CTRF](https://ctrf.io) — the interchange format the tooling around
test runs has settled on. A format nobody else reads is a format every consumer has to be taught, so
a gate written for CTRF works against ATF without being taught anything.

An `error` — a test that never got to run its body — is reported as `failed`, because a gate that
treats *"it broke before it started"* as softer than a failure lets a broken suite through. The
Gherkin step a scenario stopped on travels in each test's `message`, which is the useful unit of
failure for a BDD suite and the first thing a person reading CI wants.

## `atf lint` {#atf-lint}

```
atf lint
```

Checks that no spec line says something only the layer below should have to know. Reads the
`.feature` files under [`specs`](manifest.md) and nothing else — no environment, no adapters, no
collection — so it runs in a checkout with no backend anywhere near it.

Exits `1` when there is anything to report, and prints the report on stderr, so CI can gate on it.

### The rules {#lint-rules}

| Rule | Catches | Say instead |
|---|---|---|
| `field-claim` | `field "<f>"` — a struct field access spelled in English | a [phrase](phrasebook.md): `the list "groceries" belongs to "primary"` |
| `status-code` | a quoted 3-digit code, `100`–`599` | what the code means here: `it is refused` |
| `path` | a quoted value starting `/`, or holding `://` | the thing at the end of it, named as the catalog names it |
| `cli-flag` | a quoted value holding a `--flag` | a phrase for what the flag makes the command do |
| `selector` | a quoted CSS-ish selector — `#id`, `.class`, `[role=…]`, `::`, `>` | the control's role and accessible name |

Only **step lines** are checked. The narrative and comments are where an author explains, and
explaining is allowed to be specific.

A **data table is a deliberate exception.** `Then the task "milk" is:` followed by a table of
fields is the [whole-shape claim](specs-and-fixtures.md#tables), and the rule exists to stop
technical detail being embedded in a sentence a reader has to parse. A table reads as data, sits
apart from the prose, and replaces the field-by-field assertions the rule is really aimed at.

### Waiving a rule {#lint-waivers}

A suite mid-migration has lines it already knows about, and a check that lands permanently red is a
check somebody turns off. A comment waives a rule for the line below it:

```gherkin
# atf-lint: ignore field-claim
Then the result field "exit_code" is "0"
```

The same comment **before `Feature:`** waives that rule for the whole file. Several rules can be
named at once, separated by commas. A waiver applies to the line directly beneath it and no
further, so it can never quietly cover something added later.

A waiver is a decision someone wrote down, which is the point: the rule is still there, and so is
the reason.

## `atf docs` {#atf-docs}

```
atf docs [--out DIRECTORY] [--env ENV]
```

Writes the suite's features out as markdown: one page per `.feature` file, plus an index over them.
Each page carries the feature's narrative, its `Rule:` headings, every
scenario as the lines it was written as, and what the [run history](cockpit.md#run-history) says
about it — `passing`, `failing`, `skipped` or `never run`, and for a failing one the step the run
reached and what it said there.

```
Wrote 3 pages under /path/to/suite/docs/specs:
  index.md
  features/checkout.md
  features/lists.md

2 features, 9 scenarios — 7 passing, 1 failing, 1 never run, as of the runs recorded against dev.
```

Read-only, and not gated by `mutable_envs`: it reads the feature files and the run history, runs
nothing, provisions nothing, and writes only under `--out`. Like [`atf lint`](#atf-lint) it never
collects the suite, so it works in a checkout with no backend anywhere near it — and for the same
reason it does not read the catalog, so a page about what the specs say cannot fail because of a
resource type it was never asked about.

Exits `0` when there is nothing to write, saying so — a suite with no scenarios yet is not an error.

### `--out` {#docs-out}

Where the pages go. Defaults to `docs/specs`, relative to the suite root; an absolute path is used
as given. Each page sits at the same place in the tree its feature does under
[`specs`](manifest.md), so `specs/features/checkout.feature` becomes `features/checkout.md`.

Files are overwritten and never deleted: a feature that was renamed leaves its old page behind, for
you to remove.

### `--env` {#docs-env}

Whose run history the verdicts come from. Defaults to [`ATF_ENV`](#atf_env), else the manifest's
`default_env`; an unknown name exits 2, listing the environments that exist.

A verdict is only ever a verdict *somewhere* — a scenario that passes against `dev` and fails
against `staging` is the normal case — so every page names the environment it is reporting.

### Committing the output {#docs-committing}

The pages are ordinary files, so they can be generated into a docs site and committed. There is
deliberately **no `--check`**: the verdicts come from a run history that lives on the machine that
ran the tests, so a staleness gate in CI would fail for the one reason that is not the author's
fault. Regenerate after a run, and review the diff like any other.

If the site is mkdocs with `--strict`, add the generated pages to `nav` — or point `--out` at a
directory a nav-generating plugin covers.

## `atf import-run` {#atf-import-run}

```
atf import-run ENV REPORT.json
```

Reads a pytest JSON report and records it in the [run history](cockpit.md#run-history) as a run
against `ENV`, so a build machine's results appear in the cockpit alongside local ones — including
in the last-outcome and [flaky](../explanation/glossary.md#flaky) calculations.

The report is the one `pytest-json-report` writes:

```sh
pytest --json-report --json-report-file=report.json -q
atf import-run staging report.json
```

```
Imported 8 results into staging: 7 passed, 1 failed, 0 skipped, 0 errored.
Stored as run <id> in /path/to/suite/.atf/runs
```

This writes to `<suite root>/.atf/runs/`; it does not touch the environment, so it is not gated by
`mutable_envs`.

### `ENV` {#import-run-env}

**Required.** The environment the run was executed against. It must be a key of `environments`, and
ATF cannot infer it from the report — filing a staging run under `dev` would make the cockpit lie.
An unknown name exits 2, listing the environments that exist.

### `REPORT.json` {#import-run-report}

**Required.** Path to the JSON report. Exits 2 if it is missing, or holds no test results — which is
usually a sign it is not a `--json-report` file.

## Environment variables {#environment-variables}

### `ATF_MANIFEST` {#atf_manifest}

Path to the manifest, bypassing the upward search. Read by every command except `init`. Pointing it
at a path that does not exist is an error.

### `ATF_ENV` {#atf_env}

The active environment, unless `--env` is given. Read by `serve`, `run` and `docs`.

`seed`, `status` and `import-run` take the environment as a required positional argument and ignore
this variable — a command that changes an environment, or files a result against one, should say
which on the command line.

### Manifest pointers {#manifest-pointers}

Every `*_env` key in the manifest names an environment variable that must be set. All commands read
them at startup, before touching anything. An unset one is an error naming both the key and the
variable. See [environment-variable pointers](manifest.md#environment-variable-pointers).

## Where to go next

- [How to run ATF in CI](../how-to/run-atf-in-ci.md) — these commands as a deployment guard.
- [1. Your first spec](../tutorial/your-first-spec.md) — them in order, on a suite that works.
- [Manifest reference](manifest.md) — the file every command reads.
- [Cockpit reference](cockpit.md) — what `atf serve` starts.
