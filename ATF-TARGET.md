# ATF — the target model, and how to get there

This document is self-contained. It states what ATF should become, why, what has to change, and in
what order. It was produced by a design session that examined the whole repository and researched
current practice; the conclusions and the rejected alternatives are both recorded so neither has to
be re-derived.

**Relationship to `ATF-NEXT-SESSION.md`** (committed as `d93b691`, the previous session's brief):

- **Still authoritative:** the architecture summary, the constraints that bit last time, and the UI
  rules learned the hard way. They are reproduced in Part 7 of this document.
- **Superseded:** its framework direction — a `Task` concept, generating step stubs, and the framing
  that "one generic step is a suspiciously small number". This document replaces all of it.
- **Now factually stale, do not trust:** it says "374 tests" (it is 573) and "Nothing is committed,
  ~103 changed files in the working tree" (the tree is clean; only `ATF-TARGET.md` is untracked).

---

# Part 1 — The philosophy this serves

Stated by the project's author, and every decision below is answerable to it.

1. **A test describes how the app behaves, better than documentation does.** Tests are the primary
   description of the system. They must read that way.
2. **Not a no-Python project — an only-when-you-need-Python project.** The tests are not Python.
   They are backed by Python underneath, because they are Python tests underneath, but the text a
   person reads is not code.
3. **Layers with clearly defined boundaries.** What a product owner or QA touches is not what an
   automation engineer touches is not what a developer touches. The adapter layer exists for that
   reason and the same reasoning extends upward.
4. **One engine, any system.** CLI, HTTP API, Python function, script, UI, daemon — anything, once
   the adapter is written, and with *the same reading surface* for whoever reads the test.
5. **Integrate, do not rebuild.** Where an industry standard, a concept or a tool already solves
   something, glue it in. Rename ATF's own concepts to match where the standard's word is better.

---

# Part 2 — The repository as it stands

Python 3.11+, `uv`, **no Node, no build step**. FastAPI + htmx (vendored, pinned SHA, no CDN),
Jinja2, one semantic CSS file (`src/atf/cockpit/static/app.css`). Tailwind was considered and
rejected: it needs a build step, and the app computes presentation classes in Python.

## Layout

```
src/atf/          ~9,900 lines — the framework
  catalog.py      YAML types + instances -> a validated dependency graph
  materializer.py provisions a resource's closure, dependency-first, idempotently
  adapters/       the SPI (find/create/delete + optional browse/close) and the registry
                    rest.py, reference.py
  plugin.py       the pytest-bdd plugin: fixtures per type, the generic Given, teardown
  steps.py        the read-and-compare steps (8 claims) and the COMPARISONS table
  context.py      Context — a namespace that also describes what each slot holds (Slot)
  providers.py    ${now+1d 09:00}, ${uuid}, ${env:X}, ${fake:email}; `keyable` per provider
  placeholders.py ${...} resolution
  compare.py      the one comparison procedure (types, booleans, numbers, instants, JSON)
  discovery.py    parses .feature files; introspects pytest for tests, fixtures, step definitions
  runner.py       runs pytest in a subprocess with a progress plugin; parses --json-report
  jobs.py         the same as background jobs with live per-step progress
  store.py        run history under <root>/.atf/runs/*.json
  authoring.py    derive/insert/replace/remove on catalog YAML, validating and rolling back
  cli.py          init | serve | seed | status | run | import-run
  cockpit/        FastAPI + htmx; routers/compose.py (1,225 lines) is the scenario composer
tests/            573 tests (493 functions + parametrisation), 21 modules, 6m27s
selftest/         ATF tested with ATF — 21 scenarios, 32s (~1.5s each)
examples/todo/    a complete example suite against an in-process fake API — 8 scenarios
docs/             mkdocs — tutorial / how-to / reference / explanation
```

## Gates — all green, keep them green

```sh
uv run ruff check                 # line-length 120, rules E,F,I,UP,B,SIM
uv run ty check                   # strict: warnings are errors
uv run pytest -q                  # 573 tests
uv run mkdocs build --strict      # fails on broken links AND anchors
cd examples/todo && uv run --project ../.. python -m pytest -q
cd selftest     && uv run --project ..    python -m pytest -q
```

An acceptance test forbids any literal `http(s)://` under `src/atf/` (except `scaffold.py`) so the
framework names no domain — links go through the `docs(path)` Jinja global, which reads `ATF_DOCS`
first, else `[project.urls] Documentation`. For local work:
`ATF_DOCS=http://127.0.0.1:8000/atf` alongside `mkdocs serve`.

## What already works — do not rebuild

- Declarative catalog with dependency lineage; idempotent, dependency-first provisioning.
- Per-node `lifecycle` (persistent / ephemeral) and `mode` (create / reference).
- Adapter registry with per-environment settings; `rest` and `reference` shipped.
- pytest-bdd plugin: a generated fixture per resource type, one generic `Given`, ephemeral teardown.
- 8 read-and-compare claims and a `COMPARISONS` table the composer reads.
- `Context` describes every slot it holds (kind, fields, count, guessed resource type).
- `${...}` resolved in *any* step's arguments, whoever wrote the step; one evaluation per scenario.
- Runs as background jobs with per-Gherkin-step outcomes; history on disk; flaky detection.
- Browse an environment through an adapter and adopt a record into the catalog.
- Create/copy/edit/delete a resource in the UI: preview diff -> validate -> apply -> rollback.
- A guided composer that offers real step definitions, writes the `.feature`, re-parses, rolls back.
- `atf init` scaffolds a suite where `atf run` passes immediately.

## Measured facts that matter

- `tests/`: 573 tests, **6m27s**.
- `selftest/`: 21 scenarios, **32s**, ~1.5s per scenario. 4 are `@browser` and skip without
  Playwright; that skip is implemented by a hand-written `pytest_collection_modifyitems` hook.
  To run them: `uv sync --group browser && uv run playwright install chromium`.
- `selftest/suites/` holds **4** suite templates — `chained`, `ephemeral`, `broken`, `failing` —
  each a complete consuming project on disk (manifest, catalog, conftest, specs). The `workspace`
  adapter copies one into a temp dir per scenario. Part 6 estimates the migration needs ~30 of
  these, which is §3.4's problem in concrete form.
- **pytest-bdd (installed version) supports `Rule:` and data tables. ATF uses neither.**
- `selftest/specs/features/cockpit.feature` has **no step code at all** — proof the generic
  vocabulary can carry a whole feature.
- `selftest/specs/steps/test_provisioning.py` has 1 `@when` and **5 `@then`** — the problem this
  document is mostly about.

---

# Part 3 — What is wrong today

Five findings, in the order they bite.

## 3.1 The framework can read a system but cannot act on one

`find` / `create` / `delete` / `browse` exist in the SPI. `create` is reachable from Gherkin (the
generic `Given`) and `find` is reachable (every read-and-compare claim calls it). **`delete` and
`browse` are reachable from no scenario at all.** There is no generic `When`. Every action is
hand-written per project, *including* actions the framework already knows how to perform.

For the UI this is fatal: `page`, `element` and `view` are all `mode: reference`, and the only
interaction is an `after:` block inside a `view` body — which is part of *finding* the resource, not
an action the scenario states. So no scenario can say "click Save, **then** the file contains it",
and the click is invisible to a reader.

## 3.2 Generic assertions are technical, so the spec text is technical

Four of the 8 claims name a field — `the {type} "{name}" field "{f}" is "{v}"` and its variants.
That is a struct field access spelled in English. The other four (`exists`, `is gone`, `contains`,
`does not contain`) read fine. Making a suite "generic" therefore means making its specs *less*
readable the moment a value is involved — `Then the command field "exit_code" is "0"` is worse prose
than `Then it exits 0`.

**The proof is already in the repo, and it is uncomfortable.** `cockpit.feature` is the flagship
"no step code at all" feature — and it contains **12** field claims, including:

```gherkin
Then the page "overview" field "status" is "200"
And the element "instance_rows" field "count" is "1"
```

A status code and an implementation detail, in the spec text. That feature would **fail the `atf lint`
rule proposed in §4.2**. Zero step code was bought by pushing technical vocabulary up into the layer
a product person reads. That is the trade the phrasebook exists to undo, and `cockpit.feature` is the
best available evidence that the current vocabulary alone is not enough.

There is no layer between a domain sentence and a primitive claim. That missing layer is the single
biggest gap in the model.

## 3.3 The seam between Python and readable text is broken

A step that returns a `dict` can be asserted on generically. A step that returns anything else
cannot: `steps._result` accepts only a dict or a list of dicts. `selftest`'s CLI client returns an
`Outcome` dataclass — and *because of that one fact* the suite is forced to hand-write five `@then`
steps (`it exits {code}`, `the output mentions "{text}"`, `the output does not mention "{text}"`,
`the backend has {count} {collection}`, `the list points at the owner`).

None of those are domain knowledge. **Every broken seam converts into hand-written assertions, and
assertions in Python are exactly the half a non-developer is supposed to read.**

Related: assertions can only talk about `context.result` — a single anonymous slot — even though
`Context` already tracks every slot with a full description. A scenario with two actions cannot
compare them.

## 3.4 The catalog is an Object Mother

Nat Pryce's critique of the Object Mother pattern describes the catalog exactly: a global set of
named factories where every variation needs a new factory and tests couple tightly to specific ones.
The symptom shows up in this document's own migration estimate (Part 6): **~30 workspace fixture
directories**, one per variation of a catalog or manifest. That is an estimate, not a measurement —
but the shape of it is the Object Mother smell.

The industry answer is Test Data Builders: vary inline, declare only what differs.

## 3.5 Shared-by-default state is why parallelism is banned

`lifecycle: persistent` is the default and `pytest-xdist` is forbidden. These are one fact, not two.
Current practice is unambiguous that ephemeral-per-test isolation is what makes determinism *and*
parallelism possible.

---

# Part 4 — The target model

## 4.1 Four layers

| Layer | Who | Language | Contains |
|---|---|---|---|
| **Spec** | Product / QA | Gherkin (`Feature`, `Rule`, `Scenario`) | Domain sentences only |
| **Phrasebook** | QA / automation | YAML — **no code** | domain sentence -> primitive claims |
| **Catalog** | QA / automation | YAML | Resources, data sources, named actions |
| **Bricks + adapters** | Developers | Python | Actions the framework can't do; how to reach a system |

A **brick** is this document's word for a project-written step definition — almost always a `@when`
that performs an action the framework has no generic way to perform (running a command, calling a
third-party service) and returns what it got back. An **adapter** is unchanged from today: the
`find`/`create`/`delete` implementation for one system.

Every layer is **optional going up**. A suite with only a catalog and primitive claims is perfectly
idiomatic. Dropping to Python must never read as failure — that is the escape hatch that keeps the
learning curve flat, and the documented reason Karate-style DSLs fail at scale.

## 4.2 Three rules that hold the model together

1. **A brick produces a record. A brick never asserts.** The unit of exchange between Python and
   readable text is a record (a dict, a dataclass, or a mapping). A suite writing `@then`
   definitions is a *smell* that the seam has failed — but only a smell, not the target. Counting
   them was tried as the success metric and rejected (Part 7): it rewards turning domain sentences
   into generic field pokes. Rule 3 is the target; this is the diagnostic that usually precedes it.
2. **A phrase expands to primitive claims and bricks — never to another phrase.** Flat, one level,
   no recursion. This is the guard against the phrasebook becoming a badly-designed programming
   language, which is Robot Framework's documented failure mode at scale.
3. **A spec line may not contain a field name, a selector, a status code, a path, or a CLI flag.**
   Mechanically checkable, so it ships as `atf lint`. This replaces "count the `@then`s", which was
   a bad metric — it rewards turning domain sentences into generic field pokes.

## 4.3 The target, written out — the framework/CLI half

```gherkin
Feature: Seeding an environment
  Seeding makes every resource the catalog declares exist — dependencies first, once each,
  and never in an environment that was not opened for writing.

  Rule: What is declared is made to exist

    Scenario: A list is created under its owner
      Given a clean suite "chained"
      When the developer seeds "local"
      Then the owner "primary" exists
      And the list "groceries" belongs to "primary"

    Scenario: Seeding twice changes nothing
      Given a clean suite "chained"
      When the developer seeds "local" twice
      Then there is 1 owner and 1 list

  Rule: An environment that was not opened for writing is refused

    Scenario: Seeding a locked environment touches nothing
      Given a clean suite "chained"
      When the developer seeds "locked"
      Then it is refused because "not in mutable_envs"
      And the owner "primary" is gone
```

```yaml
# specs/phrasebook.yaml — data, no Python. Complete for the feature above.
"a clean suite \"{name}\"":
  - the suite "{name}"                 # `suite` is ephemeral, so every scenario gets a fresh one

"the developer seeds \"{env}\"":
  - I run "atf seed {env}"

"the developer seeds \"{env}\" twice":
  - I run "atf seed {env}"
  - I run "atf seed {env}"

"the list \"{list}\" belongs to \"{owner}\"":
  - the todo_list "{list}" field "owner_id" is "${owners.{owner}.id}"

"there is 1 owner and 1 list":
  - there is 1 owner
  - there is 1 todo_list

"it is refused because \"{reason}\"":
  - the command field "exit_code" is "2"
  - the command field "stderr" contains "{reason}"
```

Note what is *not* in that file: `the owner "primary" exists` and `the owner "primary" is gone` are
primitive claims that already read as domain language, so they go straight into the spec. A phrase is
only written where a primitive would leak a field name, a code or a flag.

**Python for the whole feature: one `@when` that runs a command and returns a dict.** Today the
suite needs six step definitions for this, five of them assertions. The technical vocabulary lives
in one file, which is also the only place to edit when `mutable_envs` is renamed.

## 4.4 The target, written out — the UI half

No catalog nodes for controls. ARIA roles inline, accessible names, nothing structural:

```gherkin
Scenario: A scenario written in the composer lands in the feature file
  Given the cockpit is showing the composer
  When I type "A list belongs to its owner" into the field "Title"
  And I choose the step "the todo_list \"groceries\""
  And I click the button "Save"
  Then the feature "Lists" contains a scenario "A list belongs to its owner"
```

Compare with what `selftest/catalog/views.yaml` contains today:

```yaml
selector: "#compose-form .builder-step:last-of-type .combo-list li[role=option]:not([hidden])"
```

Same capability. The UI scenario is now shaped exactly like the API scenario — which is what
"one engine, any system, same reading surface" actually means.

Role + accessible name is the right choice twice over: it is the human-readability standard *and*
the agent-determinism standard (Playwright MCP is accessibility-tree-first for exactly this reason).

**A correction that matters here: `mode: data` is a third mode, not a rename of `mode: reference`.**
`view.py:177` deliberately makes an absent `reference` node a *blocker* — *"must already exist here
— ATF never creates a reference resource"* — and that is right for what `reference` means: a
precondition ATF cannot create, such as an account someone else provisioned. A page or an element is
not a precondition at all; it is an observation. Conflating them would break real suites. So:

| mode | meaning | absent means |
|---|---|---|
| `create` (default) | ATF makes it exist | it will be created |
| `reference` | a precondition ATF cannot create | **blocks** — keep this behaviour |
| `data` (new) | an observation, a query | nothing; it is simply not there yet |

Only `data` leaves `status`, `seed` and readiness.

## 4.5 Variation without new fixtures

Gherkin data tables — supported by the installed pytest-bdd, unused — kill the Object Mother problem
and replace field-by-field assertions with whole-shape matching (Karate's `match` with fuzzy markers):

```gherkin
Scenario: An overdue task is flagged
  Given the task "milk" but:
    | due_at | ${now-1d 09:00} |
  Then the task "milk" is:
    | title | Buy milk |
    | done  | false    |
    | id    | #notnull |
```

One node in the catalog; N variations in the scenarios that need them.

## 4.6 Actions declared as data

An adapter offers *mechanical verbs*; the catalog names a *domain action* in terms of them; the spec
says the domain action. Nothing in between needs code.

```yaml
task:
  system: rest
  path: /tasks
  natural_key: [list_id, title]
  actions:
    complete: { patch: { done: true } }
    reopen:   { patch: { done: false } }
```

```gherkin
When I complete the task "milk"
```

Because `actions` is data, it is enumerable — so the composer can offer it in a dropdown, which is
the same property that made assertions composable. Optional SPI addition:

```python
class Actionable(Protocol):
    def actions(self, node: Node) -> list[str]: ...
    def act(self, node: Node, record: Record, action: str, ctx: Context) -> Record | None: ...
```

`delete` and `browse` become named actions. Mind the difference: `delete` is in the required SPI
(backends without deletion no-op it via the `NoopDelete` mixin), while `browse` is optional and
guarded by `adapters.can_browse`. So `When I delete the todo_list "groceries"` /
`Then the todo_list "groceries" is gone` needs no code in any project whose adapter really deletes,
and must degrade with a clear message where it does not.

## 4.7 Mixed lifecycle is the differentiator, not a limitation

Shared-vs-ephemeral is normally all-or-nothing. ATF has a dependency graph with **per-node
lifecycle**, so a suite can be both: expensive stable scaffolding (a tenant, an account, an API key)
persistent and seeded once with `atf seed`; volatile per-scenario data ephemeral and torn down.
The research behind this document turned up no tool that expresses the mix — they choose one or the
other — though that is an absence of evidence, not a survey.

This needs one capability — a scenario asking for an isolated instance of a normally-persistent
resource (`Given a fresh todo_list "groceries"`) — and it removes the *semantic* blocker to
parallelism. The engine work (session materializer, listing cache, get-or-create) still remains and
is its own project.

## 4.8 Three surfaces, one introspection API

The cockpit already computes everything needed to answer *"what can be said here?"* — available steps
with their captures, catalog nodes with live status, a resource's fields with current values, the
`COMPARISONS` table. That should be a deliberate API with three renderers:

| Surface | For |
|---|---|
| **Cockpit** | humans — example mapping and the composer |
| **MCP server** (`atf serve` also speaks MCP) | coding agents |
| **`atf docs`** | readers — features as living documentation in the mkdocs site |

The agent case is strategically significant and nearly free. The 2026 failure mode of LLM-authored
tests is that they are *unconstrained* — an agent writes arbitrary brittle automation. An agent that
can only compose from `available steps × catalog nodes × phrases` **cannot write an invalid test**.
The closed, enumerable vocabulary is the constraint that makes generation reliable, and it is the
same introspection the composer needs.

`atf docs` is what makes *"tests describe the app better than documentation does"* literally true.
The pattern is established (Pickles, Augurk, Serenity living docs): emit narrative, Rules, scenarios
and the last-run verdict from the run store as markdown into the existing docs site.

## 4.9 Example Mapping as the composer's model

Story / **Rule** / **Example** / **Question** is the standard BDD discovery practice, and Gherkin's
`Rule:` keyword exists to carry it into the file. Supporting `Rule:` in discovery and rendering it in
the cockpit turns the composer from a step picker into an authoring surface. The genuinely novel
extension — recording *unanswered questions* beside a rule — has no equivalent in existing tools;
CucumberStudio is the nearest and it is a Gherkin editor with no environment or catalog behind it.

---

# Part 5 — The change list

Ordered by dependency. Sizes are relative, not estimates.

| # | Change | Size | Why it is here |
|---|---|---|---|
| 1 | **Records at the seam** — accept dataclasses and mappings, not only `dict` | tiny | §3.3; deletes 3 hand-written `@then`s immediately |
| 2 | **Assertions can name any slot**, not only `result` | small | §3.3; `Context` already tracks them |
| 3 | **Matchers**: `contains`, `does not contain`, counts, `is empty` | small | §3.2; `the output mentions "…"` *is* a matcher |
| 4 | **Phrasebook** — declarative sentence -> primitive claims, flat | **medium — the keystone** | §3.2; the missing layer |
| 5 | **`atf lint`** — no technical vocabulary in spec text | small | enforces rule 3 of §4.2 |
| 6 | **Data tables** — inline variation, whole-shape assertion with `#markers` | medium | §3.4; free in pytest-bdd |
| 7 | **`mode: data`** — a **third** mode beside `create` and `reference`; only it leaves `status`/`seed`/readiness | small | an observation is not a precondition; `reference` must keep blocking (§4.4) |
| 8 | **Catalog `actions:` + optional `Actionable` SPI** | medium | §3.1 |
| 9 | **Browser adapter shipped with ATF** — ARIA roles, accessible names, inline, no declarations | medium | §4.4 |
| 10 | **`Rule:`** in discovery and the cockpit | small | §4.9; free in pytest-bdd |
| 11 | **Auto-collect `.feature` files** — no `scenarios(...)` module required | medium | removes a Python file per feature and an error path in `compose.py` |
| 12 | **Skip when a system is unavailable**, with the reason | small | replaces the raw `pytest_collection_modifyitems` hook in `selftest/conftest.py` |
| 13 | **`atf run -k / --tag / --failed / --json`** (CTRF for `--json`) | medium | `atf run` becomes the only dev loop once pytest is dropped |
| 14 | **`atf docs`** — features as living documentation | small | §4.8 |
| 15 | **Introspection API + MCP server** | medium | §4.8 |
| 16 | **`Given a fresh <resource>`** — per-scenario isolation of a persistent resource | medium | §4.7 |
| 17 | **`atf import openapi`** — derive catalog types from a schema | medium | biggest adoption lever; also feeds the composer's field picker with real types and enums |
| 18 | **Worker-safe materializer** (cache, get-or-create) -> lift the xdist ban | large | its own project; do not bundle |

Items 1–3 are small, independent, and unblock everything readable. Item 4 is the one that changes the
character of the product.

---

# Part 6 — The migration: `selftest/` becomes the only suite

**Goal.** `selftest/` covers the framework and the cockpit, is run by `atf run` and nothing else, and
doubles as the flagship demonstration — `atf serve` on it shows ATF testing ATF, browsable and
runnable in the interface it is testing. `tests/` is deleted.

**Not a port.** Where a unit test asserts on a return value, the scenario asserts on what a person
can observe: an exit code, a record in the backend, an element on a page.

## Where each module goes

| `tests/` module | fns | becomes |
|---|---:|---|
| `test_cockpit.py` | 61 | page / element / view scenarios |
| `test_compose.py` | 58 | UI scenarios that **act** — needs #8, #9 |
| `test_discovery.py` | 35 | cockpit pages + `atf run` output |
| `test_runner_jobs.py` | 32 | activity dock + `atf run` — needs #8, #9 |
| `test_materializer.py` | 29 | workspace variants + `atf seed` / `atf status` |
| `test_rest_adapter.py` | 28 | workspaces against the stub backend |
| `test_steps.py` | 27 | workspaces whose specs use the generic claims |
| `test_authoring.py` | 27 | UI scenarios that act — needs #8, #9 |
| `test_cli.py` | 23 | already the shape of `provisioning.feature` |
| `test_providers.py` | 22 | generated values, observed in the backend |
| `test_catalog.py` | 22 | malformed catalogs + exit codes (use #6 for the variants) |
| `test_context.py` | 21 | held slots in the run report |
| `test_store.py` | 20 | `atf run` twice, `atf import-run`, the history page |
| `test_config.py` | 15 | malformed manifests + exit codes |
| `test_compare.py` | 15 | one workspace, a Scenario Outline truth table |
| `test_plugin.py` | 13 | workspaces |
| `test_acceptance.py` | 11 | a source-rule adapter (suite-side; grep as a data source) |
| `test_placeholders.py` | 7 | workspaces |
| `test_bootstrap.py` | 7 | workspaces |
| `test_selftest.py` | 4 | mutation resources — see below |
| `test_html_select.py` | 16 | **tests `selftest`'s own HTML helper, not ATF** — see risks |

Estimate: **150–200 scenarios**, 4–7 minutes single-worker — comparable to the 6m27 `tests/` takes
today, so no meaningful CI change either way. The inner loop is worse until #13 lands.

## An immediate improvement that needs no framework change

Much of the current suite's ugliness is the suite's fault. `selftest`'s catalog never declares the
resources the sub-suites create, so it hand-writes `the backend has 1 owners`. Declaring them as
observed types against the same stub backend makes those assertions generic **today**:

```yaml
owner:
  system: rest
  path: /owners
  mode: reference          # -> `mode: data` after change #7: an observation, not a precondition
  natural_key: email
```

```gherkin
When I run "atf seed local"
Then the owner "primary" exists
And the todo_list "groceries" field "owner_id" is "${owners.primary.id}"
```

`${...}` already resolves inside step arguments (`plugin.pytest_bdd_before_step_call`). Do this first;
it is free and it validates the direction.

**It is a waypoint, not the destination.** That second line names a field, so it would fail `atf lint`
(§4.2, rule 3). It becomes `And the list "groceries" belongs to "primary"` once the phrasebook lands
— which is exactly the progression this document argues for: generic first, then readable.

## The mutation guard must survive

`tests/test_selftest.py` breaks ATF in four places (topological ordering, the `mutable_envs` gate,
ephemeral teardown, the cockpit's lineage-graph threshold) and asserts the matching scenario goes
red. **A self-test that cannot fail proves nothing.** Deleting `tests/` deletes this.

Re-home it as ordinary ATF: a `mutation` resource type — ephemeral, `create` copies `src/` and
applies a patch, `delete` removes it. Half the plumbing exists: `cockpit_adapter.py` takes an
`atf_src` setting and `specs/atf_cli.py` reads `ATF_SELFTEST_SRC`, both falling back to the working
tree. `selftest_adapters.py::WorkspaceAdapter` has neither and would need one. Then:

```gherkin
Scenario: Breaking dependency ordering turns the right scenario red
  Given the mutation "dependency_ordering"
  When I run the suite
  Then the run has failures
  And the failures mention "a_list_is_created_under_its_owner"
```

This needs `atf run --json` (#13). Make it a mandatory CI gate, not a nicety.

## Sequencing

1. Changes 1–3 (the seam and matchers). Prove them by rewriting `provisioning.feature`.
2. Change 4 (phrasebook) + 5 (`atf lint`). Rewrite `safety.feature`. **Stop and review here** — this
   is where the model either reads well or does not.
3. Changes 6, 7, 10, 11, 12.
4. Port slice: CLI, provisioning, catalog and manifest errors. Delete the matching `tests/` modules.
5. Changes 8, 9. Port slice: cockpit reads, then cockpit actions. Delete the matching modules.
6. Changes 13, 14. Re-home the mutation guard. Delete `tests/`.
7. Changes 15, 16, 17 as they earn their place. 18 separately.

**Nothing is deleted from `tests/` until the scenarios replacing it are green, per slice.**

## Risks, stated plainly

- **Diagnosis.** `selftest/README.md` argues against this whole plan, and argues it well: *"If a
  bootstrap bug lands, this whole suite fails to collect and tells you nothing. The unit tests still
  point at the broken function."* Partly recoverable via the mutation guard and the failure messages
  in `steps.py`, which already name what they compared. Not fully. **This is a deliberate trade and
  it should be made explicitly, not discovered later.**
- **`test_html_select.py` tests the harness, not ATF.** Under this plan `selftest/html_select.py` is
  exercised only through the assertions that happen to use it. Accept, or keep those 16 as the one
  exception.
- **Inner-loop speed** regresses until #13 lands.

---

# Part 7 — Decided, with reasons. Do not re-litigate.

| Rejected | Why |
|---|---|
| **A first-class `Actor`** | Screenplay needs one because it is code-first with nowhere else to hang abilities. ATF has environments and a catalog: a principal is naturally a *resource* whose record carries its credential, and "acting as" is a four-line brick that passes that record to the client. Adding Actor would be a second way to model a principal. **Note:** nothing in the repo demonstrates this yet — `examples/todo/catalog/guests.yaml` is an ephemeral guest with a generated nickname and no credential — so the first suite that needs two principals is where the claim gets tested. **Documented consequence:** the declarative layer is single-principal by construction — a catalog-declared action runs as the environment's credentials. Anything role-dependent is a brick. That is a boundary to write down, not a gap to engineer around. |
| **JMESPath / CEL in spec text** | A path language in a spec makes it *less* readable, which is the opposite of the goal. A gnarly nested query is a legitimate brick that returns a flat record. Also: a single expression cannot be enumerated in a dropdown, which kills both UI composition and reliable agent authoring. |
| **A separate `Task` concept in Gherkin** | The phrasebook covers naming; a Python brick covers composition. A third form is ceremony. |
| **A built-in `process`/`command` adapter** | "Run a command" is exactly the third-party action the philosophy accepts as needing code. Sugar in the core is how frameworks get fat. |
| **Markdown specs (Gauge) or prose (Concordion)** | Gauge's real advantage is *concepts* — taken as the phrasebook. Its Markdown freedom is a documented risk — it gives "more liberty to make the test like a specific document and also more risk of ending up with scripted tests in many different styles" — and unstructured prose cannot be enumerated in a composer, which is ATF's differentiator. |
| **Catalog nodes for UI controls** | That is a Page Object — the thing Screenplay exists to replace — and it puts UI structure in the catalog, which is the domain model. Roles inline instead. |
| **Renaming `adapter` -> `ability`** | "Adapter" is ports-and-adapters, universally understood, and describes the system side. "Ability" only earns its keep once actors exist, and they do not. |
| **"Count the `@then`s" as the success metric** | It rewards turning domain sentences into generic field pokes. Replaced by `atf lint` (rule 3, §4.2). |

**Kept from `ATF-NEXT-SESSION.md`,** because they were learned the hard way:

- Never a badge for an action. Actions are `button` / `a.btn` / `a.btn.primary`.
- Colour carries entity kind. `.pill.loud` at most once per rendered page.
- No blind `<select>` dropdowns — use the combobox in `macros.html` (`ui.combo`).
- Explain at the point of decision, not in cards. Do not paraphrase docs inside the app.
- Errors arrive beside the page (a toast), never as a swap that destroys what you were reading.
- `mutable_envs` gates provisioning and running. It must **not** gate authoring — editing a catalog
  or a `.feature` is a source change, identical whichever environment is selected.
- Catalog edits invalidate every environment's caches, not just the current one.
- `u(path, **params)` is the only way to build a URL. Never hand-write `?env=`.
- Discovery shells out to pytest: slow, cached per environment, must never run twice for one page
  render, must never break a page when it fails.
- An unknown environment is a 404 naming the known ones, never a silent fallback.

---

# Part 8 — Genuinely open

1. **Phrasebook format.** YAML is machine-editable and the cockpit must generate it; a Gherkin-ish
   `Phrase:` block would mean one syntax for everyone. Leaning YAML. Weakest conclusion in this
   document.
2. **`Given a clean suite "chained"`** — should isolation be something a spec *says*, or purely a
   lifecycle policy the spec never mentions? Related to #16.
3. **Whether `Question` cards (Example Mapping's red cards) belong in ATF at all**, or whether that
   is product scope creep into a test framework.
4. **Whether the 16 `test_html_select.py` tests are the one permitted pytest exception.**

---

# Part 9 — Research behind this document

Read these before overturning a conclusion in Part 7.

- Screenplay pattern — <https://serenity-js.org/handbook/design/screenplay-pattern/>,
  <https://serenity-bdd.github.io/docs/screenplay/screenplay_fundamentals>
- Robot Framework layered keywords, and its limits —
  <https://robotframework.org/robotframework-RFCP-syllabus/docs/chapter-01/architecture>,
  <https://github.com/robotframework/robotframework/issues/4472>,
  <https://medium.com/@sanmcdaniel/why-robot-framework-isnt-a-one-size-fits-all-test-automation-solution-b3790818a832>
- Declarative Gherkin — <https://cucumber.io/docs/bdd/better-gherkin/>,
  <https://itsadeliverything.com/declarative-vs-imperative-gherkin-scenarios-for-cucumber>
- Test Data Builders vs Object Mother — <http://www.natpryce.com/articles/000714.html>
- Karate `match` and fuzzy markers — <https://docs.karatelabs.io/assertions/match-keyword/>
- Gauge concepts vs Cucumber — <https://qaskills.sh/blog/gauge-vs-cucumber-bdd-frameworks>
- Example Mapping — <https://cucumber.io/blog/bdd/example-mapping-introduction/>
- Playwright semantic locators — <https://qaskills.sh/blog/playwright-best-practices-locators-2026>
- Playwright MCP, accessibility-tree-first, agent authoring —
  <https://testdino.com/blog/playwright-ai-ecosystem>
- Test data isolation and parallelism —
  <https://totalshiftleft.ai/blog/test-data-management-best-practices-api-testing>
- Living documentation — <https://www.picklesdoc.com/>, <https://augurk.github.io/>,
  <https://johnfergusonsmart.com/living-documentation-not-just-test-reports/>
- OpenAPI-driven testing — <https://schemathesis.io/>
- CTRF report format — <https://github.com/ctrf-io/ctrf>

---

# How to start

Read `docs/explanation/the-model.md`, `docs/explanation/life-of-a-run.md`,
`docs/reference/specs-and-fixtures.md`, `docs/reference/adapter-spi.md`, then
`src/atf/steps.py` and `src/atf/context.py` — they carry the design reasoning in their docstrings.

Then do the free thing first (Part 6, "an immediate improvement that needs no framework change"),
then changes 1–3, and stop for review after change 4. Design the whole of a change before writing
it; the previous sessions lost significant time implementing request by request.
