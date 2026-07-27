# selftest — ATF tested with ATF

This is an ATF suite whose system under test is ATF.

```sh
PYTHONPATH=../src uv run pytest -q      # 20 passed, or 16 passed + 4 skipped without a browser
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

The cockpit is server-rendered, so most of this needs no browser: `html_select.py` is a small
CSS-subset selector over the standard library's HTML parser, and it is unit-tested in
`tests/test_html_select.py` because the cockpit feature only exercises it as deep as its own
assertions go.

### The four scenarios that do need one

An `element` is what the server *sent*. A `view` is what is *there* — after the stylesheet applied,
htmx swapped and a combobox decided what to show. `visible` is the field no amount of HTML parsing
can give you, and it is the only reason this suite pays for a browser.

A view may declare what to do before looking, which turns "the options a step picker shows once you
have typed `belongs`" into a resource with a name and a description:

```yaml
then_picker_filtered:
  resource: view
  body:
    selector: "#compose-form .builder-step:last-of-type .combo-list li[role=option]:not([hidden])"
    after:
      - { do: click, at: "#compose-form .builder-step:last-of-type .combo-input" }
      - { do: type, at: "#compose-form .builder-step:last-of-type .combo-input", text: "belongs" }
```

(`at`, not the more natural `on`: YAML 1.1 reads a bare `on` as the boolean true, so the key would
arrive as `True` with an empty selector at the far end of it.)

Those scenarios are tagged `@browser` and skipped where Playwright or its browser is missing, so a
plain checkout still runs everything else and still goes green. To run them:

```sh
uv sync --group browser
uv run playwright install chromium
```

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
