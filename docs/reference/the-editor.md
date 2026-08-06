# The editor

`atf edit` starts a local web server that reads and drives the suite you already have.
`atf edit --mcp` serves the same operations to an agent instead of a browser.

This whole page is one of the three faces. Every section below *is* the **In the editor** face of
something defined elsewhere, so each ends with the other two.

## No privileged path {#no-privileged-path}

The editor is a client of the same core as the command and the agent interface, and holds no logic
of its own. Every button is one of the operations in [the command](the-command.md) — the same call,
the same arguments, the same answer. The cost: a feature that would be convenient in a browser and
awkward on a command line has to be made to work on the command line first.

The composer is the single view with no command behind it: it writes a file of Gherkin you could
have typed yourself, and performs nothing.

## No knowledge of your domain {#no-domain-knowledge}

The editor knows about no specific type, system, claim or marker. It renders whatever the
[registries](extending-atf.md) contain: the `sqlite` adapter a suite registers appears in the
catalogue as a type, counted in the overview, its create bodies shown, its `act` verbs offered by
the composer; register `#iban` and it appears in the marker picker and the value hints; register a
claim and the composer offers its sentence wherever its subject exists. No editor code changes, and
there is no list of known systems anywhere in it.

A concept that needs a special case to be rendered is not finished: fix the model, not the editor.
The cost is that the editor cannot get better ahead of the model.

## Overview {#overview}

One question: can I ship. The one-sentence verdict for the selected environment, then the four
things that could contradict it.

```text
staging is ready.

  resources   41 present · 0 absent · 0 unreachable
  tests      118 passing · 0 failing · 4 skipped
  last run    6 minutes ago, imported from CI
  suite       well formed
```

When it is not ready, the sentence says which of the four is at fault, and each line links to the
view that shows the detail:

```text
staging is not ready — 2 resources are absent and cannot be made here.

  resources   39 present · 2 absent · 0 unreachable
```

The verdict is a fold, not a fifth state, computed from the two vocabularies —
`present` · `absent` · `unreachable` and `passed` · `failed` · `skipped` — and nothing else. It says
ready with absent resources in the count while every one of them can be made, not ready when one
cannot, and names the reason it was given.

- **In CI** — [`atf status <env>`](the-command.md#status) and [`atf check`](the-command.md#check)
  produce the same four numbers. They do not gate alike: `check` exits `1` on an ill-formed suite,
  while `status` never exits `1` at all.
- **To an agent** — the `status` and `check` tools, returning the counts as structured fields rather
  than a sentence.

## Catalogue {#catalogue}

Every resource the suite declares, navigated by type first.

```text
Owner       3 declared   3 present
TodoList    5 declared   4 present · 1 absent
Task       22 declared  22 present
Guest       1 declared   0 present   (function scope — made per test)
```

Opening a type lists its instances with what the environment holds for each. Opening one instance
shows five things:

- **The declaration** — the class, its fields, its system decorator and that decorator's own
  configuration, as written.
- **What it is recognised by** — the recognition field and the value that identifies this one.
- **What the environment holds** — `present`, `absent` or `unreachable`, and for a present resource
  the record as found.
- **What would be sent to create it** — the exact body the adapter's `create` would receive, with
  lineage already resolved to the records it depends on.
- **What would be changed** — for a present resource that has drifted from its declaration, the
  fields ATF would send to `update`, each with the value found and the value declared.

```text
groceries · TodoList · absent in staging

  would create with:
    { "slug": "groceries",
      "owner": { "id": 12, "email": "primary@example.com" } }     → primary, present

  [ Make ]      disabled — staging is not mutable
```

```text
groceries · TodoList · present in staging, and differs

  would change:
    slug        "weekly"  →  "groceries"

  [ Make ]      disabled — staging is not mutable
```

Neither is a preview the editor assembles. The create body is what `create` would receive, asked
for and not executed; the change set is the diff [ATF computed itself](arrange.md#reconciliation)
and would hand to `update`. A resource whose body cannot be built without contacting the system says
so. The change set only ever names fields the declaration names.

- **In CI** — `atf status <env>` for the whole catalogue, `atf status <env> groceries` for one
  resource, `atf make <env> --dry-run groceries` for what would be created and changed.
- **To an agent** — the `status` and `make` tools. The dry-run answer is the same field an agent
  reads before deciding whether to make anything.

## The graph {#graph}

The spine of the editor rather than a page in it. Every resource, test and phrase is reachable by
moving along an edge from wherever you already are; there is no node that only a search box finds.
The edges are the ones the model already has. A resource reaches another through
[lineage](arrange.md#lineage), a field typed as another resource. A test reaches the resources it
asks for, as a parameter or as a `Given`. A scenario reaches a phrase by saying its sentence, and a
phrase reaches another by nesting it. A resource reaches an action its adapter can perform.

Small lineage is stated in words:

```text
groceries needs primary.
```

```text
laundry needs groceries, which needs primary.
```

Past that, or where a node has many dependants, the view draws it and the sentence becomes a
caption. The threshold is a rendering decision, not a semantic one.

Two questions have their own entry points:

- **What breaks if this does** — everything downstream of a node, resources and tests together.
- **What nothing asks for** — resources no test reaches.

- **In CI** — `atf impact groceries` for the downstream of one node, `atf impact` with no argument for
  the whole graph, `atf unused` for the unreachable resources.
- **To an agent** — the `impact` and `unused` tools.

## Tests {#tests}

Every behaviour the suite describes, in one list. A pytest function and a Gherkin scenario appear
the same way, because they compile to the same thing; the list says which form each is in and
otherwise treats them alike. It filters by verdict — `passing`, `failing`, `skipped`, `never run` —
and by tag.

Opening one test shows its steps as written, the resources it asks for as links into the catalogue,
its history — the last outcome, the message if it failed, and the verdicts before that — and a
button that runs it.

```text
Scenario: showing an owner's lists                       failing · specs/todo.feature:14

  Given the todo_list "groceries"                        → groceries, primary
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"

  last run   failed, 3 minutes ago
             the result field "output" is "no lists", which does not contain "groceries"

  [ Run this test ]
```

The failure message is the one the run produced, quoted whole and not re-rendered.

- **In CI** — `atf run --select "showing an owner's lists"` runs exactly what the button runs.
  `atf run --failed` is the `failing` filter. `atf docs` is this list as markdown, carrying the same
  verdicts.
- **To an agent** — the `run` and `docs` tools.

## The composer {#composer}

Writing a scenario, or a phrase, from what the suite already knows. It offers three things, all
derived from the registries and the graph:

- **A `Given`** for any resource the suite declares, by name or by type.
- **A step only where it can be used.** `When I complete the task "laundry"` is offered because
  `Task` declares a `complete` action and its adapter implements `act`. `When I list every todo_list`
  is offered because that adapter implements `browse`. An adapter that implements neither contributes
  no `When`, and the composer says so.
- **A claim only once something above it has produced what the claim reads.**
  `Then the result field "exit_code" is "0"` appears after a `When I run …`;
  `Then the todo_list "groceries" field "slug" is "groceries"` after that list has been arranged.
  Ordering the steps differently re-answers the offer.

Phrases are offered alongside built-in sentences, undistinguished: one that arranges as a `Given`,
one that claims as a `Then`, read from the verbs the phrase's own body uses. Where a claim takes a
value, the marker picker offers every marker in the registry — `#uuid`, `#datetime`, `#date`,
`#absent`, `#present`, `#int`, `#str`, `#bool`, and whatever the suite has registered.

What comes out is a file under the specs directory, in the syntax documented in
[Act](act.md) and [Assert](assert.md). There is no editor-only syntax, no generated header, and no
marker in the file saying it was composed.

The cost of offering only what fits: the composer cannot help you write a step that does not exist
yet. A step you write in Python or a phrase you teach in Gherkin is authored in your editor, and the
composer picks it up on the next read.

- **In CI** — nothing. The composer writes text.
- **To an agent** — the same offers, as the structured answer to "what can be said here", so an
  agent asks for the legal steps at a position rather than guessing and parsing the error.

## Activity {#activity}

A run watched while it happens, item by item.

```text
running · staging · 12 tests selected

  ✓ made       primary            Owner
  ✓ made       groceries          TodoList
  ✓ passed     showing an owner's lists                       0.4s
  ✗ failed     adding a list for an unknown owner             0.2s
                 the result field "exit_code" is "0", expected "1"
  · running    completing a task
```

Both halves of a run appear in the same stream: the resources made or found, then the tests. A test
that failed for want of its lineage reads directly under the line where the building failed.

The stream is the run record being written, not a log the editor formats. When it ends, the record
is in [history](the-record.md#history) and the tests view shows the new verdicts. Runs imported with
`atf import-run <env> <file>` appear here too, and the overview's "last run" line names where each
came from.

- **In CI** — `atf run` writes the same record and prints the same items.
- **To an agent** — the `run` tool, returning outcomes as they resolve.

## Environments {#environments}

The environment is an argument to every question the core answers. The editor carries it in the URL,
as `?env=staging` on every link, and every view is that view *for that environment*.

Changing the environment re-answers the current page. It does not navigate: looking at `groceries`
in `local` and switching to `staging` leaves you on `groceries` in `staging`. So a pasted link
carries the environment, and a reload is stable — nothing about the selection lives in memory.

- **In CI** — the environment is the positional argument — `atf status staging`, `atf make staging`.
- **To an agent** — a required parameter on every tool that touches an environment. There is no
  ambient current environment for an agent to get wrong.

## A read-only environment {#read-only}

An environment is read-only unless its manifest entry says `mutable: true`. `mutable` is false
unless stated, so an environment nobody thought about cannot be written to.

In a read-only environment, every control that would change something is **disabled, with the reason
attached, and never hidden**.

```text
  [ Make ]          disabled — staging is not mutable
  [ Make ]          disabled — plans are declared when_absent="require"
  [ Delete ]        disabled — staging is not mutable
  [ Run this test ] enabled
```

The reasons come from the core, not from the editor, which is why a reason can be specific to the
resource: `when_absent="require"` says the environment owns that resource, `when_absent="observe"`
says it is something to look at.

Running tests is not a mutation of the environment in this sense, and stays enabled. Whether the
tests can pass against a read-only environment is a property of the tests. The trade-off is screen
furniture: every row of a read-only catalogue carries a disabled button and a sentence.

- **In CI** — `atf make` on an immutable environment refuses before touching anything and exits `2`,
  with `environment_immutable` under `--json`.
- **To an agent** — the `make` tool returns the same refusal and the same reason. There is no
  argument that overrides it.

## Security {#security}

`atf edit` binds loopback. It listens on `127.0.0.1` and prints the port. It does not bind `0.0.0.0`,
and there is no flag that makes it.

**There is no built-in authentication.** Anyone who can reach the port has whatever the suite has:
the ability to run tests against every environment in the manifest, and to make and delete resources
in the mutable ones, using the credentials in your environment. That is the same power `atf` on your
command line has.

Every mutation is gated. A request that would change an environment is refused unless that
environment is `mutable: true`, and the check is made by the core, not by the disabled button.
`atf edit --mcp` passes through the same gate, so an agent cannot reach anything a browser could not.

Two practical rules follow:

- Do not expose the port. If you need the editor on a remote machine, forward the port over SSH
  rather than binding it publicly.
- Do not point a manifest at production and mark it `mutable: true` for convenience. The gate is
  the manifest.

The trade-off is stated rather than solved: no authentication means no user model, no permissions
and no audit trail. The boundary is the loopback interface, and it is the only one.

## Where to go next

- [The command](the-command.md) — every operation the editor performs, in the form CI runs it. If you
  found something in the editor, this is how you put it in a pipeline.
- [Extending ATF](extending-atf.md) — the five registries the editor renders. Registering an adapter
  or a marker changes what the catalogue and the composer offer, with no editor code touched.
- [One engine, two surfaces](../explanation/one-engine-two-surfaces.md) — what the no-privileged-path
  rule costs, what it buys, and what happens to frameworks that break it.
