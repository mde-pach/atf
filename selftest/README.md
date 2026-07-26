# selftest — ATF tested with ATF

This is an ATF suite whose system under test is ATF.

```sh
PYTHONPATH=../src uv run pytest -q      # 8 scenarios
```

## How it works

| ATF concept | What it is here |
|---|---|
| **Resource** | a real consuming suite, scaffolded on disk (`suites/chained`, `suites/ephemeral`, …) |
| **Adapter** | `selftest_adapters.py` — `create` copies a suite template into a temp dir, `delete` removes it |
| **Lifecycle** | ephemeral: every scenario gets a pristine suite, torn down afterwards |
| **SUT client** | `specs/atf_cli.py` — runs `atf …` inside that suite and reads the stub backend |
| **Environment** | `stub_backend.py`, an in-process HTTP API the suites-under-test provision into |

So `Given the workspace "chained"` builds a genuine consuming project, and
`When I run "atf seed local"` runs the real CLI against it. The provisioning step is ATF's own —
this suite defines no `@given`.

## What it covers that unit tests cannot

Every scenario crosses the seams the unit tests mock out: manifest resolution in a fresh process,
adapter-factory registration, catalog validation surfacing as an exit code, dependency-first
provisioning against a live HTTP backend, the pytest plugin's generated fixtures, and ephemeral
teardown.

## What it deliberately does not cover

Unit-level rules — each catalog validation error, placeholder forms, topological ordering, retry
and auth behaviour, discovery parsing — stay in `tests/`. Two reasons:

1. **Diagnosis.** If a bootstrap bug lands, this whole suite fails to collect and tells you
   nothing. The unit tests still point at the broken function.
2. **Expressiveness.** "A cycle is rejected, listing every problem at once" is an assertion about
   a function's return value, not a behaviour with resources to provision. Forcing it through
   Gherkin would make it less clear, not more.

The two layers answer different questions: `tests/` asks *is each part correct?*, this suite asks
*does the whole thing work when a real user drives it?*

## Guarding the guard

`tests/test_selftest.py` runs this suite, and then mutation-tests it: it breaks ATF in three
places (topological ordering, the `mutable_envs` gate, ephemeral teardown) and asserts the
matching scenario goes red. A self-test that cannot fail proves nothing.
