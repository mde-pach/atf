# Migrating ATF to the design in `docs-next/`

**Read this first, in a fresh context. It is self-contained.**

`docs-next/` is a complete, verified specification for a new version of ATF — 49 pages, written
from scratch. `src/atf/` implements an older, different design. This document measures the distance
between them and says how to cross it.

Everything below comes from six parallel gap analyses that read both the specification and the
current code. Line counts are from those analyses.

---

## 0. Ground rules

**`docs-next/` is authoritative.** Where the code and the documentation disagree, the documentation
wins, unless this document lists the disagreement as an open question in §1.

**`docs-next/_context/DESIGN.md` is the normative summary.** Read it before writing any code — it
holds the model, the exact syntax, the canonical domain and the two vocabularies in one file. Every
page under `docs-next/` was written against it.

~~**`docs/` is the old documentation.**~~ **Done.** `docs-next/` replaced it, and `docs/` is now the
design this document describes. `REFACTOR.md`, which briefed the work before this one, went with it.

**Do not preserve backward compatibility.** There is no released version and no user to break.

---

## 1. Open questions — answer these before writing code

Six things the specification does not settle, found by trying to build against it. Four are cheap.
Two are not.

**All six are now answered.** The two hard ones were prototyped against real pytest before anything
else was written, which is what §6's Phase 0 asks for — the evidence, the alternatives that were
measured and rejected, and what each decision costs are in
[`prototypes/phase0/FINDINGS.md`](prototypes/phase0/FINDINGS.md). The other four were settled as the
phases that needed them landed, and each is recorded above its original wording.

### 1.1 Typed-field lineage — **answered: lineage stops depending on annotations**

The third of the three options this question offered. **A dependency is declared outright, with
`depends_on`. No annotation carries one.**

What settled it was not the string-annotation problem but a worse one underneath it. A typed field
was doing two jobs — saying what must exist first, and carrying the parent's key into the child's
row — and **the second job does not always have anywhere to happen.** A report written per owner
that stores only its slug and a rendered blob has nowhere to put an `owner` field, so under
typed-field lineage it had no edge at all. Not a silent one: none. No amount of care about *when*
annotations are resolved fixes a dependency that has no field to live in.

The two jobs are now separate. `depends_on` is the graph and all the graph is; the fields are what
gets written. A shape with no room for its parent is no longer a shape with no edge.

`@resource` is the base decorator and owns everything belonging to ATF rather than to a system —
`unique_by`, `when_absent`, `scope`, `actions`, `depends_on`. `@adapter("sqlite")` mints `@sqlite`,
which is `@resource` with a system and that system's own options bound. A suite writes `@sqlite`;
ATF only ever reads `@resource`.

**`depends_on` takes kinds and instances, and which one it is says what is meant.** A kind means any
of them — answered by anything already supplied of that kind, and otherwise by the factory. An
instance means that one.

```python
@sqlite(table="lists",   unique_by="slug", depends_on=[Owner])   # any owner
@sqlite(table="reports", unique_by="slug", depends_on=[Owner])   # any owner, and no field can hold it

groceries = TodoList(owner=primary, slug="groceries")            # names which one
scratch   = TodoList(slug="scratch")                             # names none — the factory builds one
quarterly = Report(slug="quarterly", depends_on=[primary])       # names which one, with no field to do it
```

Construction stays ordinary, as `DESIGN.md` writes it: the decorator installs the `__init__`, so the
class a suite writes stays the class a suite writes and construction still touches nothing. Where
the shape does hold the parent, passing it as a value declares the edge and there is no second place
to repeat it, so "nobody writes a dependency twice" survives.

Two things follow. The adapter is handed its parents already resolved, so a foreign key is read from
there rather than from a field that had to exist to carry it. And a factory learns what it needs
from the kind's `depends_on` rather than from its own signature.

`prototypes/phase0/lineage/run_explicit.py` shows the graph still answers everything it is sold on:
provisioning order from one name, teardown in reverse, `atf impact`, `atf unused`, a requirement
that cannot be met named before a run, and a cycle refused.

Separately, and still worth doing: **suites should not write `from __future__ import annotations`,
and ATF should refuse a resource module that does.** It no longer protects lineage, but it keeps the
shape readable and costs five lines. `atf init` must not emit it.

### 1.2 "Two of a kind in scope is an error" — **answered: collection-time, and it is a lookup**

**Caught before the run, by an ATF-owned pass, on one condition: ATF owns step registration.**

The obstacle is not the one this question named. Closure inspection finds nothing. For a scenario,
the whole of `item.fixturenames` is:

```
['_pytest_bdd_example', '_session_faker', 'request']
```

A step's parameters never enter the fixture closure, because pytest-bdd asks for them with
`request.getfixturevalue` while the step runs. There is no closure to inspect and no
`pytest_generate_tests` pass that would help.

What *is* available at collection is the parsed scenario, on `item.function.__scenario__`, with
every step's keyword and sentence. So the arranged half — which instances a `Given` names — is free.
The missing half is which parameters those steps take, and that is a lookup **if ATF keeps the
pattern and the function together when a step is registered**: match the sentence, read the
signature, subtract the placeholders. ATF already registers every step it ships, every step a suite
writes with `atf.when` / `atf.then`, and everything a `@phrase` expands to, so this costs a
dataclass and a list rather than a static analysis.

The whole pass is about 60 lines. It also catches "asks for a kind with no factory and nothing in
scope", which `arrange.md` calls a collection error too.

**The collection pass decides; the fixture obeys.** Resolution is worked out once per test, keyed by
`(nodeid, parameter)`, and the kind fixture reads the answer rather than working it out again. That
is the same table `arrange.md#asking-for-one` promises the editor, so the editor view is a read of
it rather than a second implementation.

`pytest.UsageError` raised from `pytest_collection_modifyitems` reports **every** problem in one go,
runs no test body, and exits `4` — pytest's `USAGE_ERROR`, which is ATF's exit `2` with
`suite_invalid` as the `--json` code.

Two pieces of upstream API, and neither is one of the five private imports risk 4 names:
`item.function.__scenario__`, undocumented but load-bearing inside pytest-bdd's own `scenarios()`;
and `stacklevel=2` when wrapping `@given` / `@when` / `@then`, which is a documented parameter.
pytest-bdd injects its step fixture into the **caller's** module by walking the stack, so wrapping
its decorator without saying so registers every step a suite writes into ATF's own module and no
scenario finds any of them.

**This makes the step registry a prerequisite rather than a convenience**, and it forces one more
thing: **phrases must be expanded at collection.** A phrase expands to more steps, so if expansion
is deferred to run time, collection-time detection is lost for every scenario that uses one.

### 1.2b An instance's name can collide with a kind's — **answered: refuse at startup**

Not in the original six. An instance called `owner` shadows the fixture that means "any `Owner`",
and two kinds whose snake_case names collide do the same. Naming an instance after its own kind is
almost always a mistake, so ATF errors at load with both names, before anything runs.

### 1.2c Two small things the declaration layer will meet — **left for Phase 1**

Neither blocks anything, and both are decided better with the code in front of you than now.

`depends_on` is a constructor keyword, so a resource with a real field of that name cannot declare
it. Detectable at decoration and cheap to refuse.

Where per-instance bookkeeping lives. The prototype puts it in dunder attributes on the suite's own
object; a side table keyed by identity would keep the class's `__dict__` to the suite's fields and
stop a field called `values` or `name` colliding with ATF's.

### 1.3 Composite recognition keys — **answered: a tuple of declared fields**

`unique_by` takes a field name, or several: `unique_by=("region", "code")`. Every one of them must
be a field the resource carries.

**A parent may not be part of the key.** The old design allowed it — `natural_key: [owner_id, slug]`
is in this repository's own fixtures — because the parent appeared as a field holding `${owner.id}`.
Phase 1 removed that: a dependency is `depends_on`, and what a parent is called in a record is the
adapter's business. So `[owner_id, slug]` has no direct translation, and a resource that is unique
only within its parent has to carry a field of its own to say so.

That is the cost of this answer, and it is the reason the alternative was on the table. It buys one
rule with no exception: recognition is over declared values, and lineage is over `depends_on`.

Two refusals come with it, both at load rather than inside a run: a `unique_by` naming a field the
resource does not declare — which used to yield an empty identity, matching whatever came first —
and one naming a field that holds another resource.

`docs-next/reference/arrange.md#recognition` gains the tuple form.

### 1.3 Composite recognition keys were dropped silently — the original question

The current code supports them — `TypeSpec.natural_keys` is a list throughout `model/typespec.py`,
and `remote_keys`, `signature` and `fits` are built on that. `docs-next` only ever shows
`unique_by="email"`. A project recognised by its slug **within an account** has no expression.

Decide: `unique_by` accepts a string or a tuple, and the docs gain the tuple form.

### 1.4 `persistent` is not a pytest scope — **answered: it was never supposed to be**

The question assumed `persistent` had to ride on a pytest scope. It does not, because it is not
about pytest at all: it is a statement about the environment, and pytest has no say in how long a
row outlives a process.

So ATF maps none of its three words onto pytest fixture scopes. Every resource fixture is
function-scoped in pytest's terms — provisioning is idempotent and recognition-based, so asking
twice is cheap — and lifetime is ATF's own ledger. `function` ends with the test, `session` ends with
the run, `persistent` is never removed by ATF.

Two consequences worth stating rather than discovering. Ordering comes from the **lineage graph**
rather than from pytest's fixture ordering, so the sentence in `one-engine-two-surfaces.md`
promising pytest's ordering needs rewriting. And the run's ledger cannot live on a test's scope — a
`session` resource is made by whichever test needed it first, so it is held on the session and torn
down in `pytest_sessionfinish`.

### 1.4 `persistent` is not a pytest scope — the original question

`function` and `session` are pytest's, and `one-engine-two-surfaces.md` promises they mean exactly
what pytest means, ordering included. `persistent` has no equivalent: it must ride on `session`
while suppressing teardown and consulting recognition instead.

Decide: how that is implemented, and whether the promise about the other two survives it.

### 1.5 `error` is a fourth outcome word — **answered: fold it into `failed`**

Three outcome words survive: `passed`, `failed`, `skipped`. `ERROR` is folded into `failed` at the
boundary, and the reason travels in the message rather than in a state word.

**The stranded case goes to `failed` with its reason.** A stranded test is one that was collected
and never reported anything, because the pytest subprocess died underneath it — a crash, a kill, a
timeout. It did not pass and it was certainly not skipped, so a run that produced one must not go
green. `runner.py:257-261` keeps its behaviour; only the word changes.

Phase 4's, since it lives in the record.

### 1.5 `error` is a fourth outcome word — the original question

The specification allows three: `passed`, `failed`, `skipped`. `ERROR` appears across
`run/runner.py`, `store.py`, `report.py`, `verdict.py` and `cli.py`, and carries the stranded-test
path (`runner.py:257-261`, `STRANDED`).

Decide: fold `error` into `failed` at the boundary — probably right — and say where the stranded
case goes.

### 1.6 The continuation sentence has no subject — **answered in Phase 3**

A `Given` line that is only a field claim continues the resource the previous `Given` named, and it
is an error when no such line came before it. It cannot collide with a slot claim, because a slot
claim is a `Then`.

The parse rule was the easy half. The half that mattered is that a varied resource is **held back**
until something reads it, so several sentences make one resource with several fields changed rather
than one resource per sentence with a row left behind at each step.

### 1.6 The continuation sentence has no subject — the original question

```gherkin
Given the todo_list "groceries" but "slug" is "weekly"
And "owner" is "null"
```

The `And` line binds to the previous line's resource. That is stateful parsing, and it is ambiguous
against a slot claim of similar shape.

Decide the parse rule, or change the syntax so each line carries its subject.

---

## 2. What this is, in one number

| | lines |
|---|---|
| survives largely as is | ~3,500 |
| changes | ~2,700 |
| deleted | ~3,300 |
| deferred, not deleted (`rest.py`, `http.py`) | 456 |
| genuinely new | ~4,400 |

Against **15,885** lines today. About a quarter survives untouched, and the new work is larger than
anything kept. **This is a rewrite that reuses parts, not a refactor.**

### Where it stands

| Phase | |
|---|---|
| 0 · decide the two hard questions | done — [`prototypes/phase0/FINDINGS.md`](prototypes/phase0/FINDINGS.md) |
| 1 · declaration layer, graph, manifest, loader | built |
| 2 · adapter SPI, engine, scopes, `filesystem`/`process`/`command` | built |
| 3 · step registry, feature reader, phrases, claims, plugin | built |
| 4 · command line, record, history, reports | built |
| 5 · ATF's own suite | 49 scenarios over ten features, three times clean |
| 6 · the editor | built — seven views and the composer, all reading one core |
| 7 · `rest` | built — `import openapi` dropped, see below |
| the cutover — the deletes, and `tests/` | done |
| the command list, whole | done — including `atf edit --mcp`, ten tools over the same core |

**There is one stack now.** 202 files went; `src/atf` is 7,000 lines against 15,885, and `tests/`
is 303 lines of ATF suite in place of 892 Python tests. `atf` is `atf.entry:main`, and `pytest-bdd`
is out of `pyproject.toml`.

Three things moved rather than died, because the new stack was built on them: the step-pattern
grammar (`spec/patterns.py` → `patterns.py`, minus the old design's provisioning constants), the
HTTP client (`adapters/http.py` → `systems/http.py`), and `model/compare.py` with `text.py` — which
is §3's "seed of the reconciliation diff", and it seeded exactly that.

---

## 3. What survives — start here, do not rewrite it

- `model/compare.py` (271) — value comparison and markers. **The seed of the reconciliation diff.**
- `model/records.py` (94), `model/text.py` (18) — unchanged.
- `Materializer.topo()` (`engine/materializer.py:185-204`) and `Catalog.closure` — the graph walk.
- Get-or-create in `_provision()` (`materializer.py:388-403`) — becomes find/create/update.
- **Per-environment adapter construction already exists** — `engine/bootstrap.py:34-36`,
  `session.py:76-93`. The target design is already how the code works here.
- `run/runner.py` (336) — the whole subprocess and event spine.
- `run/store.py` (257) — atomic save, prune, `_load` already returns `None` on a corrupt file.
- `run/report.py` (61) — becomes the registered `ctrf` writer unchanged.
- `run/verdict.py` (56) — already produces the four verdict words.
- `spec/patterns.py` (63) — `fill`, `pattern_regex`, `CAPTURE_RE` are exactly what `@phrase` needs.
- `spec/vocabulary.py` ~60% and `spec/steps.py` ~55% — **keep the data/implementation split.**
  `steps.py:287-289` already synthesises a step function per `Comparison` row; adding `is #{kind}`
  is one row plus one branch in `_held`.
- `spec/collect.py` — feature collection with no binding module survives; only `_nothing`
  (`:56-57`) changes, to carry a generated signature.
- `suite/discovery/parse.py` — `parse_specs`, `parse_feature`, `matching_step`, and `context_use`'s
  AST walk.
- `suite/lint.py` (269) and `suite/docs.py` (294) — nearly whole.
- `adapters/browser.py` role/name reading — already pure Playwright.

---

## 4. What is deleted, and why

| What | Where | Lines |
|---|---|---|
| YAML catalog loader | `model/catalog.py:185-435` | ~250 |
| `typespec.py` entirely | `model/typespec.py` | 135 |
| `${...}` placeholders | `model/placeholders.py` | 105 |
| Provider registry | `model/providers.py` | 241 |
| Accessible-name computation | `adapters/control.py` minus the `Control` dataclass | ~350 |
| The `html` system | `adapters/html.py` | 104 |
| The `reference` adapter | `adapters/reference.py` | 23 |
| Adapter `Context` protocol, `from_settings` | `adapters/__init__.py` | ~65 |
| Editor authoring | `cockpit/routers/authoring.py` + `suite/authoring.py` | 891 |
| Editor glossary | `cockpit/glossary.py` | 264 |
| The context scratchpad | `spec/context.py` + `plugin.py:46-66` | ~260 |
| YAML phrasebook loader | `spec/phrasebook.py:52-231` | ~150 |
| Shape / table claims | `vocabulary.py` + `steps.py:115-186` | ~108 |
| Scaffolded fake backend | `suite/scaffold.py:120-206` | ~300 |
| Catalog YAML in tests | `tests/catalog/`, `tests/suites/*/catalog/` | ~762 |
| The OpenAPI importer | `suite/openapi/` | 741 |

Three deletions deserve their reasoning recorded, because each looks contentious and is not:

**`control.py`.** `Page` is imported in exactly one place — `html.py`, which goes. `browser.py`
imports only the 13-line `Control` dataclass and calls `page.get_by_role(role, name=…)`.
Playwright's own locators already do the whole job.

**Authoring.** `docs-next/reference/the-command.md` has no add/edit/delete-resource command, so an
authoring UI is by definition the privileged path `the-editor.md` forbids. Writing Python class
declarations into a user's module is codegen the specification never asks for. Keep the temp-copy
validation and byte-for-byte rollback as a *pattern*; delete the code.

**`spec/context.py`.** The scratchpad is the second arrangement path that
`explanation/one-engine-two-surfaces.md` exists to remove. Slots survive as a concept in the Act
band; the object does not.

`adapters/http.py` (226) is **reused as it stands** — it depends on `httpx` and nothing else, and
`systems/rest.py` is built on it. `adapters/rest.py` (230) is superseded by that and goes with the
rest of `adapters/`. `sqlite` is never shipped: it is the worked example living in a suite's own
`adapters/sqlite.py`.

---

## 5. What must be built — nothing like it exists today

| What | ~lines | Notes |
|---|---|---|
| `@resource`, and `@adapter("x")` minting `@x(...)` on top of it | 250 | The base decorator owns `unique_by`, `when_absent`, `scope`, `actions`, `depends_on`; the system decorator adds a system and its options |
| Module scanning for instance names | 120 | Import `resources:` modules, bind each instance to its variable name |
| `depends_on` and the graph read off it | 60 | **See §1.1.** Was 200 for typed-field resolution; there is nothing left to resolve |
| Reconciliation diff engine | 250 | ATF computes `changes`; partial-spec semantics |
| `filesystem` and `process` adapters | 250 | Green-field; neither exists |
| `atf.Unreachable` | 50 | **Zero occurrences in `src/` today** |
| `Options` / `Settings` typed validation | 150 | Today `TypeSpec.config` is untyped |
| Three scopes + reverse-lineage teardown | 120 | Today: two lifecycles, teardown in arrival order |
| Per-instance and per-kind fixtures, and the collection pass | 600 | **See §1.2.** The pass itself is ~60 of these |
| The step registry ATF owns | 90 | **See §1.2.** Pattern and function kept together; §1.2 depends on it |
| `@phrase` discovery, nesting, cycles | 350 | **Rests on five private pytest-bdd imports.** Expansion must happen at collection — see §1.2 |
| Marker registry | 120 | `@marker` returning `(bool, message)` |
| `atf.claims` public library | 180 | Today comparison is welded to `pytest.fail` |
| `atf impact`, `unused`, `--select` | 300 | Needs the graph as a first-class object |
| Report-format registry | 60 | `as_ctrf` slots in |
| The command line, on `click` | 250 | Global flags before **and** after the subcommand; three exit codes |
| History as files | 200 | One JSON per run, fifty per environment, a corrupt one skipped |
| `@claim` and `@check` registries | 120 | A claim is a `Then` that answers `(held, message)` |
| The public API in `atf/__init__.py` | — | **Currently a version string and nothing else** |
| `core.py`, the one API | 300 | What the command, the editor and an agent all read |
| The editor, on that core | 350 | Seven views, none of them holding logic |
| The `browser` system | 120 | Role and accessible name, never a selector |

---

## 6. The order to do it in

Each phase ends somewhere the suite can run. Do not start a phase before its predecessor lands.

### Phase 0 — decide §1.1 and §1.2 — **done**

Both are prototyped against real pytest in `prototypes/phase0/`, and both are answered above.
Neither place the design could have failed to be implementable did.

- `lineage/run_explicit.py` — the graph, declared with `depends_on` and no annotations
- `lineage/run_no_future.py` — what `from __future__ import annotations` changes
- `lineage/run.py` — the superseded evidence for not reading lineage off annotations at all
- `fixtures/run.sh` — the pytest half: 10 resolutions pass, 4 problems refuse the run

The two halves share one declaration layer rather than each keeping a copy, so a kind fixture
building its factory's dependencies from `depends_on` — the only source left — is checked, not
assumed.

### Phase 1 — the public API and the declaration layer

`atf/__init__.py` exports `resource`, `adapter`, `claim`, `marker`, `claims`, `when`, `then`,
`command`, `browser`, `filesystem`, `process`, `Update`, `Unreachable`. Then `@resource` and the
system decorators built on it, module scanning, `depends_on` and the graph read off it, the new
manifest (five keys, `mutable` per environment, no `clients:`).

**Deletes**: catalog loader, `typespec.py`, `placeholders.py`, `providers.py`.
**Done when** a `resources.py` loads and the graph is readable without touching a network.

### Phase 2 — the adapter SPI and the engine — **built, deletes outstanding**

`spi.py` (the four methods, the two optional ones, `Options`/`Settings` checked before a run),
`environment.py` (one adapter per system per environment, `Ground`), `reconcile.py` (the diff, the
three scopes, reverse-lineage teardown), `systems/filesystem.py`, `systems/process.py`,
`commands.py` and `python -m atf`.

**Nine status words became three.** `present` · `absent` · `unreachable` is what an environment
says; what a pass *did* — `created`, `updated`, `unchanged`, `left alone` — is a separate word, and
`blocked` is gone.

**Done when** `atf status` and `atf make` work against a real environment: they do, in
`examples/todo` (SQLite, an adapter the suite owns) and `examples/shipped` (`filesystem` and
`process`, no adapter at all). Both READMEs show the output.

The deletes — `html.py`, most of `control.py`, `reference.py`, the `Context` protocol — are
outstanding for the reason Phase 1's are: their consumers are the cockpit, the agent surface and the
old CLI, which are Phases 4 and 6.

#### Where the diff landed, on risk 2

`compare.matches` is reused as written. `"1"` and `1` are the same value, and two spellings of one
instant are one instant. The rule is stated at the top of `reconcile.py` rather than left implicit.

One thing it does **not** cover, and the cost is real: a field holding a parent resource is left out
of the diff. What a parent means in the child's row — a foreign key, an embedded document, a path
segment — is the system's business and only the adapter knows it, so `declared_values()` skips
resource-valued fields. **A changed parent is therefore not reconciled.** Recognition still catches
it when the parent is part of `unique_by`; it does not when the parent is merely a column.

### Phase 2 — the adapter SPI and the engine

New signature (`find`/`create`/`update`/`delete`, no context object, `resource` argument).
Reconciliation with ATF computing `changes`. Three scopes, reverse-lineage teardown.
`filesystem` and `process` adapters. Collapse nine status states to three.

**Deletes**: `html.py`, most of `control.py`, `reference.py`, the `Context` protocol.
**Done when** `atf status` and `atf make` work against a real environment.

### Phase 3 — the pytest layer — **built, deletes outstanding**

`steps.py` (the registry ATF owns), `feature.py` (the reader), `phrases.py`, `vocabulary.py` (the
sentences ATF ships), `claims.py`, `markers.py`, `runtime.py` (what one test holds), `plugin.py`,
`systems/command.py` and the `shell` fixture.

**Done when** the same behaviour passes as a pytest function and as a scenario, from one engine:
`examples/todo/specs/` has both, 14 pass, and they run twice cleanly. `examples/todo/refused/`
keeps the three mistakes the collection pass catches, so the messages can be read.

#### pytest-bdd is gone, and risk 4 with it

Once ATF owned step matching, phrase expansion and fixture resolution — all of which §1.2 forced —
what pytest-bdd still did was collect feature files. ATF reads them itself now, in `feature.py`, over
the deliberately small language `DESIGN.md` specifies: no DocStrings, no data tables, `Examples` the
only table there is. That is the same hand-rolled shape `suite/discovery/parse.py` already had.

**This removes the five private imports risk 4 is about**, rather than managing them. `pytest-bdd`
can come out of `pyproject.toml` when `spec/` goes.

#### §1.6 answered, and how

The continuation sentence binds to the resource the previous `Given` named, and it is an error —
not a guess — when no such line came before it. What made it work was not the parse rule but
*when* the patch is applied: a varied resource is **held back** until something reads it, so
`but "slug" is "weekly"` followed by `And "owner" is "null"` provisions one resource with two fields
changed. Applying each sentence as it arrives would leave an intermediate row behind.

#### The deletes

`context.py`, the YAML phrasebook and the shape claims are superseded by `runtime.py`, `phrases.py`
and `claims.py`, and come out with the rest of `spec/` once the cockpit and CLI stop importing it.
The scratchpad is genuinely gone as a concept: `Scope` holds slots and a ledger, and **cannot
provision** — arranging goes through `reconcile.ensure` whichever surface asked.

### Phase 3 — the pytest layer

**Build the step registry first, or with the Gherkin compiler — not after.** §1.2's collection-time
promise rests on it, and phrases must expand at collection for the same reason.

Per-instance and per-kind fixtures. The Gherkin→fixture-request compiler. `atf.claims` as a
library. The marker registry. `@phrase`. One-field-per-sentence variation.

**Deletes**: `context.py`, the YAML phrasebook, the shape claims, the `html`-backed interface steps.
**Done when** the same behaviour passes as a pytest function and as a scenario, from one engine.

### Phase 4 — the command line and the record — **built, deletes outstanding**

`record.py` (runs, outcomes, the verdict fold, history, flakiness), `reports.py` (the registry, with
`ctrf` reading and writing), `runner.py` (selection, and turning what pytest said into outcomes),
`scaffold.py`, `commands.py`, `registries.py` (`@claim` and `@check`) and `entry.py`.

**Done when** CI can gate on it. It can: three exit codes, `--json` carrying the four machine names,
`--report ctrf:` round-tripping through `import-run`, `--failed` reselecting exactly what failed,
and `atf init` writing a suite that runs.

#### The command line is Click's, not hand-rolled

The spec writes `atf make readonly --json`, with a global flag **after** the subcommand. A manifest's
`command: { prefix: "atf --config …" }` can only put one **before**. Both positions are real, and
hand-rolling that merge was a mistake caught in review — it is one shared decorator on Click now.
`click` moves from a transitive dependency of `uvicorn` to a declared one, because ATF's command
line is built on it.

#### History is files

One JSON per run under `.atf/history/`, named by run id, fifty per environment. A corrupt file is
reported on stderr and skipped, never raised — the tests still run. A `.db` beside the manifest was
never an option: a suite's own `sqlite` adapter arranges resources in exactly such a file, so one
there would read as something under test.

#### §1.5, landed

There is no fourth outcome word. A stranded test — collected, and never heard back from because the
subprocess died — is `failed` with its reason in the message, so a killed run cannot go green.

### Phase 4 — the command line and the record

Three exit codes with the reason in the message. `seed`→`make`, `lint`→`check`, `serve`→`edit`.
`impact`, `unused`, `--select` with the empty-selection split. Report registry. History as one JSON
per run under `.atf/history/`. `atf init` writing three files.

**Done when** CI can gate on it.

### Phase 5 — ATF's own suite — **built except the editor**

`selftest/` is an ATF suite testing ATF. It scaffolds a workspace on disk, runs `atf` against it
through the `command` prefix, and claims on what came back. **No backend, no stub server, no shared
port** — and no adapter at all, because there is no system ATF needs to test itself that ATF does not
already ship.

**Done when** it runs twice in a row cleanly. It does: four scenarios, twice, leaving nothing behind.
That property is the whole point of running it twice — one green run says nothing about residue, and
with the workspace function-scoped a survivor would be found by recognition on the next run and
tested instead of made.

#### It found five bugs, which is the argument for doing it at all

None of these were visible from reading the code, and all four are the shape that only appears when
one suite drives another.

1. **`atf make` on an immutable environment exited `0`.** It reported each resource it left alone
   rather than refusing. It now exits `2` with `environment_immutable`, before touching anything.
2. **A relative path in an environment's settings resolved against the working directory**, not
   against the manifest. `filesystem: { root: . }` wrote into wherever `atf` was invoked from, so
   `find` asked about one place and `create` wrote to another. It would bite any suite run from a
   subdirectory, not only a nested one.
3. **`--config` did not reach the plugin.** `atf run --config X` loaded the right manifest for
   selection, and then the plugin searched upwards from the working directory and found a different
   one. Only a suite running another suite can see this.
4. **A directory resource could not own its tree.** Teardown would only remove an empty directory, so
   a workspace the thing under test had written into could never be removed. A resource declaring
   `files` now owns what is under it.
5. **A deselected test was recorded as failed.** The run collector marks anything collected and never
   heard from as stranded, which is right for a killed subprocess and wrong for `-k` or `--tag`. Any
   filtered run reported every test it deliberately skipped as a failure. Found by the first
   scenario that filtered one.

#### The phase order has 5 depending on 6

`how-atf-tests-itself.md` specifies `the-editor.feature`, which drives `atf edit` — and the editor is
Phase 6. So the dogfooding suite cannot be finished before the phase after it. `the-editor.feature`
and the `browser` system are the outstanding part; everything the command line reaches is done.

#### Where it lives

`selftest/`, rather than the root `atf.yaml` and `tests/` the specification writes, because the old
suite still occupies `tests/`. It moves when that goes, and the move is a rename.

### Phase 5 — ATF's own suite

Rewrite `tests/` against `docs-next/advanced/how-atf-tests-itself.md`, which specifies it in full.
Systems: `command`, `browser`, `filesystem`, `process`. **No backend, no stub server, no shared
port** — which removes the one-suite-at-a-time constraint that costs the most time today.

**Done when** it runs twice in a row cleanly. One green run says nothing about residue; with
`persistent` the default, expected residue is not a leak — the leak is a `function` or `session`
resource that outlived its scope, and it surfaces on the *next* run in a different test.

### Phase 6 — the editor — **built, and it finished Phase 5**

`core.py` (the one API), `editor.py` (`atf edit`, seven views), `systems/browser.py`, and the
interface claims. `the-editor.feature` now drives a real headless Chromium against a real `atf edit`
over the scaffolded workspace, so **ATF's own suite is complete**: five scenarios, four consecutive
clean runs, no residue and no stray processes.

**The violation is fixed by construction.** Every view is a call into `core.py` and the editor holds
no logic of its own — no query, no state, no second opinion about what a resource is. `core.py`
exists precisely so the seven-of-eight-routers problem cannot come back: there is one place to read
from, and the editor's Make button calls the same `commands.make` the command line calls.

The editor knows about no specific type, system, claim or marker. It renders the registries, so a
suite registering `@redis` gets a catalogue entry, a graph node and a composer sentence with no
editor code changing.

The graph as its spine. "What would change" in the inspector, which cannot exist before Phase 2.
Six views. Fix the existing violation: **seven of eight routers reach into `session`/`materializer`
directly**, so the no-privileged-path rule is already broken and will re-rot without one core API
and a scenario per view.

### Phase 7 — `rest` — **built. `import openapi` is dropped.**

`systems/rest.py` is the fifth shipped system, on the new SPI. `adapters/http.py` is reused as it
stands, which is what "deferred, not deleted" was for: it depends on `httpx` and nothing else.

**The three lookup strategies `arrange.md#recognition` describes, and a resource says which by what
it declares.** `filter` — `GET /owners?email=…`, chosen by `list_filter`. `path` — `GET /owners/{email}`,
chosen by `read_path`. `scan` — page the collection and match client-side, the default, because it
needs the API to support nothing at all.

`examples/rest` is the same two resources as `examples/todo` against an HTTP API, so the two
`resources.py` can be read side by side: `depends_on` identical, `unique_by` identical, only the
decorator and its options different. The API is itself a `@process` resource with `port=8799`, so
the suite starts it, waits for the port and stops it — three scenarios, twice, no strays.

#### `import openapi` is dropped, and the ground rules say so

**`docs-next/` mentions OpenAPI nowhere.** The normative command list in `DESIGN.md` is
`init · status · make · run · check · docs · edit · impact · unused · import-run`, and `import-run`
reads a CTRF run record rather than a schema. There is no `schemas:` key in the five-key manifest
either, so the named place the old importer was re-run from does not exist.

§0 says the documentation wins where it and the code disagree, unless §1 lists the disagreement as
an open question. It does not. So `suite/openapi/` (741 lines) goes, and the alternative — building
an emitter for a command the specification does not have — would have been inventing surface rather
than migrating it.

The half worth remembering is `score.py`: it guesses a recognition key and *learns the convention
from what a project already keys on*, so a guess corrected by hand becomes evidence for the next
import. If an importer is ever wanted back, that idea is the part to bring, not the YAML writer.

---

## 7. Risks, ranked

1. ~~**Typed-field lineage silently losing an edge** (§1.1). No error, wrong result.~~ **Closed, not
   mitigated.** Lineage is declared with `depends_on`, so there is nothing to resolve and nothing to
   resolve wrongly. This was the worst failure mode in the system and it no longer exists.
2. **The reconciliation diff has no safe default.** `compare.matches` is deliberately loose —
   `str(actual) == str(expected)`, `same_instant`. Reuse it and `"1"` versus `1` is correctly
   unchanged; tighten it and every run writes to the real environment; loosen it and real drift goes
   uncorrected. This lands on shared environments where a wrong answer is expensive.
3. ~~**Fixture ambiguity as a collection error** (§1.2) — may require machinery pytest does not
   offer.~~ **Closed.** It needs no machinery pytest lacks; it needs ATF to own its step registry.
   What remains is that the registry is now on the critical path — see risk 4.
4. ~~**Nested phrases on five private pytest-bdd imports** (`spec/phrasebook.py:20-24`).~~
   **Closed by Phase 3, by removing the dependency.** §1.2 had already forced ATF to own step
   matching, phrase expansion and fixture resolution; what pytest-bdd still did was read feature
   files, and `feature.py` does that over the small language `DESIGN.md` specifies. Nesting,
   keyword inference and the failure chain are ATF's own code now, with no upstream to outgrow.
5. **Reverse-lineage teardown across three scopes.** Today teardown is best-effort and unordered.
   Wrong order leaves residue that fails the *next* run somewhere else. **Confirmed real, and
   handled**: Phase 5 found three separate ways residue escaped — an unremovable non-empty
   directory, a path resolved against the wrong root, and `session` scope with no run-level
   ledger to tear down from. Each surfaced only on the second run, exactly as predicted.
6. ~~**`atf edit` importing the user's `resources.py`** in a long-lived process.~~ **Closed.**
   `Editor.reload()` re-reads on every request, and the loader's eviction of a cached module whose
   file differs is what makes that safe. Refreshing re-asks, so what a page shows is what the
   environment said a moment ago — which is what `arrange.md#recognition` promises anyway.
7. **Module identity.** A resource's name is its variable's name, so importing `resources` and
   `suite.resources` declares two sets with the same names. Today ids come from file paths —
   deterministic and diagnosable by reading YAML. **Reduced by §1.1**: nothing resolves a dependency
   by name any more, so the silent half is gone — a `depends_on` entry is the class object itself.
   What is left is that two kinds of the same name want the same fixture, which §1.2b refuses at
   startup.

---

## 8. Known bug in the current code, unrelated to the migration

`adapters/browser.py:139` sets `name=name or text`, echoing the requested name rather than computing
the accessible one — so an unfiltered read returns element text, not the ARIA name. Fix with
Playwright's aria snapshot; do not keep `control.py` for it.

---

## 9. Where to look things up

- **The model, the syntax, the canonical domain** — `docs-next/_context/DESIGN.md`
- **What each concept is** — `docs-next/reference/`, one page per band, every definition owned once
- **The whole suite, shown whole** — `docs-next/advanced/how-atf-tests-itself.md`
- **Why a decision was made** — `docs-next/explanation/`, each page naming what was rejected
- **What Phase 0 decided, and what it measured to get there** —
  [`prototypes/phase0/FINDINGS.md`](prototypes/phase0/FINDINGS.md)
- **Where the specification stopped short and somebody chose** — six judgements, each with what it
  does now and the alternative: <https://claude.ai/code/artifact/0ee0bcdc-f9be-4493-9b12-ea22bf3bf8b9>
- **The new stack, working** — `examples/todo` (a suite with its own adapter, both surfaces),
  `examples/shipped` (`filesystem` and `process`, no adapter), `selftest/` (ATF testing ATF)
- **Read it served** — `uv run --group docs mkdocs serve -f mkdocs-next.yml -a 127.0.0.1:8001`
