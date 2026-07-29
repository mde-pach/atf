# CLI reference

```
atf [-h] {init,serve,seed,status,run,lint,docs,import,import-run} ...
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
atf serve [--env ENV] [--host HOST] [--port PORT] [--mcp]
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

### `--mcp` {#serve-mcp}

Also answer [MCP](https://modelcontextprotocol.io), at `/mcp/` on the same host and port, so an
agent can compose scenarios from this suite's own vocabulary — the
[introspection surface](cockpit.md#introspection). Off by default.

The SDK it needs is **not a dependency of ATF**: a framework should not decide that every suite
serves agents. Install it with `uv sync --group mcp`. Asked for `--mcp` without it, the command
prints what to install, exits 2, and starts nothing — a cockpit quietly missing the endpoint
somebody asked for would be found out by a client that could not connect, which says nothing about
why.

`run` over MCP is gated by [`mutable_envs`](manifest.md#mutable_envs), because running provisions.
Everything else the endpoint offers only reads.

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

Checks that the `.feature` files under [`specs`](manifest.md) are **well formed** — that each file
is the thing it claims to be. It reads the files and nothing else: no environment, no adapters, no
collection, so it runs in a checkout with no backend anywhere near it.

Exits `1` when there is anything to report, and prints the report on stderr, so CI can gate on it.

### The rules {#lint-rules}

| Rule | Catches | Why it matters |
|---|---|---|
| `no-feature` | a `.feature` with no `Feature:` line | it is collected and contributes nothing |
| `two-features` | a second `Feature:` in one file | everything after the first is ignored by every Gherkin reader |
| `untitled` | a keyword with nothing after the colon | the title is what the cockpit lists, a run reports, and `-k` matches |
| `stray-step` | a step before any `Scenario:` or `Background:` | nothing will run it where it is |
| `dangling-and` | an `And` or `But` with no step above it | there is nothing for it to continue |
| `empty-scenario` | a scenario with no steps | it passes without asserting anything |
| `outline-without-examples` | a `Scenario Outline:` with no `Examples:` | it runs zero times |
| `ragged-table` | rows with differing numbers of cells | the short rows lose their last values |
| `unknown-placeholder` | a `<name>` no `Examples:` column supplies | it reaches the step with its angle brackets on |
| `duplicate-scenario` | two scenarios in one feature with the same title | they generate one test name and one of them runs |

Every one is a fact about the file that is wrong in every domain, so **there are no waivers and
nothing to waive.**

### What it does not check, and why {#lint-not}

**The words.** An earlier version reported a spec line naming a field, a status code, a path, a flag
or a selector, on the grounds that the layer below had leaked into the layer above. That rule is
real — it is the reason the [phrasebook](phrasebook.md) exists — but it is not checkable, because it
infers *meaning* from *syntax*.

A quoted `/products/42` is a route escaping an adapter in one suite and the domain's own value in
another: a redirect target, a CMS slug, a router rule. `503` is an implementation detail here and
the entire subject matter of a monitoring product. Nothing separates the two but knowing what the
system under test *is*, which a linter does not. What the rule produced was false positives on
correct specs, a waiver comment per line, and a check that meant nothing.

Keeping technical vocabulary out of spec text is still the point of the
[phrasebook](phrasebook.md#why). It is a judgement, and it belongs to a reviewer.

## The rules {#lint-rules}

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

## `atf import openapi` {#atf-import-openapi}

```
atf import openapi [SOURCE] [--schema NAME] [--apply]
```

Derives resource types from an OpenAPI schema and writes them into
[`resources.yaml`](catalog.md#resource-types). It is the answer to the blank page: a catalog states
where each resource lives, what identifies one, and how it is reached, and a schema already says
most of that.

For every collection path in the schema it writes one type — its [`path`](catalog.md#path), its
[`id_field`](catalog.md#id_field), and a guessed [`natural_key`](catalog.md#natural_key) with the
reason it was guessed written beside it:

```yaml
account:
  system: rest
  path: /accounts
  id_field: id
  # guessed: `GET /accounts` filters by it, and its format is `email`
  natural_key: email
```

Read-only against every environment, and not gated by [`mutable_envs`](manifest.md#mutable_envs):
it writes your repository, not a backend. It does not load the catalog either — a registry too
broken to load is exactly the state you might be running this to get out of.

### `SOURCE` {#import-openapi-source}

A path or a URL. **Omit it** to read the schema named in the manifest under
[`schemas`](manifest.md#schemas), which is the form that makes re-importing after an API change a
command with nothing after it.

### `--schema NAME` {#import-openapi-schema}

Which entry under [`schemas`](manifest.md#schemas) to read, when the manifest names more than one.
With exactly one entry it is not needed; with none, and no `SOURCE`, the command exits 2 showing
the manifest key to add.

### `--apply` {#import-openapi-apply}

Write the proposal. Without it, nothing is written and the diff is printed for you to read.

**The first import writes without asking**, because a `resources.yaml` that declares no types is the
blank page this command exists to remove and there is nothing there to lose. Every import after
that stops at a diff: by then the file holds a `natural_key` you corrected and a `mode` you set, and
a generator that reverts those is a generator you cannot afford to re-run.

A re-import therefore **only ever adds**. Types already declared are left byte-for-byte alone; ones
whose `path` the schema has since moved, or whose `natural_key` names a field a create no longer
accepts, are reported as drift for you to fix; types the schema no longer mentions are named and
left. See [How to keep the catalog in step](../how-to/keep-the-catalog-in-step.md).

### How the natural key is guessed {#import-openapi-natural-key}

Deterministic scoring, strongest signal first. Nothing is fetched, nothing is learned, and the same
schema always produces the same answer.

| Signal | Why it is worth what it is |
|---|---|
| The collection endpoint **filters** by the field — `GET /accounts?email=` | the API stating *"you can find one this way"*, which is exactly what a natural key means to ATF |
| **Another type in your catalog is already keyed on that name** | your project's own convention, learned rather than assumed — correcting one guess by hand raises that name's score next time |
| `format:` or `pattern` — an email, a uuid, a hostname, a constrained string | somebody bothered to constrain it, so it identifies something |
| Required, a string, and not the identity | weak, and it separates a candidate from an optional display field |
| The name looks like a key — `email`, `slug`, `code`, `key`, `reference`, `username`, `sku`, `name` | **last, and only while your catalog has no convention yet** — a resemblance is a guess about English |

Never considered: the identity the backend assigns, timestamps, booleans, numbers, arrays, objects,
`description`/`notes`, and anything marked `readOnly`. A natural key has to be settable at creation
and stable afterwards, and none of those are both.

A path that **scopes** a collection is not scored, because it is not a guess.
`/accounts/{account_id}/projects` gives `natural_key: [account_id, slug]`, a
[`list_path`](catalog.md#list_path) ATF can fill in from the body, and a comment saying each project
is declared with the account it belongs to.

**Ambiguity is left unresolved.** When the leading candidate is not clearly ahead of the runner-up,
no `natural_key` is written and the candidates are listed in the file instead:

```yaml
label:
  system: rest
  path: /labels
  id_field: id
  # no natural_key: nothing was clearly ahead — considered `name` (it is a required string),
  #   `slug` (it is a required string).
```

That type will not provision until you choose, which is the safe half of the trade: a *wrong*
natural key never matches, so ATF creates another record on every run and nothing goes red until
somebody looks at the environment.

### What it does not infer {#import-openapi-not-inferred}

Said in the output rather than guessed, because a schema has no opinion about any of it:

| Key | What you decide |
|---|---|
| [`mode`](catalog.md#mode) | defaults to `create`. Set `reference` for anything ATF must never make, `data` for anything it only reads. |
| [`lifecycle`](catalog.md#lifecycle) | defaults to `persistent`. Set `ephemeral` for anything built per scenario. |
| [`depends_on`](catalog.md#depends_on) | a fact about your instances, not about the API — except where a path already scopes one resource under another. |

Instances are not written at all. Which accounts your suite needs is a question about your tests.

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
