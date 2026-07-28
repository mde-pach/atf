# CLI reference

```
atf [-h] {init,serve,seed,status,run,lint,import-run} ...
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
atf run [paths ...] [--env ENV]
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

The active environment, unless `--env` is given. Read by `serve` and `run`.

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
