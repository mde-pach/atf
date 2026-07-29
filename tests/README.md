# ATF's tests, written in ATF

ATF's test suite is an ATF suite whose system under test is ATF, and this repository is set up the
way any project using ATF is: **one `atf.yaml` at the root**, found by walking up from wherever you
are. So the command works on it with nothing to export first.

```sh
uv run pytest -q                     # everything — about four minutes
uv run pytest -q tests/specs         # the scenarios alone — about a minute

uv run python -m tests.backend       # the environment, in another terminal…
uv run atf status local              # …and then any of these
uv run atf serve                     # ATF, browsing the suite that tests it
```

`atf lint` and `atf docs` need no environment at all and work on their own. Everything that reaches
a resource needs the environment running, which is the same thing that is true of any suite: start
what you are testing, then point ATF at it. The scenarios start it themselves, because a test run
should need one command.

**Three invocations are four times faster than one**, and CI uses them:

```sh
uv run pytest -q --ignore=tests/specs --ignore=tests/test_mutations.py -n auto   # ~55s
uv run pytest -q tests/specs                                                      # ~90s
uv run pytest -q tests/test_mutations.py                                          # ~95s
```

They want different things. The Python tests are ordinary tests with their own temp directories, so
they go across cores. The scenarios are an ATF suite and **must not** — the engine is single-worker
by design, and running them across workers fails in exactly the way
[concurrency](https://mde-pach.github.io/atf/reference/specs-and-fixtures/#concurrency) predicts.
The mutation guard runs the suite in subprocesses, so it shares a machine with nobody.

Running the lot with `-n auto` is *correct* — every scenario carries an `xdist_group` marker that
pins them to one worker — but it takes seven minutes rather than four, because the nested `atf`
subprocesses fight each other for the machine.

Six scenarios need a real browser and skip without one, so a checkout that never ran
`uv sync --group browser` is still green and still meaningful.

If the vocabulary below is unfamiliar, the
[glossary](https://mde-pach.github.io/atf/explanation/glossary/) defines every word in a sentence.

## How it works

| ATF concept | What it is here |
|---|---|
| **Resource** | a real consuming suite on disk (`workspace`), a running `atf serve` over one (`cockpit`), and what that cockpit shows (`page`, `screen`) |
| **Adapter** | `suite_adapters.py` copies a suite template into a temp dir and points the command at it; `cockpit_adapters.py` starts and stops the server. A `page` is ATF's own `html` adapter, a `screen` its `browser` one, and running the CLI is its `command` one — this suite writes none of the three. |
| **Lifecycle** | ephemeral for a `workspace` and a `private_cockpit`: a scenario that runs `atf` against a suite, or presses a button in one, gets a pristine one. Shared for a `shared_suite` and the `cockpit` over it — starting a server costs the better part of a second, and a `page` is served by ATF's `html` system, which only ever GETs, so nothing that reads one can change it. |
| **Mode** | `data` for a page, a screen, and the records a suite under test leaves behind — observations, never preconditions, which is what stops this suite changing the interface it is reading. |
| **SUT client** | `specs/atf_backend.py` — reads the environment the suites under test provision into |
| **Environment** | [`backend.py`](backend.py), serving `stub_backend.py` on the loopback address the manifest names. Three JSON collections, because the suite templates declare `rest` resources — **not** because ATF is about HTTP. This catalog is mostly not: a workspace is a directory, a cockpit a subprocess, a page a response. |
| **Phrasebook** | `specs/phrasebook.yaml` — every exit code, field name and CLI flag this suite needs, kept out of the features |

So `Given the workspace "chained"` builds a genuine consuming project, and
`When I run "atf seed local"` runs the real CLI against it — and both of those steps are ATF's own.
This suite defines no `@given` and no `@then` anywhere, and its entire vocabulary is three `@when`s
in `specs/conftest.py` saying where the command was standing or what the developer had exported,
which is the one thing a suite testing a *test framework* knows that ATF cannot. They live in a
`conftest.py` rather than beside a feature because every `.feature` here is collected by ATF with no
binding module of its own, and a step declared in a module is visible only inside it.

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
else. Every claim in it names a control by what it *is* and what it is *called*:

```gherkin
  Scenario: A type page lists its instances and what the environment holds, in one table
    Given the page "owner_type"
    Then the cell "primary" is showing
    And the cell "The owner the list hangs off." is showing
```

There is not one selector in this suite. A page says where to go and nothing else; what is on it is
named inline, by role and accessible name, which is what a screen reader announces. `elements.yaml`
used to be eleven nodes each carrying a CSS selector — a Page Object with a YAML file for a class —
and a rename in a template made a scenario wrong about a page that still worked.

The dependency chain does the work: a page declares the cockpit serving it, the cockpit declares
the workspace it serves — so provisioning one page scaffolds a suite, starts a server over it,
fetches the page, and tears both down afterwards.

### The scenarios that need a browser

A `page` is what the server *sent*, read by ATF's `html` system, which costs nothing. A `screen` is
what is *there* — after the stylesheet applied, htmx swapped and a combobox decided what to show —
read by ATF's `browser` system. **They answer the same sentences.** `the option "groceries" is not
showing` is one claim, and the only reason it lives below the line is that nothing in the HTML says
which options a person can currently see.

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

What is left in `tests/` is what genuinely has no observable surface, and the split settled into
four kinds of thing. **Every one of those modules opens with a docstring saying which it is and
why**, so the boundary is written down where somebody about to add a test will read it:

| Kind | Modules |
|---|---|
| A decision procedure over data — a truth table, a parser, a static analyser | `test_compare.py`, `test_placeholders.py`, `test_discovery.py`, `test_accessible.py`, `test_context.py` |
| A contract a reading surface has no words for — an HTTP header, a confirmation token, a status code, an auth scheme | parts of `test_cockpit.py`, `test_compose.py`, `test_authoring.py`, `test_rest_adapter.py` |
| Something only observable *while* it happens, or only when a backend misbehaves | `test_runner_jobs.py`, `test_store.py`, `test_engine.py` |
| A rule about what the framework may not *do* | `test_acceptance.py`, `test_mutations.py` |

The rule behind the table: **a module's behaviour becomes scenarios; what stays is a decision
procedure over data.** Where a conversion would have needed a suite whose whole purpose was to fail
in a particular shape, the unit test was the better description and stayed.

**The one real cost is diagnosis, and it is a deliberate trade.** If a bootstrap bug lands, this
whole suite fails to collect and tells you nothing, where a unit test still points at the broken
function. The mutation guard below is the partial recovery, and the failure messages in `steps.py`
— which name what was compared — are the rest of it.

## Guarding the guard

`tests/test_mutations.py` runs this suite, and then mutation-tests it: it breaks ATF in four places
— topological ordering, the `mutable_envs` gate, ephemeral teardown, and the threshold above which
the cockpit draws a lineage rather than describing it — and asserts the matching scenario goes red.
A self-test that cannot fail proves nothing, and that last one is the interface caught through the
interface.

It also guards the dogfood itself: no hand-written `@given` or `@then` may appear anywhere under
`specs/`. Provisioning and every claim are ATF's own, and the day one of them is written here by
hand is the day this stops being a suite that proves the framework is usable.

## Three disciplines, learned by getting them wrong

**A scenario may never depend on an ambient variable.** Two scenarios about a scaffolded suite
passed alone and failed under the full suite, because they inherited an `ATF_ACTOR` that the unit
test they replaced had set explicitly. Whatever a scenario needs in the environment, it says.

**A negative claim is worth doubting until its positive twin is green.** `Then the option "the
todo_list" is not showing` passed for a year because no option was called that at all. Write the
claim that proves the thing can be seen before you trust the claim that it cannot.

**A claim's value cannot contain a double quote**, because it is captured between them. A message
reading `is "standard", not "enterprise"` has to be claimed by naming the parts around the quotes —
which is a limitation of the vocabulary, not of the message.
