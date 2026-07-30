# ATF refactor brief

A standalone working document. It assumes no prior conversation: read it top to bottom and execute
the work plan in section 10.

Every file:line reference in it was verified against the source at the time of writing. Re-verify
before changing anything — section 2 gives the commands that re-derive each count.

---

## 1. What this codebase is

ATF ("Another Test Framework") is a Python test framework where a test is a readable Gherkin spec
that declares the resources it needs, and the framework makes those resources exist before the test
runs. Four moving parts:

- **Catalog** — resources declared as YAML with dependency lineage. Purely declarative.
- **Materializer** — provisions a resource and its dependency closure into an environment,
  idempotently, delegating the *how* to a pluggable adapter per backend.
- **Specs** — pytest-bdd scenarios. Each resource type becomes a generated pytest fixture; generic
  steps provision and assert on any resource named in a scenario.
- **Cockpit** — a FastAPI + htmx web app rendering the catalog, scenarios and run history.

There is also an MCP server (`mcp.py`) offering the same vocabulary to an agent, and a CLI (`atf
init|status|seed|run|lint|docs|serve|import-run`).

Size: 49 Python modules, ~16k lines, plus ~3.2k lines of templates, CSS and inline JS. `ruff check`
and `ty check` both pass clean today, and must still pass after every step below.

ATF is set up on itself: `atf.yaml` is at the repo root, and `tests/` holds both an ATF suite whose
system under test is ATF, and ordinary Python tests.

### Verdict this refactor starts from

The design at the edges is genuinely good — a structural adapter SPI built on Protocols, a
declarative catalog, a clean manifest parser. The decay is concentrated in one place and radiates:
**the engine's two most-used return values are untyped string-keyed dicts.** Most of section 4 is
downstream of that, including findings that look unrelated to it.

---

## 2. Working rules

**Verification commands.**

```sh
uv run ruff check                 # must stay clean
uv run ty check                   # strict, zero suppressions; must stay clean
uv run pytest -q                  # the full suite: ~7 minutes. Milestones only, not per edit
uv run pytest -q tests/test_engine.py   # a single module: seconds
uv run atf lint                   # needs nothing running
```

The full suite takes about seven minutes. Do not run it after every edit — run it at the end of each
numbered step in section 10. Long runs should be backgrounded, not blocked on.

**Re-deriving the counts in this document.** Every number below is reproducible. Examples:

```sh
# untyped status reach-ins (section 4, A1)
grep -rn '\.get("status"\|\.get("identity"\|\.get("record"\|\["identity"\]' src/atf --include='*.py'

# dataclasses sharing a field signature (A5)
python - <<'EOF'
import ast, pathlib, collections
sig = collections.defaultdict(list)
for f in sorted(pathlib.Path("src/atf").rglob("*.py")):
    for n in ast.walk(ast.parse(f.read_text())):
        if isinstance(n, ast.ClassDef) and n.decorator_list:
            fields = tuple(s.target.id for s in n.body
                           if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name))
            if len(fields) >= 4: sig[fields].append(f"{f}:{n.lineno} {n.name}")
for fields, where in sig.items():
    if len(where) > 1: print(" / ".join(where), "->", ", ".join(fields))
EOF

# the ref_field identity rule (B1)
grep -rn 'ref_field' src/atf --include='*.py'
```

**Scope.** This document authorises the changes it describes. It does not authorise scope creep:
no new features, no dependency additions, no behaviour changes beyond those explicitly named. Where
a step would change observable behaviour, that is called out.

---

## 3. Standards this refactor is held to

These are the owner's stated standards. They decide the judgement calls.

1. **Readability beats everything.** A longer, explicit variable name beats a shorter one. Readable
   code beats optimised code. Do not trade clarity for cleverness or for a micro-optimisation.
2. **Code self-documents.** Contextual documentation only where it adds value.
3. **A comment gives meaning to a scope, or states what a function does** — its contract and its
   edge cases. It does **not** argue why the code is this way, name alternatives considered, narrate
   what the code used to be, or cite prior art. Rationale is commit-message or spec material, not
   comment material. Full rule and enforcement in section 8.
4. **Clean boundaries between concepts.** Coupling is the symptom of a boundary that was never
   drawn. A concept has one home; other layers import it rather than re-deriving it.
5. **Well-crafted patterns.** Factored, reusable, maintainable. A rule that exists in four places is
   a missing abstraction, not four small conveniences.

---

## 4. Design defects

Ordered by leverage. A1 and A2 are the ones that unlock the rest.

### A1. The engine returns dicts where it should return domain types

Two functions produce nearly everything the rest of the system consumes, and both return
`dict[str, Any]`.

**`Materializer.status()` → `dict[str, dict[str, Any]]`** (`src/atf/materializer.py:289`). The inner
mapping has four keys — `status`, `detail`, `identity`, `record` — and `_status_of`
(`materializer.py:299-315`) returns a *different shape per branch*: three keys when absent, two when
unsupported, four when present.

Every consumer therefore reaches in by string literal with a default. **26 sites across 10 files:**
`introspect.py` (×6), `cockpit/view.py` (×3), `cockpit/routers/catalog.py` (×8),
`cockpit/routers/authoring.py` (×2), plus `routers/search.py`, `routers/overview.py`,
`cockpit/deps.py`, `cli.py`, `store.py`, `jobs.py`.

**`Materializer.materialize()` → `dict[str, Any]`** (`materializer.py:334`) with keys `results` (a
list of dicts keyed `id`/`action`/`ok`/`detail`/`record`) and `records`. **15 literal reach-ins** in
`cli.py`, `jobs.py` and `materializer.py` itself. The shape also mutates mid-flight:
`materializer.py:405` does `outcome.pop("record")`, so a result dict has five keys before that line
and four after.

Consequences, several of which appear below as separate findings:

- **`ty` is blind across the entire cockpit.** The strict check with zero suppressions that this repo
  advertises stops at the engine boundary, because everything past it is `Any`.
- It is why `engine: Any` appears at `cockpit/routers/catalog.py:430` and
  `cockpit/routers/authoring.py:630`. Once the data is dicts, typing the producer buys nothing.
- It is why mode semantics are re-decided in four places (A11) — there is no type to hang the
  question on.
- `.get("stauts")` returns `None` silently and renders an empty cell.

**Fix.** Frozen dataclasses in `engine/status.py`: `ResourceStatus` (absorbing the conditional keys
as `identity: str | None`, `record: Record | None`) and `ProvisionResult` / `ProvisionOutcome`. Give
`ResourceStatus` the predicates the consumers currently open-code — `present`, `blocking`, `tone`.

### A2. `Node` is a TypedDict with ten free functions orbiting it

`catalog.Node` (`catalog.py:60`) has 13 fields and no behaviour. The behaviour is scattered across
three modules:

| Function | Location | Belongs on |
|---|---|---|
| `natural_keys(node["config"])` | `catalog.py:377` | `Node` |
| `key_criteria(node, resolve)` | `catalog.py:387` | `Node` |
| `find_node(nodes, type, name)` | `catalog.py:417` | a `Catalog` |
| `resource_types(nodes)` | `catalog.py:373` | a `Catalog` |
| `_varied(node, overrides)` | `materializer.py:637` | `Node` |
| `_is_own_text(value)` | `materializer.py:655` | `Node` |
| `key_of_its_own(node)` | `materializer.py:565` | `Node` |
| `browse_fields(resource_type)` | `materializer.py:225` | a `TypeSpec` |
| `remote_keys(config)` | `cockpit/routers/catalog.py:343` | a `TypeSpec` |
| `_signature(record, keys, config)` | `cockpit/routers/catalog.py:451` | a `TypeSpec` |

Two consequences. `node["config"]` — an untyped bag of leftover type keys — is passed around instead
of the node, so callers must know which sub-dict holds what. And it is why the `ref_field` identity
rule exists in four copies (B1): there is no object to put it on, so each caller re-derives it.
`key_criteria`'s docstring already claims to be *"the one definition of which record out there is
this node"*; it cannot be, as a free function taking a dict.

**Fix.** `Node` becomes a frozen dataclass with `natural_keys`, `key_criteria`, `remote_field` and
`varied_with` as methods. A `Catalog` object owns `find` and `types`. A `TypeSpec.from_entry`
classmethod (`engine/typespec.py`) owns the type-entry projection. This one change collapses A2, B1
and B2.

Note: `Node` is currently a `TypedDict` and is constructed with keyword arguments in three places
(`catalog.py:243`, `materializer.py:262`), so the migration to a dataclass is mostly mechanical, but
every `node["field"]` access site must change. Count them first.

### A3. The progress protocol has four participants and no definition

A run reports itself as JSONL. The event vocabulary — `collected`, `start`, `result`, `step`,
`provisioned`, `held`, `finished` — is written as bare string literals in **four places**:

| Participant | Role | Location |
|---|---|---|
| `PROGRESS_PLUGIN` (a string literal) | writes 5 event kinds | `runner.py:64-90` |
| `plugin.py` | writes 2 event kinds | `plugin.py:242`, `:364-377`, `:404` |
| `runner.fold_events` | reads 3 event kinds | `runner.py:375-387` |
| `jobs.JobRunner._apply` | reads 6 event kinds | `jobs.py:319-348` |

No constants, no schema, no shared constructor. Two participants also duplicate the writer itself:
`plugin._emit` (`plugin.py:364-377`) and the `_emit` inside the plugin string (`runner.py:56-61`) are
the same function, one of them invisible to every tool in the repo.

The two readers disagree by construction. `fold_events` handles only `step`/`provisioned`/`held`,
because the synchronous path takes outcomes from the pytest JSON report instead; `_apply` handles all
six, because the async path has no report. **The same run is interpreted differently depending on
which path launched it,** and nothing tests that they agree.

**Fix.** `run/events.py` holding the event names as constants plus one `emit()` and one `apply()`,
imported by all four participants. Requires the plugin to stop being a string — see D.

### A4. Two pytest launchers with different capabilities

| | `runner.run` | `JobRunner._run` |
|---|---|---|
| Location | `runner.py:242` | `jobs.py:258` |
| Mechanism | `subprocess.run` + module `_LOCK` | `Popen` + drain thread |
| Outcomes from | `--json-report` file | JSONL events |
| Supports `-k` / `-m` | **yes** (`runner.py:263-275`) | **no** (`jobs.py:270`) |
| Progress observable | no | yes |

They share `child_env` and `inject_progress_plugin` and diverge on everything else. The practical
result is a capability gap: `atf run --tag smoke` filters, and a run started from the cockpit cannot.
There is also a third, dead command builder at `runner.py:335` (`pytest_command`).

**Fix.** One launcher taking an optional progress callback, with the synchronous path being the async
path awaited. Removes the second event folder (A3) with it. This is the one step that changes
observable behaviour — cockpit-started runs gain filtering — which is a fix, but note it.

### A5. Three entities declared twice, with hand-written mappers

**`context.Slot` (`context.py:53`) and `runner.Held` (`runner.py:153`) are field-for-field
identical** — `name, kind, fields, count, resource_type, node_id, guessed`. Found automatically by
the AST scan in section 2. Plus two hand-written codecs: `Slot.as_dict()` writes the seven keys
(`context.py:84`), `runner.held_from()` reads them back (`runner.py:398`).

**`runner.TestResult` (`:171`) and `jobs.ItemState` (`:64`)** — the same seven fields under two names
(`nodeid`/`id`, `outcome`/`state`), with `Job.merged()` (`jobs.py:116-132`) as the manual mapper and
`failed_step` implemented identically on both (`runner.py:181`, `jobs.py:80`).

**`Record`** — the alias `dict[str, Any]`, declared at `adapters/__init__.py:14`. Four modules
(`records.py:35`, `context.py:25`, `steps.py:39`, and transitively more) import the whole adapter
package — dragging in `accessible`, `catalog`, `compare`, `placeholders` — to name a dict.

In each case the duplication exists because the type sits on the wrong side of a module boundary and
nobody wanted the import. Same cause as B4.

### A6. One field holding two disjoint enums

`jobs.ItemState.state` holds either a run outcome (`passed`/`failed`/`skipped`/`error`) or a
provisioning action (`created`/`exists`/`reference`/`blocked`/`error`), discriminated by `job.kind`
on the parent object. `jobs.py:57-60` writes it out:

```python
_COUNTED = {
    RUN:       (PENDING, RUNNING, PASSED, FAILED, SKIPPED, ERROR),
    PROVISION: (PENDING, RUNNING, CREATED, EXISTS, REFERENCE, BLOCKED, ERROR),
}
```

Every reader must know which kind of job it is looking at to know what `state` means. `error` is the
only member of both sets.

**Fix.** Either `Job` becomes generic over its item type, or there are two job types sharing a
progress protocol. Both are honest; the current shape is a union with the tag on the wrong object.

### A7. `Cockpit` is a 23-method God object, in the wrong package

`cockpit/deps.py` — one class mediating environment registry, bootstrap, status cache, discovery
cache, results cache, run store, flaky analysis, job launching, job history, and synchronous runs.
23 public methods over five unrelated responsibilities, plus a module-level mutable global
(`_cockpit`, `:247`) whose `set_cockpit` setter exists only so tests can reset it.

It contains **no web code**, yet lives inside the FastAPI package. `cockpit/__init__.py` is
`from .app import create_app`, so `mcp.py:41` importing `cockpit.deps` executes `app.py` and pulls
**FastAPI into the MCP server**. That is the exact outcome `introspect.py`'s module docstring exists
to prevent, and the stated reason `docs.py:63-65` duplicates the state words rather than sharing them
(B4).

**Fix.** Split along the cache boundaries — `EnvironmentRegistry`, `StatusCache`/`DiscoveryCache`,
`ResultsView`, `JobGateway` — and move them to `engine/session.py`. `cockpit/deps.py` keeps only the
thin FastAPI dependency wrapper (`get_cockpit`). Fixes the God object and the import together, and
gives B3/B4 somewhere legal to live.

### A8. The CLI has no output layer

`cli.py`, 621 lines, ~10 commands, and every command formats its own output. `cmd_status` computes
`width = max(len(nid) for nid in status)` and prints a table (`:282-290`); `cmd_seed` prints a
different table with its own `[mark:>4]` column (`:226-230`); `cmd_docs` prints another. Tallies,
pluralisation and the stderr/exit-code convention are re-derived per command:

- `cli._tally` (`:257`) maps provisioning actions to human labels — a fourth copy of that mapping
  (A11)
- `cli._reason` (`:241`) extracts the first `E ` line of a pytest failure — **identical** to
  `docs._said` (`docs.py:321`), same algorithm, same fallback (B6)
- `cli.py:439` hand-rolls pluralisation, as do eight other sites (B3)

**Fix.** A small `Console` (table, tally, `problem()` → stderr + exit 2). Removes ~80 lines and makes
each command read as orchestration.

### A9. `Discovery` is an anemic bag joined by the view layer

`discovery.Discovery` (`:153`) is six lists with eight lookup methods, every one a linear scan:
`spec`, `test`, `fixture`, `tests_for_spec`, `tests_for_resource`, `specs_for_resource`,
`questions_under`, `steps_for`.

`cockpit/view.scenario_views` (`:239`) loops over `found.specs` calling `found.tests_for_spec(spec.id)`
*inside* the loop — a full scan of `tests` per spec, so a page render is O(specs × tests). At current
suite sizes that is invisible; the point is that the join lives in the view because the model offers
no index. `cockpit/deps.py:233` (`_labels`) does the same join again, differently.

**Fix.** Build indexes once in `Discovery.__post_init__`; express the spec→tests join once.

### A10. Two seams declared and then bypassed

**The capability SPI.** `adapters/__init__.py` defines `Browsable`/`can_browse`,
`Actionable`/`can_act`, `Showing`/`can_show`, `Available`, `Closeable` — a clean structural protocol
per capability. Then `steps.py:457` does `isinstance(one, CommandAdapter)` and `ui.py:226` does
`isinstance(one, BrowserAdapter)`. A suite cannot supply its own command runner or driver and have
the generic steps find it.

This also undoes part of the lazy-import work: `adapters/__init__.py:206-215` defers built-in imports
deliberately (documented as 80ms of `httpx`, plus `click` and `pygments`), and `steps.py:40` /
`ui.py:43` import two built-in adapter modules eagerly at plugin-import time.

**Fix.** `Runnable`/`can_run` and `Drivable`/`can_drive`, and both `isinstance` checks go away along
with the two eager imports.

**Encapsulation of `Context`.** `plugin.py:263` sets `context._showing = adapter` with a
`noqa: SLF001`. `Context` is ATF's own class — give it a `now_showing(adapter)` method and the
suppression goes.

**Global mutable state**, four instances: `runner._LOCK`, `cockpit/deps._cockpit`,
`adapters._REGISTRY`, and `plugin.py:108-114` writing generated fixtures into `globals()`. The last
is forced by pytest-bdd's fixture resolution; the first three are not.

### A11. Mode and outcome semantics decided in five places

The mapping from a resource's mode/lifecycle, or a provisioning action, to what it means for a person
exists five times with five vocabularies:

| Location | Vocabulary |
|---|---|
| `materializer.provisionable` (`:319`) | can-create + refusal sentence |
| `cockpit/view.readiness` (`:167`) | blocker / will-create, with its own copy of the reference-mode sentence |
| `cockpit/view.TONES` (`:528`) | ok / idle / accent / bad / warn |
| `cli._tally` (`:257`) | created / already present / found / failed / blocked |
| `jobs._provision_state` (`:400`) | action-or-error |

`provisionable` is documented as the place that owns the question. Four others answer it too.

Related: mode and lifecycle are compared as bare strings outside their home. `catalog.py:29-31` owns
`CREATE`/`REFERENCE`/`DATA` and `LIFECYCLES`, but `materializer.py:43,50` re-declares
`EPHEMERAL = "ephemeral"` and `REFERENCE = "reference"` — and because that clashes,
`materializer.py:35` imports catalog's as `REFERENCE_MODE`. `cockpit/view.py:176,178` compares
`node["mode"]` against literal `"reference"` and `"data"` while importing four other constants from
`materializer` two lines up.

And `CREATE` means two unrelated things: `catalog.py:29` is a resource **mode**;
`cockpit/routers/authoring.py:40` is a form **action**. Same literal, same package, and
`authoring.py:29` imports from `catalog`. Rename the form actions.

---

## 5. Duplication

Each row is a rule or an algorithm existing in more than one place. All verified.

| # | What | Copies | Where |
|---|---|---|---|
| B1 | The `ref_field` identity rule (`ref_field` when there is exactly one natural key) | **4** | `catalog.py:413`, `plugin.py:83-84`, `cockpit/routers/catalog.py:346-347`, `:455-462` |
| B2 | Type-entry projection, each re-typing the defaults `"create"`/`"persistent"`/`"id"` | **5** | `catalog.py:242-257`, `materializer.py:261-276`, `cockpit/view.py:341-347`, `introspect.py:645-646` & `:971-974`, `cockpit/routers/authoring.py:609` |
| B3 | `plural(count, noun)`, byte-identical bodies | **3** + 10 inline | `cockpit/view.py:405`, `introspect.py:573`, `docs.py:176`; inline at `steps.py:645`, `:894`, `introspect.py:515`, `:623`, `compare.py:284`, `cli.py:439`, `lint.py:287-288`, `cockpit/view.py:573`, `cockpit/routers/catalog.py:534`, `cockpit/routers/authoring.py:292` |
| B4 | Scenario-state words + the fold | **2**, and they already disagree on all-skipped | `cockpit/view.py:141-144`, `:282-291` vs `docs.py:66-69`, `:130-141` |
| B5 | First line of an exception, at 3 different truncation widths | **4** | `materializer.py:665`, `placeholders.py:117`, `cockpit/routers/catalog.py:524`, `adapters/browser.py:183`; inline at `cockpit/routers/authoring.py:230` |
| B6 | First `E ` line of a pytest failure, identical algorithm | **2** | `cli.py:253`, `docs.py:326` |
| B7 | Shared-field intersection across records, identical | **2** | `steps.py:898-903`, `context.py:210-216` |
| B8 | Transitive dependency closure | **2** (one iterative, one recursive) | `materializer.closure:189`, `cockpit/view.closure_of:187` |
| B9 | "the sole adapter of this kind, or explain why not" | **3** | `ui.py:196-208`, `ui.py:226-234`, `steps.py:457-464` |
| B10 | `field_choices` → option dict | **4** | `introspect.py:807`, `:829`, `:863`, `:873` |
| B11 | `Surface(...)` assembled field-for-field from a `Cockpit` | **2** | `mcp.py:232-239`, `cockpit/routers/compose.py:137-144` |
| B12 | `HX-Request == "true"` | **3** | `cockpit/view.py:104`, `cockpit/routers/catalog.py:549`, `cockpit/routers/scenarios.py:40` |
| B13 | Step docstrings restating `GENERIC_STEPS.summary` verbatim | **22 of 22** | `steps.py` — and both copies are read: `introspect.py:946` uses `summary`, `introspect.py:707` uses `docstring` |
| B14 | The four `Given` pattern literals | **4** | `steps.py:64-76` (constants), `plugin.py:117,124,137,143` (literals), `tests/test_compose.py:34`, `discovery.py:26` (as a regex). Nothing asserts they agree |
| B15 | Near-identical claim bodies: 8 resource-field × 8 slot-field | 16 bodies | `steps.py:503-556`, `:715-760`. Also duplicated inside: the "slot holds N records, needs one" message (`:576-579`, `:771-774`) and "has no field X — it carries Y" (`:776-778`, `:840-842`) |
| B16 | Roving-highlight keyboard navigation, in JS | **2** | `cockpit/templates/base.html:103-118` (palette), `:211-233` (combobox) |
| B17 | The untyped "option" dict returned by ~10 `introspect` functions, with keys differing silently between them (`step_options` adds `rank`, `subject_options` adds `group`, `feature_options` adds neither) | ~10 | `introspect.py` — it is the shared vocabulary between the cockpit and the MCP server per the module's own docstring, and the one concept in the file with no name and no type |

`can_browse`/`can_act`/`can_show` (`adapters/__init__.py:52,84,126`) are three copies of
`callable(getattr(adapter, name, None))`. Explicit named predicates are defensible; noted only
because A10 adds two more.

---

## 6. Dead code — delete outright

| Symbol | Location |
|---|---|
| `outcome_of` | `cockpit/view.py:557` |
| `discovery_age` | `cockpit/deps.py:117` |
| `result_for` | `cockpit/deps.py:154` |
| `questions_under` | `discovery.py:194` |
| `as_query` | `http.py:231` |
| `EnvRecords.undeclared` | `cockpit/routers/catalog.py:278` |
| `pytest_command` | `runner.py:335` — a third pytest command builder (A4) |

No caller in `src/`, `tests/` or templates for any of them. `EnvRecords.declared` *is* used by a
template; `undeclared` is not.

Separately: `Materializer.create_all` (`materializer.py:495`) has no caller in `src/` or `tests/` but
is documented as public API in `docs/reference/specs-and-fixtures.md:693`. Public surface with zero
coverage — either exercise it in a test or drop it from both places. This is a judgement call for the
owner, not a mechanical delete.

---

## 7. Code hidden from every tool in the repo

Two blocks of real code in a medium nothing checks.

| Where | Size | What it is | Move to |
|---|---|---|---|
| `runner.py:45-141` | ~96 lines | An entire pytest plugin inside `'''…'''` — 8 hooks, a class, error handling. Invisible to `ruff`, `ty` and coverage. Half of A3 lives here | `run/progress_plugin.py`, shipped as package data and referenced by path with `-p` |
| `cockpit/templates/base.html:71-311` | ~240 lines | Command palette, a full accessible combobox (filter, group-collapse, roving highlight, restore-on-escape), SVG graph auto-fit, viewport-anchored tooltips | `cockpit/static/app.js` |

The repo's stated convention is "no Node, no build step, one semantic CSS file". The CSS earned a
999-line file; the JS did not. Both moves cost no build step and no dependency.

---

## 8. Inline documentation

**1,502 docstring lines + 217 comment lines — about 13% of the codebase — deleted, not relocated.**
The decisions are already made. Do not move this content into `docs/` (it would become an audit
trail) and do not rewrite commit history.

### The rule

A docstring or comment may:
- name what a scope **is** (module, class)
- state what a function **does**, its contract, and its edge cases (`None` when…, raises…, empty
  when…)

It may not:
- argue why the code is this way
- name alternatives considered, or what the code *used to* be
- cite prior art or another tool's approach
- narrate a trade-off

The test is tense and mood. Present indicative describing behaviour stays. Past tense, conditional,
comparative, or the word *because* goes.

**Keep — this is the target shape.** `catalog.py:1`:

```python
"""Catalog node model, loader and validation. Import-safe: never touches the network."""
```

One line. Names the scope, states one contract that constrains every caller. It is the shortest
module docstring in the repo and the only one needing no change.

`catalog.key_criteria`'s docstring keeps its first line and its `None`-cases paragraph — a caller
cannot derive those from the signature — and loses the middle paragraph asserting the function's
importance.

**Cut — the four failure modes as they currently appear:**

| Mode | Example |
|---|---|
| Argues the decision | `materializer.py:53-63` — 11 lines on why per-node lifecycle exists, citing "§4.7 of the target", a document not in this repo |
| Names the rejected option | `plugin.py:128-131` — "The alternative is a second catalog node per variation, which is Object Mother" |
| Narrates history | `steps.py:1-10` — "ATF used to define exactly one step … and every project re-wrote the same family" |
| Cites prior art | `docs.py:9-13` — Pickles, Augurk, Serenity |

### The pass is mostly mechanical

**Line 1 of nearly every module docstring is already exactly right**, with an essay underneath. So
the pass is largely *truncate to line 1*. Two exceptions need rewording rather than truncation:

- `discovery.py:1` — "Turns a project into the structured model **the cockpit** renders" names one of
  four consumers (`docs`, `lint` and `mcp` use it too). Reword to *"A suite's features, steps and
  fixtures as a structured model."*
- `cli.py` — its 60 rationale lines are all inside `cmd_*` docstrings. That is user-facing help text
  in the wrong place, duplicating `docs/reference/cli.md`. Delete, do not truncate.

Also delete outright:
- `docs.py:63-65`, the comment explaining why the state words are duplicated. Fix B4 and it has no
  subject.
- `steps.py:77-81`, the comment explaining why `plugin.py` re-types the patterns. Fix B14 and it has
  no subject.
- the 22 step docstrings in `steps.py` that restate `GENERIC_STEPS.summary` (B13). Have
  `introspect.step_options` read `generic(step.pattern).summary` when there is one — exactly as
  `introspect._step_entry:946` already does — then delete them.

### Per-module budget

`mod` = module docstring lines today → after. `why` = rationale lines inside function/class
docstrings. `#` = rationale-bearing comment lines. Worst ratios are the small leaf modules, not the
big files.

| Module | LOC | mod | why | # |
|---|---|---|---|---|
| `phrasebook.py` | 406 | 64→1 | 51 | 8 |
| `openapi.py` | 802 | 61→1 | 35 | 11 |
| `docs.py` | 376 | 45→1 | 33 | 0 |
| `adapters/command.py` | 142 | 40→1 | 0 | 0 |
| `adapters/html.py` | 137 | 33→1 | 0 | 0 |
| `ui.py` | 238 | 32→1 | 0 | 0 |
| `mcp.py` | 309 | 30→1 | 17 | 0 |
| `steps.py` | 910 | 28→1 | 10 | 31 |
| `accessible.py` | 393 | 28→1 | 13 | 5 |
| `records.py` | 112 | 26→1 | 6 | 0 |
| `introspect.py` | 1154 | 26→1 | 91 | 12 |
| `adapters/browser.py` | 184 | 26→1 | 6 | 0 |
| `lint.py` | 292 | 23→1 | 6 | 0 |
| `providers.py` | 262 | 21→1 | 23 | 0 |
| `report.py` | 82 | 21→1 | 0 | 0 |
| `collect.py` | 105 | 20→1 | 5 | 0 |
| `cockpit/routers/compose.py` | 699 | 18→1 | 16 | 6 |
| `context.py` | 237 | 14→1 | 0 | 0 |
| `cockpit/routers/authoring.py` | 635 | 12→1 | 16 | 0 |
| `runner.py` | 492 | 10→1 | 32 | 5 |
| `compare.py` | 287 | 9→1 | 26 | **22** |
| `authoring.py` | 286 | 9→1 | 11 | 0 |
| `jobs.py` | 405 | 9→1 | 0 | 0 |
| `placeholders.py` | 117 | 9→1 | 0 | 0 |
| `cockpit/routers/catalog.py` | 549 | 8→1 | 6 | 0 |
| `store.py` | 220 | 6→1 | 0 | 0 |
| `materializer.py` | 668 | 5→1 | **88** | 11 |
| `plugin.py` | 411 | 5→1 | **53** | 3 |
| `cockpit/view.py` | 630 | 5→1 | 19 | 0 |
| `cockpit/glossary.py` | 269 | 5→1 | 7 | 0 |
| `cockpit/deps.py` | 259 | 5→1 | 5 | 0 |
| `cockpit/routers/scenarios.py` | 104 | 5→1 | 0 | 0 |
| `discovery.py` | 978 | 4→1 | **61** | 8 |
| `bootstrap.py` | 96 | 4→1 | 0 | 0 |
| `cockpit/routers/overview.py` | 118 | 4→1 | 5 | 0 |
| `cockpit/routers/activity.py` | 99 | 4→1 | 0 | 0 |
| `http.py` | 232 | 3→1 | 0 | 0 |
| `cli.py` | 621 | 1→1 | **60** | 5 |
| `adapters/__init__.py` | 258 | 1→1 | **58** | 10 |
| `catalog.py` | 421 | 1→**keep** | 19 | 3 |
| `config.py` | 318 | 1→1 | 18 | 0 |
| `scaffold.py` | 371 | 1→1 | 12 | 0 |
| `cockpit/app.py` | 61 | 1→1 | 7 | 0 |
| `adapters/rest.py`, `adapters/reference.py`, `cockpit/routers/search.py`, `__init__.py` | — | 1→1 | 0 | 0 |

`adapters/__init__.py` needs care: its 58 rationale lines are inside **Protocol** docstrings
(`Actionable` alone is 23 lines with a YAML example). Keep each protocol's method contract and the
`wait`/return-value semantics — those are the SPI, and an adapter author needs them. Cut the
argument for why the seam exists.

`scaffold.py` is the one module allowed a literal URL. Keep that comment: it is a constraint on
editors, not a rationale.

### Enforcement, so it cannot come back

Mechanical parts to a linter, judgement to review — matching the four conventions already in the
README.

In `pyproject.toml`:

```toml
[tool.ruff.lint]
extend-select = ["D"]
ignore = ["D203", "D213"]      # keep the existing summary-on-first-line style

[tool.ruff.lint.pydocstyle]
convention = "pep257"
```

`D200`/`D205`/`D400`/`D415` force summary-first with a blank line before any body, which alone makes
an essay visually obvious in review — it can no longer masquerade as a summary.

Then `scripts/prose.py`, run in CI beside `ruff check`, for the two rules ruff cannot express:

1. A module docstring is at most **2 lines**.
2. No docstring or comment contains: `because`, `rather than`, `instead of`, `the alternative`,
   `used to`, `would have`, `deliberately`, `on purpose`, `which is why`, `the reason`.

Rule 2 is blunt and will occasionally catch a legitimate phrasing. That is the right failure
direction: the author rewords one line, and the alternative is a rule nobody applies. Current
violations: 130 docstrings, 48 comment blocks.

Add as README convention #5:

> **A comment says what a scope is or what a function does.** Not why it is that way, not what it
> replaced, not what else was considered. A decision that needs recording is a commit message.
> Enforced mechanically by `scripts/prose.py` for length and for the phrases that always mean
> rationale; the rest is review's job.

---

## 9. Filesystem structure

### The problem

34 modules flat in `src/atf/`, spanning six unrelated concerns. Nothing in the filenames says
`placeholders.py` is pure model and `jobs.py` is background execution, or that importing `records.py`
drags in the whole adapter package. Four modules exceed 800 lines. Two hold code inside strings.

### The layering already exists in the imports

Grouping the 34 top-level modules by role and checking every relative import against the grouping
yields **exactly four back-edges**, and each is a single misplaced symbol already named above. The
structure below is not invented — it is what the code already does, minus four symbols.

```
src/atf/
├── cli.py                  the only module importing across every layer
│
├── model/                  what a suite declares — no I/O, no pytest, no web
│   catalog.py  manifest.py (was config.py)  placeholders.py  providers.py
│   compare.py  records.py (now owns Record)  text.py (new: one plural())
│
├── engine/                 making a declaration true against an environment
│   materializer.py  bootstrap.py
│   session.py (was cockpit/deps.py, split per A7)
│   typespec.py (new, A2/B2)  status.py (new, A1)
│
├── adapters/               how to talk to one kind of system
│   __init__.py  control.py (was accessible.py)  http.py (moved down)
│   rest.py  reference.py  browser.py  html.py  command.py
│
├── spec/                   the pytest side
│   plugin.py  context.py  collect.py  phrasebook.py
│   patterns.py (new: the pattern constants + grammar, dependency-free — B14)
│   └── steps/  __init__.py (the tables)  resource.py  interface.py (was ui.py)
│
├── run/                    running, and what a run leaves behind
│   runner.py  progress_plugin.py (new, section 7)  events.py (new, A3)
│   jobs.py  store.py  report.py  verdict.py (new: the state words + fold — B4)
│
├── suite/                  reading and writing a suite's own source
│   discovery.py  lint.py  docs.py  authoring.py  scaffold.py  openapi.py
│
├── agent/                  the machine-facing surface
│   introspect.py  mcp.py
│
└── cockpit/                the human-facing surface
    app.py  deps.py (thin FastAPI wrapper only)  view.py  glossary.py
    routers/  static/ (+ app.js)  templates/
```

Direction is strictly downward: `model` ← `adapters` ← `engine` ← `spec` ← `run` ← `suite` ←
`agent`/`cockpit` ← `cli`.

### The four back-edges

| Back-edge | What is actually imported | Fix |
|---|---|---|
| `records` → `adapters` | `Record`, a `dict[str, Any]` alias | A5 — move to `model/records.py` |
| `plugin` → `run` | `PROGRESS_OUT`, one env-var name string | A3 — `run/events.py` |
| `phrasebook` → `suite` | `CAPTURE_RE`, `fill`, `pattern_regex` — the pattern grammar, not discovery's collection machinery | `spec/patterns.py`; also absorbs `discovery.PROVISION_RE` |
| `agent` → `cockpit` | `Cockpit` | A7 — `engine/session.py` |

After those four, the layering is acyclic with no exceptions. Verify with the script in section 2
adapted to the new package names.

### Splitting the four oversized modules

Each is already sectioned by the author with `# ---- … ----` banners, so the cut lines are pre-drawn.
Read them before choosing boundaries.

**`introspect.py`, 1154 lines, 11 sections → 5 modules** under `agent/`. Its docstring says *"The
surface is three verbs"*; those three verbs are 15% of the file and the machinery behind them shares
the namespace.

| New module | From sections | ~lines |
|---|---|---|
| `surface.py` | "the thing every question is asked of", "which steps a scenario can use" | 120 |
| `fields.py` | "the fields of a resource" | 60 |
| `rows.py` | "one step under construction", "a claim, both ways round", "what the rows above have left behind", "turning rows into the words" | 350 |
| `options.py` | "the choices, each carrying what is needed to make it" | 280 |
| `__init__.py` | `describe`, `compose`, `try_scenario` | 180 |

**`discovery.py`, 978 → 3** under `suite/`, on the existing seam between static parse and pytest
collection: the pattern grammar (moves to `spec/patterns.py`), `parse.py` (the static half `lint` and
`docs` use, needing no importable suite), `collect.py` (the half that shells out to pytest). Worth
more than its size: `docs.py` currently spends a paragraph explaining it deliberately uses only the
static half — with two modules, the import says it.

**`steps.py`, 910 → 3** under `spec/steps/`: the tables, the resource/slot claims, the interface
steps. The split is what makes B15 possible.

**`openapi.py`, 802, 6 sections → 3** under `suite/openapi/`: `score.py` (how much each signal is
worth), `read.py` (reading the shapes out of the document), `write.py` (writing it down + the
proposed change).

---

## 10. Work plan

Each step makes the next cheaper. Land each as its own commit; run `ruff check`, `ty check` and the
full suite at the end of each numbered step, not per edit.

1. **A1 — `engine/status.py`: `ResourceStatus`, `ProvisionResult`, `ProvisionOutcome`.**
   Turns 41 literal reach-ins into attribute access and gives `ty` something to check across the
   cockpit for the first time. Precondition for A11 and both `engine: Any` holes.
   *Done when:* no `.get("status")` / `["identity"]` remains outside `engine/`, and both `engine: Any`
   annotations are concrete.

2. **A2 — `Node` and `Catalog` as real objects; `engine/typespec.py`.**
   Collapses B1 (4 copies) and B2 (5 copies) into methods. Count `node["…"]` access sites first.
   *Done when:* `ref_field` appears once in the codebase, and the defaults `"create"`/`"persistent"`/
   `"id"` appear once.

3. **A3 + A4 + section 7's first row — one launcher, one event module, the plugin as a file.**
   Removes the second event folder, the `-k`/`-m` capability gap, and 96 lines of unchecked code.
   *Done when:* the event names exist as constants in one module, `runner.py` holds no triple-quoted
   Python, and a cockpit-started run accepts a tag filter.

4. **A5 + the four back-edge symbols.** `Slot`/`Held` unified, `TestResult`/`ItemState` unified,
   `Record` to `model/`, `PROGRESS_OUT` to `run/events.py`, the pattern grammar to `spec/patterns.py`.
   Small, independent, and the precondition for step 6.

5. **A7 — split `Cockpit`, move to `engine/session.py`.** Then B3 (`text.py`) and B4 (`verdict.py`)
   have somewhere legal to live; do them here. `mcp.py` stops importing FastAPI.
   *Done when:* `grep -rn "fastapi" src/atf` returns nothing outside `cockpit/`.

6. **Move to packages** (section 9). One commit, imports only, no logic changes. Verify acyclicity
   with the layering script.

7. **Delete section 6.** Ten minutes, no risk. Ask the owner about `create_all`.

8. **The prose pass (section 8) and its rules.** Zero behaviour change, so it can land at any point —
   earlier makes review of everything above easier, since several defects are currently narrated by
   the comments that would go. Land the ruff config, `scripts/prose.py` and README convention #5 in
   the same commit as the last module, so the count cannot climb back.

9. **The remainder.** A10 protocols and the two eager adapter imports; A8 `Console`; A9 indexes;
   B15 step-table collapse (with B13); section 7's JS extraction then B16; the oversized-module
   splits; then B5–B12 and B17 as you pass through.
