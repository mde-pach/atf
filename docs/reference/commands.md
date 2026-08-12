# Commands

Six commands, generated from the command tree itself. Nothing below is hand-written except this
page's first two sections.

| Question | Command | What it also answers |
| --- | --- | --- |
| Start me off | `atf init` | what is already here, and whether the scaffold runs green |
| Is this suite sound, and what will happen? | `atf plan` | standing, drift, undeclared, lint, spans |
| Run the tests | `atf run` | reports, the contract, drafting claims |
| Put me inside this failure | `atf enter` | |
| Tell me everything about this | `atf explain` | impact, what is unused, history |
| Let me look around | `atf edit` | the spec, written out |

There is no `make`. `atf run` makes what it needs and `atf plan` shows what is missing; the state
without the tests is `atf plan --apply`.

## Exit codes {#exit-codes}

Three, and there is no fourth.

| Code | Running tests | Everything else |
| --- | --- | --- |
| `0` | nothing failed | the question was answered |
| `1` | at least one test failed | the answer is no |
| `2` | the run never started, and nothing was recorded | the question could not be asked |

A selection that legitimately matched nothing exits `0`.

`--json` puts a machine-readable name on stderr for anything that exits `2`: `usage`,
`suite_invalid`, `environment_unreachable`, `environment_not_ours`. The human output of any
subcommand may change between versions; the exit codes and the `--json` shape may not.

## Global flags

`--json`, `--config PATH` and `--quiet` may be written before or after the subcommand. The later
one wins.

::: mkdocs-click
    :module: atf.entry
    :command: cli
    :prog_name: atf
    :depth: 1
    :style: table
