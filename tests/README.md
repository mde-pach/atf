# ATF's tests, written in ATF

ATF's test suite is an ATF suite whose system under test is ATF. Running it is running ATF:

```sh
uv run pytest -q          # from the repository root — the scenarios and the rest together
uv run pytest -q tests/specs   # the scenarios alone
```

Six scenarios need a real browser and skip without one, so a checkout that never ran
`uv sync --group browser` is still green and still meaningful.

If the vocabulary below is unfamiliar, the
[glossary](https://mde-pach.github.io/atf/explanation/glossary/) defines every word in a sentence.

## How it works

| ATF concept | What it is here |
|---|---|
| **Resource** | a real consuming suite on disk (`workspace`), a running `atf serve` over one (`cockpit`), and what that cockpit shows (`page`, `element`) |
| **Adapter** | `suite_adapters.py` copies a suite template into a temp dir; `cockpit_adapters.py` starts and stops the server and reads what it sent; `screen` is ATF's own browser adapter |
| **Lifecycle** | ephemeral for both: every scenario gets a pristine suite and its own server, torn down afterwards |
| **Mode** | `reference` for pages and elements — observed, never created, which is what stops this suite changing the interface it is reading. `data` for the records a suite under test leaves behind, and for a `screen`. |
| **SUT client** | `specs/atf_cli.py` — runs `atf …` inside that suite and reads the stub backend |
| **Environment** | `stub_backend.py`, an in-process HTTP API the suites-under-test provision into |
| **Phrasebook** | `specs/phrasebook.yaml` — every exit code, field name and CLI flag this suite needs, kept out of the features |

So `Given the workspace "chained"` builds a genuine consuming project, and
`When I run "atf seed local"` runs the real CLI against it. The provisioning step is ATF's own —
this suite defines no `@given` and no `@then` anywhere. Its entire vocabulary is four `@when`s in
`specs/conftest.py`, all of them "run the command", because running a command is the one thing a
framework has no generic way to do. They live in a `conftest.py` rather than beside a feature
because every `.feature` here is collected by ATF with no binding module of its own, and a step
declared in a module is visible only inside it.

## One template, many variations

Most of what this suite has to say about ATF is *"here is a manifest with one thing wrong with it,
and here is what the command says about it"*. A suite template per malformation would be forty
directories differing by three lines each — a global set of named fixtures where every variation
needs a new one, which is the Object Mother pattern. So a scenario writes the difference where the
difference matters:

```gherkin
  Scenario: A type naming a system nothing knows how to talk to is refused
    Given the workspace "bare" but:
      | catalog/resources.yaml | {account: {system: quantum}} |
    When I run "atf status local"
    Then it is refused because "no registered adapter"
```

`but:` is ATF's own varied-provision step; the table reaches `WorkspaceAdapter` as an override of
the node's body, and a body key that is not `suite` is a path inside the copied workspace holding
that file's whole text. Flow-style YAML fits on one line because a broken catalog is small by
nature. `#absent` removes a file; `@{…}` is written where the file must *contain* an unresolved
`${…}`, since the materializer resolves a body before the adapter sees it.

`suites/bare` exists for this: a valid manifest and an empty catalog, so a scenario's refusal
arrives without the two real nodes of `chained` for company. **Five templates, not forty-five.**

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

## What it used to say it could not cover

This section used to argue that unit-level rules — each catalog validation error, each manifest
one — belonged in `tests/`, because *"a cycle is rejected, listing every problem at once"* is an
assertion about a function's return value rather than a behaviour with resources to provision.

`specs/features/catalog.feature` is now that scenario, and it is not worse for it: a cycle is
rejected means **the command refuses and names the ring**, which is what a person meets. What
made the argument true was the missing variation mechanism, not the subject matter — writing forty
suite templates would indeed have been worse than forty unit tests. `Given … but:` removed the
reason.

What is left in `tests/` is what genuinely has no observable surface: rules about what the
framework may not *do* (`test_acceptance.py` — no product URLs in the source, no per-system
branching in the materializer, no socket opened while a catalog loads), and the parts not yet
ported. The migration is tracked in `ATF-PLAN.md`.

**The one real cost is diagnosis, and it is a deliberate trade.** If a bootstrap bug lands, this
whole suite fails to collect and tells you nothing, where a unit test still points at the broken
function. The mutation guard below is the partial recovery, and the failure messages in `steps.py`
— which name what was compared — are the rest of it.

## Guarding the guard

`tests/test_selftest.py` runs this suite, and then mutation-tests it: it breaks ATF in four places
— topological ordering, the `mutable_envs` gate, ephemeral teardown, and the threshold above which
the cockpit draws a lineage rather than describing it — and asserts the matching scenario goes red.
A self-test that cannot fail proves nothing, and that last one is the interface caught through the
interface.
