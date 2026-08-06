# The command

Every subcommand, every flag, every exit code.

`atf` is the CI face of the framework. It is non-interactive: it never prompts, never opens a
browser, never waits for a person. Each invocation asks one question and answers it with an exit
code. Everything finer travels in the message, and every answer is also available as data.

The human output of any subcommand may change between versions. The exit codes and the `--json`
output may not.

## Exit codes {#exit-codes}

There are three, and there is no fourth. `0` passed. `1` a test failed. `2` the run never started.

For the commands that do not run tests, read the same three codes as: the question was answered
(`0`), the answer is no (`1`), the question could not be asked (`2`).

`2` covers an unreachable environment, an ill-formed suite, an environment that may not be changed,
and a bad invocation; the line printed says which. The cost: a shell script cannot branch on why by
comparing a number. That is what `--json` is for.

In `--json` mode, anything that exits `2` emits one of four stable machine names on stderr:

```json
{"error": {"code": "environment_unreachable", "environment": "staging",
           "message": "connection refused"}}
```

`environment_unreachable` is an environment that did not answer: neither pass nor fail, nothing
learnt. `suite_invalid` is an unknown step, a dependency cycle, or two resources with one name.
`environment_immutable` is an operation that would change an environment that is not `mutable`.
`usage` is an unknown flag, a missing argument, or an unreadable or invalid `atf.yaml`.

[`atf check`](#check) is the exception: reporting an ill-formed suite is its job, so it exits `1`
and prints the faults under `faults` rather than exiting `2` under `error`.

An interrupt exits `2`. Partial work is not recorded as a run, so there is no verdict to report.

- **In CI** — the whole branching surface: the code, and `error.code` when it needs to know why.
- **In the editor** — not shown. The editor shows the thing a code summarises.
- **To an agent** — the same `error.code` strings, as a field on a failed tool call.

## Global flags {#global-flags}

Accepted by every subcommand. A flag that takes no argument is off unless it is given.

`--json` puts the answer on stdout and an error on stderr, both as JSON. `--config PATH` is the
manifest to read, `./atf.yaml` by default. `--quiet` suppresses progress and leaves the exit code
and any written file alone. `--version` and `--help` print and exit `0`.

Each is accepted before the subcommand and after it, and each appears in the generated options
below, on every command that takes it.

Commands that name an environment take it as a positional argument. Commands that merely use one
take `--env`, defaulting to `default_env` from the manifest.

The manifest used by every example on this page:

```yaml
resources: [./resources.py]
specs: ./specs
extensions: [./adapters/sqlite.py]
default_env: local

environments:
  local:
    mutable: true
    sqlite:  { path: ./todo.db }
    command: { prefix: "python todo.py" }
```

`sqlite` is the suite's own [adapter](extending-atf.md#registering-an-adapter), not part of ATF;
`command` ships with it.

## `atf init` {#init}

Scaffolds nothing but ATF itself: an `atf.yaml` with one environment, an empty `resources.py`, and
an empty `specs/` directory. It does not generate tests, resources or example code.

::: mkdocs-click
    :module: atf.entry
    :command: init
    :prog_name: atf init
    :depth: 2
    :list_subcommands: False

Exits `0` when the files were written, `1` when `atf.yaml` already exists and `--force` was not
given — nothing is written — and `2` on bad flags or a directory that is not writable.

```console tesh-session="init" tesh-exitcodes="0" tesh-setup="empty.sh"
$ atf init
wrote atf.yaml
wrote resources.py
wrote conftest.py
wrote specs
```

- **In CI** — not shown. A pipeline runs against a suite that already exists.
- **In the editor** — not shown. The editor needs a manifest to open, so `init` comes first.
- **To an agent** — not shown. There is no `init` tool; an agent writes the three files itself.

## `atf status` {#status}

Asks the environment what it holds. One line per resource, in the environment's vocabulary:
`present`, `absent` or `unreachable`. It changes nothing.

```sh
atf status <env> [name]
```

The optional `name` narrows the question to one resource and everything it depends on.

::: mkdocs-click
    :module: atf.entry
    :command: status
    :prog_name: atf status
    :depth: 2
    :list_subcommands: False

Exits `0` when the question was answered, whatever the answer was, and `2` on bad flags, no such
environment, an ill-formed suite, or an environment that could not be reached.

**`status` is not a gate, and never exits `1`.** Absence is information: a resource ATF is going to
create is expected to be absent beforehand. The gate is [`atf run`](#run).

```console tesh-session="status" tesh-exitcodes="0" tesh-setup="todo.sh"
$ atf status local
primary    absent  created
secondary  absent  created
groceries  absent  created
...
```

```console tesh-session="status" tesh-exitcodes="0"
$ atf status local groceries
primary    absent  created
groceries  absent  created
```

Asking about `groceries` also answers about `primary`. A resource is never reported without the
lineage it stands on.

- **In CI** — a diagnostic, not a gate: it prints what the environment held before `atf run` touched
  it, and a pipeline does not branch on the result.
- **In the editor** — the [catalogue](the-editor.md#catalogue) and the counts on the overview, the
  same question asked per type.
- **To an agent** — the `status` tool, returning the `resources` array above; `state` is a field.

## `atf make` {#make}

Brings the environment into line with what the resources declare, in dependency order. `primary` is
created before `groceries`, because `groceries` names it.

```sh
atf make <env> [name] [--dry-run]
```

**`make` reconciles; it does not only create.** A resource that is missing is created. A resource
that is there but whose fields differ from the declaration is updated to match. A declaration is a
partial specification, so only the fields it names are touched.

::: mkdocs-click
    :module: atf.entry
    :command: make
    :prog_name: atf make
    :depth: 2
    :list_subcommands: False

Exits `0` when the environment matches the declaration, `1` when it does not and ATF may not fix it
— a resource declared `when_absent="require"` is absent — and `2` on bad flags, no such environment,
an ill-formed suite, an unreachable environment, or one that is not `mutable`.

```console tesh-session="make" tesh-exitcodes="0" tesh-setup="todo.sh"
$ atf make local groceries
primary    present  created  changes: email
groceries  present  created  changes: slug
```

```console tesh-session="dry" tesh-exitcodes="0" tesh-setup="todo.sh"
$ atf make local groceries --dry-run
primary    absent  created  changes: email  (dry run)
groceries  absent  created  changes: slug  (dry run)
```

The change line is the diff ATF computes, not the adapter, which is why it can be shown first.

```console tesh-session="refused" tesh-exitcodes="2" tesh-setup="todo.sh"
$ atf make readonly
the readonly environment is not mutable, so nothing was made. Add `mutable: true` to it, or point at one that has it.
```

`mutable` is false unless stated, so the third example is what an unconfigured environment does. It
refuses before touching anything.

- **In CI** — rarely called directly: `atf run` makes what the tests name.
- **In the editor** — the Make button on a resource, and the "would create" and "would change"
  panels, which are `--dry-run`'s answer rendered.
- **To an agent** — the `make` tool, with the dry-run answer as a field.

## `atf run` {#run}

Runs tests and records a [run](the-record.md#a-run). Resources a test names are made as it asks for
them, unless `--no-make` says otherwise.

::: mkdocs-click
    :module: atf.entry
    :command: run
    :prog_name: atf run
    :depth: 2
    :list_subcommands: False

A selection is a narrowing, and the narrowings compose. `--tag` repeats as OR. `--select` takes a
leading `+` to widen downstream, so `+groceries` also takes tests naming a resource that depends on
`groceries`. `--failed` reads this environment's [history](the-record.md#history) rather than the
graph, and selects nothing where there is none. `-k` is pytest's own language, a selection over
names where the other three are selections over the graph. `--report` takes
`format:path` and repeats; see [report](the-record.md#report).

Exits `0` when no test failed, which includes a selection that legitimately matched nothing and one
that was entirely skipped. Exits `1` when at least one test failed; a resource that could not be
created is one of the ways a test fails. Exits `2` on bad flags, a `--select` naming a resource the
suite does not declare, no such environment, an ill-formed suite, an unreachable environment, an
immutable environment that the selection needs changed, or an interrupt — in which case nothing ran
and no run was recorded.

**There is no blocked outcome.** A test whose resource is missing has it created and runs. A test
whose resource cannot be created fails, on the sentence that named the resource.

**An empty selection splits.** `--select` naming something the suite does not declare is a mistake:
the run never starts, nothing is recorded, and the exit code is `2` with `usage` under `--json`.
`--select` naming a real resource that no test reaches is an answer: the run happens and exits `0`.
To distinguish "ran nothing" from "ran and passed" in a pipeline, use `--dry-run` and count the
identities it prints.

```console
$ atf run --env local --tag smoke
specs/lists.feature::a list belongs to its owner .. failed
  specs/lists.feature:12
  Then the todo_list "groceries" field "slug" is "groceries"
  field "slug" is "grocery", expected "groceries"

1 failed, 13 passed
```

The two halves of the split, in order:

```console
$ atf run --select +grocerys
no resource "grocerys" in this suite
$ echo $?
2

$ atf run --select +visitor
0 tests selected
```

`--failed` selects from this environment's history rather than from the graph, and `--report` writes
the run out for a pipeline to collect:

```console
$ atf run --failed --report ctrf:out.json
```

- **In CI** — the gate: one invocation, one exit code, and `--report` for what the code cannot carry.
- **In the editor** — the run button, on one test or on a filter, streaming into
  [activity](the-editor.md#activity).
- **To an agent** — the `run` tool, taking the same selection arguments and returning outcomes as
  they resolve.

## `atf check` {#check}

Asks whether the suite is well formed, without an environment and without running anything. It
answers the questions that would otherwise surface as `error.code: suite_invalid` from another
command: unknown steps, dependency cycles, duplicate resource names, a `specs` path that is not
there.

::: mkdocs-click
    :module: atf.entry
    :command: check
    :prog_name: atf check
    :depth: 2
    :list_subcommands: False

Exits `0` when the suite is well formed, `1` when it is not — the faults are the answer, listed
under `faults` — and `2` on bad flags or an unreadable manifest.

```console
$ atf check
14 scenarios, 4 resources, 3 phrases
ok
```

```console
$ atf check --json
{"ok": false, "faults": [
  {"code": "unknown_step", "file": "specs/lists.feature", "line": 9,
   "text": "When I archive the todo_list \"groceries\""}
]}
```

- **In CI** — the pull-request gate; it needs no infrastructure and exits `1` on findings, which is
  what distinguishes it from `atf status`.
- **In the editor** — the overview's "suite" line, with each fault linking to the scenario it names.
- **To an agent** — the `check` tool, returning `faults` structured: an agent reads the rule it
  broke.

## `atf docs` {#docs}

Renders the specs as markdown, carrying the last [verdict](the-record.md#verdict) for each scenario
from history. A scenario nobody has run is rendered as `never run` rather than left blank.

::: mkdocs-click
    :module: atf.entry
    :command: docs
    :prog_name: atf docs
    :depth: 2
    :list_subcommands: False

Exits `0` when the markdown was written, and `2` on bad flags, an output directory that is not
writable, or an ill-formed suite. A `failing` verdict on the page does not change the code: `docs`
reports, it does not judge.

```console
$ atf docs --out site/specs --env local
wrote site/specs/lists.md      14 scenarios   13 passing   1 failing
```

- **In CI** — publishes what the suite claims, verdicts attached, wherever the team reads
  documentation.
- **In the editor** — the [tests](the-editor.md#tests) list is the same content, live.
- **To an agent** — the `docs` tool: what the suite already claims, read before writing a test that
  claims it again.

## `atf edit` {#edit}

Opens the editor, or with `--mcp` the agent interface onto the same engine. This is the one
interactive subcommand, and it is documented in full in [the editor](the-editor.md).

::: mkdocs-click
    :module: atf.entry
    :command: edit
    :prog_name: atf edit
    :depth: 2
    :list_subcommands: False

`--port` is ignored with `--mcp`, which speaks on stdio. There is no `--host`: the editor binds
loopback and there is no flag that changes it — see [security](the-editor.md#security).

Exits `0` when the editor closed — interrupting it is how you close it, so that is a clean exit too
— and `2` on bad flags or no such environment. `edit` does not exit `2` on an ill-formed suite; the
fault is shown in the editor.

```console
$ atf edit --env local
editor on http://127.0.0.1:8765
```

- **In CI** — not shown. `edit` is interactive and `--mcp` waits on a peer; neither belongs in a
  pipeline.
- **In the editor** — this is the command that starts it.
- **To an agent** — `atf edit --mcp` is the agent interface, speaking MCP on stdio through the same
  gate a browser goes through.

## `atf impact` {#impact}

Answers what breaks if a named resource does. It reads the graph, not history, so it answers before
anything is run.

```sh
atf impact [name]
```

Named, it answers about one resource. Bare, it prints the whole graph: every resource, what each one
stands on, and the tests that reach it.

::: mkdocs-click
    :module: atf.entry
    :command: impact
    :prog_name: atf impact
    :depth: 2
    :list_subcommands: False

`--depth 1` is direct dependents only; lineage is followed the whole way when it is not given.

Exits `0` when the question was answered, including when the answer is nothing, and `2` on bad
flags, no resource of that name in the suite, or an ill-formed suite. Nothing depending on the named
resource is exit `0`, not `1`.

```console
$ atf impact groceries
resources
  Task laundry          (via TodoList groceries)
tests
  specs/lists.feature::a list belongs to its owner
  specs/tasks.feature::completing a task
  tests/test_lists.py::test_c
```

```console
$ atf impact primary --tests-only --json
{"resource": "primary", "tests": [
  "specs/lists.feature::a list belongs to its owner",
  "specs/tasks.feature::completing a task",
  "tests/test_lists.py::test_c"
]}
```

- **In CI** — the answer to "which tests does this change touch", fed to `--select` on a pipeline
  that does not want to run everything.
- **In the editor** — the [graph](the-editor.md#graph) view, and its "what breaks if this does"
  entry point.
- **To an agent** — the `impact` tool, read before changing a resource.

## `atf unused` {#unused}

Lists what nothing asks for: resources no test names and nothing depends on, phrases no scenario
says, steps no scenario reaches.

::: mkdocs-click
    :module: atf.entry
    :command: unused
    :prog_name: atf unused
    :depth: 2
    :list_subcommands: False

`--kind` repeats, and every kind is listed when it is not given.

Exits `0` when the question was answered — unused things were listed, and without `--strict` that is
not a failure — `1` under `--strict` when something is unused, and `2` on bad flags or an ill-formed
suite. The default is `0` because an unused resource is often deliberate: one declared for an
environment to require, waiting for the test that will name it.

```console
$ atf unused
resource  Guest visitor          nothing asks for it
phrase    "a customer who has already paid"   said by nothing
```

```console
$ atf unused --kind resources --strict
resource  Guest visitor          nothing asks for it
```

- **In CI** — a hygiene step, and with `--strict` a gate a team can opt into.
- **In the editor** — the graph's "what nothing asks for" entry point, over the same set.
- **To an agent** — the `unused` tool, which is what an agent reads before deleting anything.

## `atf import-run` {#import-run}

Brings a run recorded elsewhere into this suite's [history](the-record.md#history). The file is a
report in a registered format — `ctrf` unless told otherwise — which is the same format
`atf run --report` writes.

```sh
atf import-run <env> <file>
```

::: mkdocs-click
    :module: atf.entry
    :command: import_run
    :prog_name: atf import-run
    :depth: 2
    :list_subcommands: False

Exits `0` when the run was stored — failures inside the imported run do not change that, since
importing is what succeeded — and `2` on bad flags, no such environment, an unreadable file, or a
file that is not the stated format.

The imported run is stored with `source: imported`. Nothing is executed and no environment is
touched.

```console
$ atf import-run staging ci-results.json --label ci
imported r-7b12ce  staging  14 tests  1 failed  source=imported label=ci
$ echo $?
0

$ atf run --env staging --failed
specs/lists.feature::a list belongs to its owner .. passed

1 passed
```

`--failed` selects from CI's outcomes exactly as it selects from a laptop's. A local pass over an
imported failure is a disagreement between two runs of one test, which makes it
[flaky](the-record.md#flakiness) rather than fixed.

- **In CI** — the other end of `--report`: CI writes the file, a laptop reads it.
- **In the editor** — imported runs appear in [activity](the-editor.md#activity) and in history
  beside local ones, and the overview's "last run" line names where each came from.
- **To an agent** — the `import-run` tool: a CI artefact goes into history, then history answers.

## Where to go next

- [The record](the-record.md) — what `run`, `import-run` and `--report` produce, and how outcomes
  fold into the verdicts `atf docs` prints.
- [Run ATF in CI](../how-to/run-atf-in-ci.md) — these commands assembled into a pipeline, with
  `atf run` as the single gate and `--json` for the pipeline that wants to know why.
- [The editor](the-editor.md) — the other face of the same engine, for when a coarse answer is not
  what you need.
