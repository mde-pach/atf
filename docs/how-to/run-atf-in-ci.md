# How to run ATF in CI

Use your suite as a deployment guard: run the specs against a deployed environment and fail the
pipeline when they fail.

## Use `atf run` as the gate

`atf run` exits `0` when every test passes and `1` when any test fails, so it works as a step
directly:

```sh
atf run --env staging
```

Other exit codes mean the suite never ran: `2` for a configuration or catalog error — a missing
manifest, an unknown environment, a dangling dependency — and `130` for an interrupt. Treat
anything non-zero as a red build; the distinction matters only when you are reading the log.

To gate on a subset, pass paths:

```sh
atf run specs/steps/test_checkout.py --env staging
```

## Supply the secrets

Manifests contain no secrets — only `*_env` pointers to environment variables. Whatever your
manifest names, CI must provide. For a manifest containing `token_env: ATF_TOKEN`:

```yaml
# GitHub Actions
      - run: atf run --env staging
        env:
          ATF_TOKEN: ${{ secrets.ATF_TOKEN }}
```

If a pointer is unset, ATF fails fast at startup with the variable's name — before touching the
environment.

## Choose the environment

`--env` wins; otherwise ATF reads `ATF_ENV`; otherwise the manifest's `default_env`. Set
`ATF_ENV` once at job level if every step targets the same place:

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
        run: uv run atf run
```

The `seed` step is optional — specs provision what they declare, so a run alone is enough. Seed
first when you want provisioning failures reported separately from test failures, which makes a red
build faster to read.

For `seed` to work, the environment must be listed in `mutable_envs` in the manifest. If it is not,
the command exits `2` and changes nothing. Leave production out of that list and the guard becomes
structural rather than a matter of discipline.

## Keep it to one worker

Do not add `pytest-xdist`. The session materializer, its listing cache and get-or-create are not
safe under parallel workers; concurrent runs against one environment will duplicate resources. If
you need parallelism, split by environment — one worker per environment, never several per
environment.

For the same reason, avoid two pipelines seeding the same environment at once.

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

## Publish what failed

`atf run` prints one line per test with its outcome and duration, and the failing assertion beneath
it. That is usually enough in a log. If you want a machine-readable artifact, run pytest directly —
it takes the same environment variables:

```sh
uv run pytest --json-report --json-report-file=report.json -q
```

Upload `report.json` as a build artifact.
