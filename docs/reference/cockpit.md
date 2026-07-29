# Cockpit reference

The cockpit is a server-rendered web app started with [`atf serve`](cli.md#atf-serve). It reads the
catalog, the specs and the run history for **one environment at a time**, and can provision
resources and run tests in environments the manifest marks mutable.

It has three verticals, and the rail reads **Overview**, **Scenarios**, **Resources** — the third is
the catalog, labelled by what it holds. There are no breadcrumbs; each page opens with one line
saying what it answers. Everything below is scoped to the selected environment.

## Overview {#overview}

`GET /` — *what the last run said, what is standing in the way, and what to do next.*
`GET /overview/summary` returns the same answer as a fragment, which the
[activity dock](#activity-dock) pulls in when a job finishes so the headline re-syncs without a
reload.

Nothing on this page counts something that is true by construction. A number that cannot go wrong
is not worth a reader's attention.

### The verdict {#verdict}

One sentence, at the top, answering the question the app exists to ask.

| Verdict | When |
|---|---|
| **Not yet** | Nothing has ever run against this environment. |
| **No — N scenarios failing** | Something failed in the last run. |
| **Not fully** | Nothing failed, but scenarios are [never run](#scenario-states) or [blocked](#readiness). |
| **Yes** | Every scenario passed. |

Each carries the supporting counts and the time of the last run.

### Start here {#first-run}

When no run has ever finished against this environment, the page leads with the numbered way out of
it — *Provision N resources*, then *Run N scenarios* — rather than a screen of zeros. It disappears
once there is a run on record.

### Scenario states {#overview-states}

A count per state: `passing`, `failing`, `blocked`, `never run`, `skipped`. Each links to
[`/scenarios?state=<state>`](#state-links), so "the failing ones in staging" is a URL you can
bookmark. Failing scenarios are also listed inline.

### Environment {#overview-environment}

How much of the catalog exists here — present against declared — split into what a run would
create (**absent**) and what it could not (**broken**). The difference is
[readiness](#readiness), and it is the one distinction worth reading carefully.

### Recent runs {#overview-runs}

The last handful of runs from the [history](#run-history), with their outcomes and when they
happened, plus any test flagged [flaky](#scenario-states) — listed under the scenario title it
belongs to, because nobody recognises a pytest node id.

### Gaps worth acting on {#overview-gaps}

Resource types no scenario exercises, scenarios that have never run, and scenarios that are
skipped. When there are none, the page says so rather than showing an empty heading.

!!! note "There is no coverage meter"

    An earlier version showed Config, Coverage and Health meters. Coverage counted a spec as
    covered whenever any test was bound to it — which pytest-bdd always does — so it read 7/7
    permanently and could never surface a problem. The honest questions it was trying to ask are
    now [gaps](#overview-gaps): which types nothing exercises, and which scenarios have never run.

### When discovery fails {#overview-discovery-failed}

If collection produced no scenarios at all, the page says so before anything else. Every count
below would otherwise be a confident claim about an empty model.

## Scenarios {#scenarios}

`GET /scenarios` lists every scenario; `GET /scenarios/{spec_id}` opens one. Both render the same
page, so a scenario is always shown in the context of the list.

A pytest-bdd test is mechanically one-to-one with a scenario, or one per row of its `Examples`
table, so there is no separate Tests vertical: a test is shown beneath the scenario it covers, never
beside it.

### Filtering by state {#state-links}

`GET /scenarios?state=<state>` opens the list with that filter already applied, where `<state>` is
one of `passing`, `failing`, `blocked`, `never run` or `skipped`. The Overview's state counts link
straight here.

Arriving filtered is a first-class way in, not a refinement you make once you are already looking at
the list — and it means "the failing scenarios in staging" is a URL you can bookmark or paste into a
ticket.

### What a scenario page carries {#scenario-page}

| Section | Contents |
|---|---|
| Gherkin | The scenario as written, including inherited `Background:` steps. |
| Resources | Every resource the scenario names, each with its live status in this environment. |
| Readiness | What running it now would do: how many resources it would create, and anything that would stop it. See [readiness](#readiness). |
| Tests | The covering tests — one, or one per `Examples` row. |
| Last outcome | The result of the most recent run of each covering test, and when it ran. |
| Failing step | When the last outcome was a failure, the Gherkin step the run reached. |

Resource names in the Gherkin link to the resource type that owns them.

### Scenario states {#scenario-states}

One state per scenario, decided in this order:

| State | Meaning |
|---|---|
| `skipped` | Tagged `@skip` or `@wip`. |
| `failing` | A covering test failed or errored in the last run. The failing Gherkin step is shown. |
| `blocked` | A resource in the scenario's closure is in a state a run cannot fix. See [readiness](#readiness). |
| `passing` | Every covering test passed. |
| `never run` | No run on record for this environment. |

`failing` outranks `blocked` deliberately: a real failure you have already seen is more informative
than a prediction about the next run.

**`flaky` is a flag, not a state.** It is set alongside whichever state applies, from the
[run history](#run-history): a test whose verdict flipped between passed and failed across the
recent runs, with no change to the suite in between. A skip is not a verdict and does not count as a
flip; an error counts as a failure. A flaky verdict is worth neither green nor red.

### Readiness {#readiness}

Before a scenario runs, the cockpit walks the closure of every resource it names and sorts them into
two lists.

**Blockers** — states that running cannot fix:

| State of a named resource | Why it blocks |
|---|---|
| `unsupported` | No adapter is configured for that system in this environment. |
| `error` | The adapter raised while looking it up. |
| `absent` **and** [`mode: reference`](catalog.md#mode) | ATF never creates a reference resource. Its absence means the environment is not configured as the suite assumes. |

**Will create** — resources that are absent but creatable. These are **not** blockers, and the
cockpit shows them as information: running the scenario is what makes them exist. That is the whole
premise of the catalog, and it would be wrong to warn about it.

So an untouched environment full of absent resources is *ready*, not blocked. An environment missing
one feature flag the suite treats as a reference resource is blocked, even though everything else is
green.

[Provision](#provision) clears the second list, and the first where the cause was `error`. An
`unsupported` blocker is fixed in the manifest, not in the environment.

## The composer {#composer}

`GET /compose` — *write a scenario without opening an editor.* Reachable from the Scenarios page and
from any scenario, which starts a new one in the same feature.

The premise is that a scenario is a choice from a closed list rather than a piece of writing. ATF
knows every resource the catalog declares, every step this suite can reach and every field a
resource is known to have, so the page asks four questions and writes the Gherkin:

| Row | Chosen by |
|---|---|
| `Given` | a resource type, then one of its instances |
| `When` | a step's wording — an action is a thing a suite defines or a catalog names |
| `Then` | **what it is about**, then what of it, then how, then against what |

A `Then` starts from the subject because that is what a person starts from: a resource, a whole type
of them, a [slot](specs-and-fixtures.md#slots) a step above produced, or a step of the suite's own.
Choosing a resource then offers its fields *with what each currently holds in this environment*, so
the value is usually one click rather than a guess.

### What it will not offer {#composer-refuses}

A step whose `needs` nothing above it has produced. The count and the reason are shown rather than
the option being silently missing — *"3 more steps are not offered here: nothing above this row puts
`result` on the context"* — because a hidden option is a mystery and a count is an instruction.

### Tables {#composer-tables}

A step ending in a colon takes [a table](specs-and-fixtures.md#tables), and the composer builds one:
each field the resource is known to have is offered with its current value, and
[`#markers`](specs-and-fixtures.md#markers) are offered beside the value box for the fields whose
exact contents are not the point. A half-filled row is reported; a row nobody filled in is not
written, because the page always offers a spare one and an offer is not a line.

### Trying it, and writing it {#composer-write}

**Try it** runs the draft without saving it, and reports the Gherkin step it reached. **Save**
appends it to the feature file — and writes no Python at all, because every step the composer offers
is one an [auto-collected feature](specs-and-fixtures.md#collecting) can already reach.

Writing is **not gated by `mutable_envs`** and needs a confirmation token instead: it changes files
in your repository and touches no environment. Conflating *may write to production* with *may
describe production* would make the catalog uneditable from the one place that can see what
production actually holds.

**Edit as text** switches to the Gherkin itself, held to exactly the same checks. A draft that would
not parse is never written, and a new file that would not parse is not left behind.

## The introspection surface {#introspection}

Everything the composer runs on is a plain function of a catalog and a
[discovery](#discovery) — no request, no page. [`atf serve --mcp`](cli.md#serve-mcp) offers that same
surface over [MCP](https://modelcontextprotocol.io), so an agent composes from the list the page
composes from.

The point is what it *cannot* do. An agent handed a file and a docstring writes arbitrary
automation; an agent that can only choose from `available steps × catalog nodes × phrases` cannot
write a step this suite does not define, name a resource the catalog does not declare, or assert
about a [slot](specs-and-fixtures.md#slots) nothing above it produced. Those are not rules it is
asked to follow — there is nothing on the surface that would turn them into a line.

### Three tools {#introspection-tools}

| Tool | Answers |
|---|---|
| `describe` | what can be said here |
| `compose` | these choices → the Gherkin they mean, or the reason they are not a scenario |
| `run` | a scenario this suite has, or a draft that has not been written yet |

Three, and structural rather than one per wording. `describe` returns the steps with what each
captures, needs and produces; the catalog's resources with their status in this environment and the
fields each is known to have, with current values; the [phrases](phrasebook.md) this suite writes
and what they stand for; the closed lists of comparisons and of
[`#markers`](specs-and-fixtures.md#markers); and the resource types with the actions declared on
them. All of it is derived from the tables that define ATF's vocabulary, so **adding a generic step,
a resource type, a phrase, a marker or an adapter surfaces it with no change to the MCP layer** —
which is asserted by a guard in the test suite rather than merely intended.

`compose` writes nothing. Its `problems` are one sentence each and are the useful half: *"no when
step this feature can reach is worded 'I invent a step'"*, *"the catalog declares no account called
'nobody'"*, *"nothing above this puts `result` on the context"*.

`run` is the only one that touches an environment, so it is **gated by
[`mutable_envs`](manifest.md#mutable_envs)** exactly as the composer's *Try it* is: running
provisions. A draft is run from a scratch feature that is removed afterwards; nothing is written to
the suite.

### Reaching it {#introspection-endpoint}

One process serves both — the endpoint is streamable HTTP at `/mcp/` on the same host and port as
the pages, stateless, and it refuses a request whose `Host` header names somewhere else. It carries
**no authentication**, like the rest of the cockpit; see [Security posture](#security).

## Resources {#catalog}

`GET /catalog` — *everything a scenario can ask for, whether it exists in this environment, and what
provisioning it would actually do.* `GET /catalog/type/{name}` opens a resource type;
`GET /catalog/node/{node_id}` opens one instance.

The organising axis is the [resource type](../explanation/glossary.md#resource-type): the type is
what binds to an adapter, what becomes a pytest fixture, and the word a scenario says. Collection
and system remain available as secondary groupings, because they are sometimes how you remember
where a resource lives — but they are filing accidents, not properties of the resource.

### What a resource-type page carries {#resource-type-page}

Everything a spec author needs in order to use one:

| Section | Contents |
|---|---|
| System | The backend the type lives in, and the adapter handling it in this environment. |
| Mode and lifecycle | `create` or `reference`; `persistent` or `ephemeral`. |
| Identity field | The record field carrying the identity, which `${...id}` resolves to. |
| Adapter settings | The type's remaining keys as the adapter reads them — [`path`](catalog.md#path), [`natural_key`](catalog.md#natural_key), [`list_path`](catalog.md#list_path) and the rest. |
| Fixture | The pytest fixture generated for this type, usable directly from a plain pytest test. |
| Gherkin line | The provisioning step, filled in with a real instance: `Given the account "primary"`. |
| Instances | Every instance of the type, each with its live status and its dependencies. |
| Scenarios | The scenarios that name this type. |

The generated per-type factory is documented here rather than in a vertical of its own. It belongs
to the type, and framework plumbing fixtures — `request`, `context`, `materializer`, `api` — were
noise in a browsable list. Fixtures remain a real part of the model and are documented in the
[specs and fixtures reference](specs-and-fixtures.md#fixtures).

An instance shows the same states `atf status` reports: `present`, `absent`, `ephemeral`,
`unsupported`, `error`. They are defined in the [CLI reference](cli.md#status-words).

### What an instance page carries {#node-page}

| Section | Contents |
|---|---|
| Lineage | The dependency graph around this node, with each box carrying its live status. |
| Needs / needed by | Its direct dependencies, and what depends on it. |
| Declared body | The instance body as written, with `${...}` [placeholders](catalog.md#placeholders) marked — they are the part resolved at provisioning time. |
| Identity | The identity read back from the environment, when it is present. |
| Scenarios | The scenarios that name this resource. |
| Provision | Scoped to this node, labelled with the size of its closure. |

## Provisioning and running {#provision}

Provisioning and running are **the same mechanism**. Both are a list of things attempted one at a
time, so both are background jobs, both report per-item progress, and both surface in the same
[activity dock](#activity-dock).

### Provision {#provision-button}

`POST /provision`. **One verb**, scoped by what is selected:

| Selection | What is provisioned |
|---|---|
| nothing | Everything ATF can create that is not here yet. |
| a resource type | Every missing instance of it. |
| one instance | That instance. |
| a scenario's missing resources | Those. |

Whatever the scope, each target is expanded to its
[closure](../explanation/glossary.md#closure) — dependencies first — so you never have to work out
the order. A node whose dependency failed is reported `blocked` rather than attempted. The control
is labelled with the count it would act on and, for a single instance, with the size of its closure,
so the button and the action cannot disagree.

Two kinds of resource are never offered as targets, because provisioning could only report the same
refusal back: a [`mode: reference`](catalog.md#mode) resource, which ATF may never create, and an
[ephemeral](../explanation/glossary.md#ephemeral) one, which the test that needs it builds fresh and
tears down. The control says why rather than failing when pressed.

Provisioning with nothing left to do is refused with **409**, naming the environment, rather than
starting an empty job.

### Run {#run-button}

`POST /run`. With scenarios selected, it runs their tests; with nothing selected, it runs the whole
suite. Submitted ids are intersected with what discovery found, and a submission naming nothing this
suite owns is refused with **409** — form values become pytest arguments, so only ids the cockpit
itself discovered may pass.

There is one active job per environment. Starting one while another is in flight returns the running
job rather than starting a second. A job that exceeds its timeout is killed, reported as timed out,
and releases the slot — see the [timeouts table](specs-and-fixtures.md#timeouts).

### The activity dock {#activity-dock}

One surface for both, fixed at the bottom of the window: each item moves from `pending` to `running`
to its outcome, labelled with the scenario title or the node id rather than a pytest node id.

**The dock stays visible while you navigate.** A run started from a scenario is still watchable from
the catalog, which is the point of having one activity surface instead of a progress bar per page.
It polls while a job is in flight, and when the job ends the Overview verdict re-syncs — and, after
provisioning, so does the cached status, since provisioning is exactly what makes that status wrong.

### Rescan {#rescan}

`POST /catalog/rescan`. Reloads the catalog from disk and asks the environment what exists.

It is a `POST` because it does work, but it is **a read**: it changes nothing out there. So, unlike
Provision and Run, it is **not gated by `mutable_envs` and needs no confirmation** — it works in
production, and the only thing it can cost you is the time the adapters take to answer. Press it
after editing a YAML file.

This is worth stating plainly because its predecessor, `Sync`, sat visually beside two mutating
buttons and was reasonably mistaken for a third.

### The mutation gate {#mutation-gate}

`POST /run` and `POST /provision` — and only those two — require both:

- the environment to appear in [`mutable_envs`](manifest.md#mutable_envs), or the route returns
  **409** and the control renders disabled with the reason;
- a valid confirmation token, or the route returns **409**.

The token is generated once per `atf serve` process and embedded in every page. **Restarting the
server invalidates every open tab** — reload before acting on it. The browser replays the token
automatically, so it defends against another site posting to your cockpit, not against you.

A refused action arrives **beside** the page as a message, never as a swap that destroys what you
were reading.

## Run history {#run-history}

Runs are persisted to `<suite root>/.atf/runs/*.json`, one file per run.

| Written by | When |
|---|---|
| A cockpit run | As the run completes. |
| [`atf run`](cli.md#atf-run) | As the run completes. |
| [`atf import-run`](cli.md#atf-import-run) | When a pytest `--json-report` from CI is ingested. |

Because the store is on disk rather than in memory, the cockpit knows the last outcome and its
timestamp across restarts, and can compare recent runs of the same test to flag it
[flaky](../explanation/glossary.md#flaky) or to say how long it has been failing. A CI failure shows
up in the cockpit the same way a local one does, once the report is imported.

The history is partitioned by environment and capped, oldest first, so it cannot grow without
bound. A run file this version of ATF cannot parse is skipped rather than raised: a corrupt history
must never take a page down.

`.atf/` is a local cache. Keep it out of version control; `atf init` scaffolds a `.gitignore` that
already does.

## Discovery {#discovery}

Opening any page triggers discovery for that environment if it is not already cached: ATF runs
`pytest --collect-only` in a subprocess to learn which tests exist and what they cover.

Collection **never executes a test** and never provisions anything, so viewing a page is safe in any
environment, including one outside `mutable_envs`. It does import the suite, so a manifest error or
an import error surfaces as a banner on the page rather than as failing tests.

On a discovery timeout the page still renders — scenarios come from a static parse of the `.feature`
files — but nothing derived from collection appears, and the banner says so.

## Choosing the environment {#environment-switcher}

The environment selector lives in the **top bar, beside the actions it gates** — not in the sidebar.
The environment decides what every number on every page means and whether the buttons work at all,
so it belongs next to them. A read-only environment shows a lock beside the selector saying why.

Resolution order for a request: the `?env=` query parameter, then the `HX-Env` header, then the
environment remembered from your last choice, then the one `atf serve --env` selected.

**An explicitly requested environment that does not exist is a 404** naming the environments that
do. It does not fall back to the default — silently showing you dev while you believed you were
looking at staging is how someone acts on the wrong place.

Each environment has its own cached materializer, status, discovery and job slot.

## Freshness {#freshness}

Nothing in the interface is of unknown age.

- Every page shows when the environment was last read — *checked N mins ago*, beside
  [Rescan](#rescan).
- Every scenario shows when it last ran.
- The recent-runs list is timestamped.

A status figure with no age attached is a claim you cannot evaluate, which is why there is not one.

## Search {#search}

`⌘K` (or `Ctrl-K`) searches **resource types, resources and scenarios**. Matches are ranked exact,
then prefix, then substring, weighted by which field matched, and capped at twelve. Arrow keys and
Enter work throughout.

## Vocabulary in the interface {#vocabulary}

Domain words rendered as chips carry the same one-sentence definition everywhere they appear —
served from one place in the source, so the interface and this documentation cannot drift apart.

Where the published documentation is available, a chip's "read more" links to the matching entry in
the [glossary](../explanation/glossary.md); the glossary's anchors exist to be that target and are
treated as a stable surface. ATF's source names no domain, so the cockpit reads the documentation
URL from the project's own metadata at runtime and simply omits the link when there is none. Every
definition and empty state stands on its own without it.

## Themes {#themes}

The interface follows the operating system's light or dark setting; the toggle in the top bar
overrides it, and the choice is stored in `localStorage`.

## Security posture {#security}

The cockpit has **no authentication**. `atf serve` binds `127.0.0.1`; any other `--host` prints a
warning to stderr. For shared access, put it behind an authenticating reverse proxy.

The [`mutable_envs`](manifest.md#mutable_envs) gate is the structural protection: an environment
absent from that list is read-only in the cockpit no matter what anyone clicks.

## Where to go next

- [How to find out why an environment is red](../how-to/find-out-why-an-environment-is-red.md) — the
  cockpit used in anger.
- [3. Read your suite in the cockpit](../tutorial/read-your-suite-in-the-cockpit.md) — a guided
  first visit.
- [CLI reference](cli.md#atf-serve) — the command that starts it.
- [Manifest reference](manifest.md#display) — labels and colours for your systems.
