# selftest — ATF tested with ATF

This is an ATF suite whose system under test is ATF.

```sh
PYTHONPATH=../src uv run pytest -q      # 16 passed
```

If the vocabulary below is unfamiliar, the
[glossary](https://mde-pach.github.io/atf/explanation/glossary/) defines every word in a sentence.

## How it works

| ATF concept | What it is here |
|---|---|
| **Resource** | a real consuming suite on disk (`workspace`), a running `atf serve` over one (`cockpit`), and what that cockpit shows (`page`, `element`) |
| **Adapter** | `selftest_adapters.py` copies a suite template into a temp dir; `cockpit_adapter.py` starts and stops the server, and reads pages and elements over HTTP |
| **Lifecycle** | ephemeral for both: every scenario gets a pristine suite and its own server, torn down afterwards |
| **Mode** | `reference` for pages and elements — they are observed and could never be created, which is also what stops this suite changing the interface it is reading |
| **SUT client** | `specs/atf_cli.py` — runs `atf …` inside that suite and reads the stub backend |
| **Environment** | `stub_backend.py`, an in-process HTTP API the suites-under-test provision into |

So `Given the workspace "chained"` builds a genuine consuming project, and
`When I run "atf seed local"` runs the real CLI against it. The provisioning step is ATF's own —
this suite defines no `@given`.

## Testing the front end the same way

`specs/features/cockpit.feature` has **no step code at all** — one `scenarios(…)` line and nothing
else. Every assertion in it is one of the
[read-and-compare steps](https://mde-pach.github.io/atf/reference/specs-and-fixtures/#read-and-compare-steps)
ATF gives every suite:

```gherkin
  Scenario: A type page lists its instances and the environment's records in one table
    Given the element "instances_table"
    Then the element "instances_table" exists
    And the element "instance_rows" field "count" is "1"
```

The dependency chain does the work. An element declares the page it is on, the page declares the
cockpit serving it, the cockpit declares the workspace it serves — so provisioning that one element
scaffolds a suite, starts a server over it, fetches the page, and tears both down afterwards.

An element that matches nothing is *absent*, which is what makes `Then the element "…" is gone` say
what it means: it is how this suite proves a piece of interface was removed and stayed removed.

The cockpit is server-rendered, so reading it needs no browser: `html_select.py` is a small
CSS-subset selector over the standard library's HTML parser, and it is unit-tested in
`tests/test_html_select.py` because the cockpit feature only exercises it as deep as its own
assertions go.

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

`tests/test_selftest.py` runs this suite, and then mutation-tests it: it breaks ATF in four places
— topological ordering, the `mutable_envs` gate, ephemeral teardown, and the threshold above which
the cockpit draws a lineage rather than describing it — and asserts the matching scenario goes red.
A self-test that cannot fail proves nothing, and that last one is the interface caught through the
interface.
