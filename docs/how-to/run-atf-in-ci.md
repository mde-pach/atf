# How to run ATF in CI

Use your suite as a deployment guard: run the specs against a deployed environment, fail the
pipeline when they fail, and feed the result back to the cockpit.

## Use `atf run` as the gate

`atf run` exits `0` when every test passes and `1` when any test fails, so it works as a step
directly:

```sh
atf run --env staging
```

Other exit codes mean the suite never ran: `2` for a configuration or catalog error — a missing
manifest, an unknown environment, a dangling dependency — and `130` for an interrupt. Treat anything
non-zero as a red build; the distinction matters only when you are reading the log. See
[exit codes](../reference/cli.md#exit-codes).

To gate on a subset, pass paths:

```sh
atf run specs/steps/test_checkout.py --env staging
```

## Supply the secrets

Manifests contain no secrets — only [`*_env` pointers](../reference/manifest.md#environment-variable-pointers)
to environment variables. Whatever your manifest names, CI must provide. For a manifest containing
`token_env: ATF_TOKEN`:

```yaml
# GitHub Actions
      - run: atf run --env staging
        env:
          ATF_TOKEN: ${{ secrets.ATF_TOKEN }}
```

If a pointer is unset, ATF fails fast at startup with the variable's name, before touching the
environment.

## Choose the environment

`--env` wins; otherwise ATF reads `ATF_ENV`; otherwise the manifest's `default_env`. Set `ATF_ENV`
once at job level if every step targets the same place:

```yaml
    env:
      ATF_ENV: staging
```

If the manifest is not in the working directory, point at it with `ATF_MANIFEST`.

## A complete job

```yaml
name: E2E

on:
  push:
    branches: [main]

jobs:
  specs:
    runs-on: ubuntu-latest
    env:
      ATF_ENV: staging
      ATF_TOKEN: ${{ secrets.ATF_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen

      - name: Provision what the specs need
        run: uv run atf seed staging

      - name: Run the specs
        run: uv run pytest --json-report --json-report-file=report.json -q

      - name: Record the run
        if: always()
        run: uv run atf import-run staging report.json

      - name: Keep the report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: atf-run
          path: |
            report.json
            .atf/runs/
```

The `seed` step is optional — specs provision what they declare, so a run alone is enough. Seed
first when you want provisioning failures reported separately from test failures, which makes a red
build faster to read.

For `seed` to work, the environment must be listed in
[`mutable_envs`](../reference/manifest.md#mutable_envs). If it is not, the command exits `2` and
changes nothing.

## Feed the result back to the cockpit

The job above runs pytest directly rather than `atf run`, for one reason: it wants the JSON report.
`atf import-run` then files that report in the [run history](../reference/cockpit.md#run-history) as
a run against the named environment.

```sh
pytest --json-report --json-report-file=report.json -q
atf import-run staging report.json
```

Why bother: the cockpit then shows CI outcomes on the scenario page alongside local ones, dates
them, and folds them into the flakiness calculation. A test that passes locally and fails nightly is
exactly the thing you want flagged, and neither half of that pattern is visible on its own.

`import-run` writes to `.atf/runs/` under the suite root. It does not touch the environment, so it
is not gated by `mutable_envs`, and it is safe in `if: always()`.

`atf run` writes to the same store, so a job that does not need the artifact can keep using it and
still contribute history — as long as `.atf/runs/` survives the job.

### Getting the history back to a human

`.atf/` is a local cache, gitignored by design, and a CI runner is thrown away. Two ways to make the
history useful:

- **Upload it as an artifact**, as above, and unpack it into a suite root when you want to look.
- **Import on the machine that will read it**: download the build's `report.json` and run
  `atf import-run staging report.json` locally. The cockpit picks it up on the next page load.

## Keep it to one worker

Do not add `pytest-xdist`, and do not let two pipelines provision one environment at once — see
[concurrency](../reference/specs-and-fixtures.md#concurrency). If you need parallelism, split by
environment: one worker per environment, never several per environment.

## Test a pull request against a throwaway environment

If your infrastructure can create an environment per branch, add it to the manifest once with its
URL read from the environment:

```yaml
environments:
  review:
    adapters:
      rest:
        base_url_env: REVIEW_URL
        auth: { bearer: { token_env: ATF_TOKEN } }
    clients:
      api:
        base_url_env: REVIEW_URL
```

Then point each build at its own instance:

```yaml
      - run: uv run atf run --env review
        env:
          REVIEW_URL: ${{ steps.deploy.outputs.url }}
```

Add `review` to `mutable_envs` so the job may seed it.

## Catch drift before it fails a deploy

`atf status` is read-only and safe anywhere, which makes it a good nightly job:

```sh
atf status staging
```

A resource that has quietly gone `absent` or `error` is usually the API changing shape underneath
the catalog — see
[How to keep the catalog in step with an API change](keep-the-catalog-in-step.md). Finding that at
03:00 is better than finding it during a release.

## Where to go next

- [CLI reference](../reference/cli.md) — every command, flag and exit code used above.
- [How to find out why an environment is red](find-out-why-an-environment-is-red.md) — reading the
  imported run once CI goes red.
- [Manifest reference](../reference/manifest.md#mutable_envs) — the gate that keeps production out
  of reach.
