# Run ATF in CI

Run the suite as a gate: one command, an exit code the pipeline reads, a report it can display, and
the results brought back so the editor knows what the pipeline saw.

## The shortest path

```sh
atf run --env staging --report ctrf:atf-run.json
```

Nonzero means the gate is closed. That is the whole contract.

## Exit codes

There are three, and there will only ever be three. `0` is passed, `1` is a test failed, and `2` is
the run never started.

Branch on `2` and nothing else. A pipeline that treats it as a test failure sends somebody looking
for a bug that is not there — the suite never ran.

When you need to branch on the reason, ask for it as data:

```sh
atf run --env staging --json
```

`--json` carries a structured error code beside the message: `environment_unreachable`,
`suite_invalid`, `environment_immutable`, `usage`. Match on that, never on the wording of a message.

A resource that cannot be created fails the test that needed it, so `atf run` closes the gate on a
broken environment by itself.

## The report

The argument to `--report` is `format:path`. Pass the flag more than once to write several.

**Only `ctrf` ships.** Any other format is one your suite registers first — JUnit XML is the worked
example, in [Extending ATF](../reference/extending-atf.md#report-format), and once it is registered
`--report junit:atf-run.xml` behaves like the line above.

The report carries every test's [outcome](../reference/the-record.md#outcome), the Gherkin sentence
that failed, and the paths of any screenshot or trace. Artefacts go under `.atf/artefacts/`; upload
that directory alongside the report or the paths in it point at nothing.

## Seeding ahead of the run

Make what the tests need before the gate runs, so the tests only ever find:

```sh
atf make staging
atf run --env staging --report ctrf:atf-run.json
```

`atf make` creates what is absent and updates what differs. Two reasons to do it as its own step:

- A provisioning failure is named as a provisioning failure, in its own step, instead of arriving as
  a red test in the step after it.
- Every test in the run then does the same thing to the environment — find — which is what makes the
  suite safe to run against something shared.

Add `--dry-run` to a pull request job to print what provisioning would create and change without
touching anything.

Against an environment where [`mutable` is false](configure-an-environment.md#mutable), `atf make`
refuses and exits `2` with `environment_immutable`. There, declare the resources
[`when_absent="require"`](require-something-you-cannot-create.md), let whatever owns the environment
seed it, and a test whose precondition is missing fails naming the resource.

Add `atf check` first. It is fast, it needs no environment to be reachable, and it fails on a suite
that is not well formed before anything is provisioned.

## A GitHub Actions job

```yaml
name: tests
on: [push]

jobs:
  atf:
    runs-on: ubuntu-latest
    env:
      ATF_ENV: staging
      STAGING_URL: ${{ secrets.STAGING_URL }}
      TOKEN: ${{ secrets.STAGING_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .
      - run: atf check
      - run: atf make staging
      - run: atf run --report ctrf:atf-run.json
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: atf-run
          path: |
            atf-run.json
            .atf/artefacts/
```

`ATF_ENV` chooses the environment for `atf check` and `atf run`; `atf make` takes it as an argument.
`if: always()` matters — the report is most useful on the run that failed.

## Bringing the results back

Download the report and import it:

```sh
atf import-run staging atf-run.json
```

The run joins this machine's [history](../reference/the-record.md#history), so the editor's verdicts
and `atf docs` reflect what the pipeline saw. Most of the evidence for flakiness is in CI, which is
what makes ["has it passed and failed lately"](work-out-why-it-is-red.md) answerable. Import on a
schedule or after a failure; the gate is complete without it.

## What is different about CI

- **Non-interactive.** `atf edit` and `atf edit --mcp` are local surfaces.
- **Binary.** The exit code is the answer. A report is for humans reading afterwards.
- **No exploring.** Everything you will want later — the screenshot, the trace, the sentence that
  failed — has to be written during the run and uploaded. Decide that before you need it.

## When it goes wrong

**Exit `2`, `unknown environment`.** `ATF_ENV` or `--env` does not match `atf.yaml`. `--json` gives
`usage`.

**Exit `2`, `$STAGING_DB is not set`.** The secret is not exposed to the step. Secrets are not
inherited by every step by default.

**Exit `2`, `unreachable: todo`.** The system did not answer. Nothing was tested, so do not treat it
as a failure. `--json` gives `environment_unreachable`.

**Exit `2`, `atf make` refuses.** The environment is not mutable (`environment_immutable`). Either it
should be, or the resources should be `when_absent="require"`.

**Exit `2`, `unknown selector`.** `--select` named something no resource and no type answers to. A
typo never reaches the suite.

**A green run that selected no tests.** `--select` named a real resource that nothing depends on.
Empty is the answer to what was asked, so `0` is right.

**Report paths point at nothing.** `.atf/artefacts/` was not uploaded.

**A red test naming a resource, not a claim.** Provisioning could not make what the test asked for.
Read it in the `atf make` step above it.

## Where to go next

- [Work out why it is red](work-out-why-it-is-red.md) — what to do with the report the gate produced.
- [Run only what a change touched](run-only-what-a-change-touched.md) — the selection that keeps a
  branch's gate short without guessing.
- [Configure an environment](configure-an-environment.md) — the environment the job names, and why it
  is unwritable unless you said otherwise.
