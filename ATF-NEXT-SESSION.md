# ATF — write tests in the UI, and rework what stops that being possible

## What ATF is

A testing framework. The cockpit (`src/atf/cockpit/`) is its entrypoint: you run tests from it and
you create things in it. Resources and scenarios can also be written directly as files — it's a test
framework, both are normal. Do not reframe ATF as anything broader; a "product vision" framing was
tried in the previous session and rejected as filler.

**The goal is to write tests.** A test is three things:

1. declare / use the resources it needs
2. write the process (the actions)
3. write the assertion

**The more of those can be done in the UI, the more we implement.** Where a test must call a
third-party service to *perform an action*, that needs real code — accepted. Everything else should
not. Asserting on a field of a resource ATF already has an adapter for must be possible in the UI.

## Why this needs a framework rework, not just UI work

The previous session repeatedly tried to build the UI first and kept hitting walls that are in the
framework. Three of them, in the order they bite:

### 1. `context` is a `SimpleNamespace`, so nothing downstream is introspectable

`src/atf/plugin.py`:

```python
@pytest.fixture
def context() -> SimpleNamespace:
    """The per-scenario scratchpad: steps write what they create and read what they need."""
    return SimpleNamespace()
```

Steps communicate by convention — a `When` sets `context.result` to anything at all, and the `Then`
that follows knows its shape only because the same person wrote both:

```python
@when("I read its plan")
def _(context, api):
    context.result = api.plan_of(context.account)

@then(parsers.parse('the plan is "{expected}"'))
def _(context, expected):
    assert context.result == expected
```

This is *the* blocker on building assertions in the UI. It is not that assertions are hard; it is
that after any `When` runs, the framework has no idea what is available to assert on. The three parts
of a test are not independent — the process determines what is assertable — and no UI can fix a
scratchpad that forgets what it is holding.

**What to design:** a context that carries what it holds. Provisioned records already arrive with a
known resource type and a known id (`_provision` does `setattr(context, resource_type, record)`), so
those are describable today. The open question is what a project's own `When` declares about its
output, and how much can be inferred without forcing every existing step to be rewritten.
Backward compatibility matters: `context.foo = x` must keep working.

### 2. The "no opinions about record shape" principle is drawn in the wrong place

`docs/explanation/the-model.md` says ATF deliberately never defines record shape — the adapter's
record is passed to steps untouched, and *"the moment the framework has opinions about record shape,
it stops being generic."*

Taken literally this forbids UI-built assertions, because nothing in ATF admits a resource *has*
fields. But it is overdrawn: `natural_key: email` already names a field and nobody calls that a
violation. The real line is between **ATF asserting a shape** and **the author naming a field ATF
then reads**. State that as the principle, in the docs, before building anything that reads a field —
otherwise every assertion feature looks like it is breaking the rules.

### 3. One generic step is a suspiciously small number

ATF generates a fixture per resource type but exactly **one** step:
`Given the {resource_type} "{name}"`. Everything else is re-hand-written per project — including
`the plan is "standard"`, which is nothing but a record-field comparison the adapter could do.

That is a missing framework layer, not a UI gap. The whole family of read-and-compare steps belongs
in ATF, and every project reimplementing it is the symptom. Sketch (validate, do not assume):
`the {type} exists`, `the {type} is gone`, `the {type} field "{f}" is "{v}"`, `I re-read the {type}`.
A draft lived at `src/atf/steps.py`, was never wired into `plugin.py`, and was deleted before review.
Re-derive it from the design if the design survives.

Note when scoping: values arrive from Gherkin as strings while records hold bools/ints/dates.
`adapters/rest.py::_matches` and `_same_instant` already solve exactly this comparison problem —
reuse that logic rather than inventing a second one.

## Two things that look like features and are probably dead ends

- **Generating step *stubs*.** Mostly moves typing from an editor into a form. The value is in steps
  that need no code at all, so the generic layer matters more than the generator. Keep stub
  generation as a last resort, not the centrepiece.
- **Authoring tests against `mode: reference` resources.** They can be asserted on but never created
  by ATF, so a UI-authored test against one can only verify what someone else provisioned. Worth
  knowing before betting the authoring flow on adoption-from-environment.

## The other half: the UI carries about twice the content it needs

Reviewed and approved in the previous session — apply, subject to whatever the rework above changes.

### Resources

```
┌──────────────┬──────────────────────────────────────────────────────────┐
│ RESOURCES  8 │ owner                              rest · 2 of 2 present │
│ by type ▾    │ Given the owner "primary"     [+ New owner] [Provision 2]│
│              ├──────────────────────────────────────────────────────────┤
│ guest    0/1 │ INSTANCE      STATUS     WHAT IT IS                      │
│ label    1/1 │ primary       ● present  The owner every list hangs off ⋯│
│ owner    2/2 │ secondary     ● present  Proves lists never leak        ⋯│
│  primary     │ ─────────────────────────────────────────────────────────│
│  secondary   │ tester@todo…  ○ in dev   not declared   [Add to catalog] │
│ task     2/2 │                                                          │
│ todo_list2/2 │ natural key email · identity id                          │
└──────────────┴──────────────────────────────────────────────────────────┘
```

Selecting an instance replaces the right pane:

```
┌──────────────────────────────────────────────────────────────┐
│ milk                    task · ● absent    [ Provision +2 ]  │
│ An open task on the groceries list, due tomorrow morning.    │
│ { "title": "Buy milk",                                       │
│   "list_id": "${lists.groceries.id}",   ← resolves at run    │
│   "due_at":  "${now+1d 09:00}" }                             │
│ needs groceries, primary · used by "A task lands on its list"│
│ catalog/tasks.yaml                        [Copy] [Edit] [✕]  │
└──────────────────────────────────────────────────────────────┘
```

Delete: the "Declared in the catalog" list (it duplicates the left nav *and* the instances table);
the "How a scenario asks for one" card (one line of Gherkin, belongs in the header); the "Provision"
card and its paragraph; the "Copying, editing and deleting" prose (they are header controls); the
`mode` and `collection` kv rows. Show `lifecycle`/`mode` **only when non-default** — `ephemeral` and
`reference` change behaviour and earn a line in words; `persistent`+`create` says nothing. Show the
lineage graph only when the closure exceeds 3 nodes; below that `view.lineage_sentence()` is better.

Merge the instances table and the environment-records table into **one** table — declared rows first,
then a divider, then records the environment has that the catalog does not declare, each with
`[Add to catalog]`. Today the same resources appear in up to three lists on one page.

### Scenarios

```
┌───────────────────┬──────────────────────────────────────────────────┐
│ [failing 1] [all] │ A task lands on its list      Lists · failing ⟳  │
│ ⌕ filter…         │ failed 3 mins ago · 8ms                 [ Run ]  │
│                   │  Given  the todo_list "groceries"      ● absent  │
│ LISTS             │  And    the task "milk"                ● absent  │
│ ● A task lands  ⚑ │  When   I read the tasks on the list             │
│ ○ A list belongs  │  Then   the task "Buy milk" is open              │
│ ○ Completing a…   │         AssertionError: deliberate failure       │
│ GUESTS AND LABELS │  Running provisions 3 resources                  │
│ ✓ A guest is…     │  specs/features/lists.feature:14   [Add another] │
└───────────────────┴──────────────────────────────────────────────────┘
```

Delete the "What pytest collects" card. Examples appear only when the scenario has one; the
covering-tests table only when there is more than one test.

### UI rules that were learned the hard way

- **Never a badge for an action.** Create paths were invisible because they were `class="chip"` —
  pill-shaped, so they read as decorative tags. Actions are `button` / `a.btn` / `a.btn.primary`.
- **Colour carries entity kind, not badge shapes.** `ui.ref(kind, href, label, status=None)` renders
  coloured text (mono for identifiers) with a status dot. `.tag` is only for real labels (a Gherkin
  tag, a system name). The filled lozenge `.pill.loud` is at most once per rendered page.
- **No blind dropdowns.** A `<select>` of names is unusable at real scale and tells you nothing about
  what you are picking. Use the combobox in `macros.html` (`ui.combo`) — type-to-filter, ↑↓/Enter/Esc,
  and every option carries secondary info: a resource's status and `represents`, a step's wording and
  defining file. Extend this pattern; do not regress to `<select>`.
- **Explain at the point of decision, not in cards.** `ui.term()` count went 45 → ~14 by explaining a
  term once per page. Do not add more. Framework explanation in a card is clutter; a hover definition
  on the word, or a sentence in the field's hint, is not.
- **Errors arrive beside the page** (a toast), never as a swap that destroys what you were reading.
- Do not paraphrase docs inside the app. An in-app "Concepts" page was built and rejected; terms link
  to the real documentation via the `docs(path)` global.

## Repo and gates

`/Users/maximedepachtere/project/atf` — Python 3.11+, `uv`, **no Node, no build step**.
FastAPI + htmx (vendored, pinned SHA, no CDN), Jinja2, one semantic CSS file
(`src/atf/cockpit/static/app.css`). Tailwind was considered and rejected: it needs a build step in a
pure-uv repo, and the app computes presentation classes in Python (`class="pill {{ tone(state) }}"`),
which would mean safelisting or moving design into `.py`.

All green — keep them green:

```
uv run ruff check                 # line-length 120, rules E,F,I,UP,B,SIM
uv run ty check                   # strict: warnings are errors
uv run pytest -q                  # 374 tests
uv run mkdocs build --strict      # fails on broken links AND anchors
cd examples/todo && uv run --project ../.. python -m pytest -q   # 8 passed
cd selftest     && uv run --project ..    python -m pytest -q    # 8 passed
```

An acceptance test forbids any literal `http(s)://` under `src/atf/` (except `scaffold.py`) so the
framework names no domain — documentation links go through the `docs(path)` Jinja global, which reads
`ATF_DOCS` first, else `[project.urls] Documentation`. The published docs site currently 404s
(GitHub Pages was never enabled), so for local work:
`ATF_DOCS=http://127.0.0.1:8000/atf` alongside `mkdocs serve`.

**Nothing is committed.** ~103 changed files in the working tree from recent work, 34 of them new.
Worth splitting into reviewable commits by area before adding more.

## Architecture

`catalog.py` loads YAML types + instances into a dependency graph → `materializer.py` provisions a
resource's closure dependency-first and idempotently, delegating to `adapters/` (`find` / `create` /
`delete`, plus optional `browse` = "list what this type already has here", and `provisionable()`
which refuses `reference` and `ephemeral` nodes) → `plugin.py` is the pytest-bdd plugin (one fixture
per resource type, the one generic `Given`, ephemeral teardown) → `discovery.py` parses `.feature`
files and introspects pytest for tests, fixtures and **available step definitions** (pattern, params,
file, docstring) → `runner.py` / `jobs.py` run tests as background jobs with per-Gherkin-step
outcomes and a provisioning trace → `store.py` persists runs to `<root>/.atf/runs/*.json` →
the cockpit renders it.

`authoring.py` writes catalog YAML: `derive(record, …)` turns a real environment record into the node
that would have produced it — dropping server-owned fields, and turning a value that matches another
node's identity into `${that.node.id}` plus a `depends_on`, which is what makes a derived node
re-creatable in an empty environment rather than welded to this one. `insert`/`replace`/`remove` edit
one top-level entry and leave every other byte alone. Every write validates the whole catalog and
restores the original bytes if it would stop loading.

Read before designing: `docs/explanation/the-model.md`, `docs/explanation/life-of-a-run.md`,
`docs/reference/specs-and-fixtures.md`, `docs/reference/adapter-spi.md`.

## What already works (do not rebuild)

- Run and provision as background jobs, unified `Job` model, live per-item progress in a dock that
  survives navigation.
- Run history on disk so the verdict survives a restart; flaky detection; `atf import-run` for CI.
- Step-level failure capture: the failing Gherkin step is marked in the rendered Gherkin with its
  assertion beneath, and steps before it show as passed.
- Browse an environment through the adapter and adopt a record into the catalog.
- Create / copy / edit / delete a resource in the UI: preview diff → validate → apply → rollback.
- A guided scenario composer offering the suite's real step definitions, writing the `.feature`,
  re-parsing it and rolling back if it would not parse.
- `atf init` scaffolds a suite where `atf run` passes immediately, with no server to start.

## Constraints that bit last time

- `mutable_envs` gates provisioning and running. It must **not** gate authoring: editing the catalog
  or a `.feature` is a source change, identical whichever environment is selected.
- Catalog edits invalidate every environment's caches (`Cockpit.invalidate_all()`), not just the
  current one.
- `u(path, **params)` is the only way to build a URL — it carries the environment and percent-encodes.
  Do not hand-write `?env=` and do not add `|urlencode`.
- Discovery shells out to pytest, so it is slow and cached per environment; it must never run twice
  for one page render, and must never break a page when it fails.
- An unknown environment is a 404 naming the known ones, never a silent fallback to the default.

## How to work

1. **Design the whole thing first, in one piece, and get it validated before writing code.** The
   previous session lost significant time implementing request by request and having each increment
   corrected.
2. **Think past the literal request.** If a capability is obviously adjacent and nearly free given
   what exists, propose it — do not wait to be asked feature by feature. Equally, say plainly when
   something looks like a dead end and why.
3. **UI/UX is the product, not a layer on top of it.** It is the main entrypoint. Design it from what
   a person is trying to do, not as a rendering of the data model.
4. Do not remove or rewrite anything that was not asked for without saying so first.
