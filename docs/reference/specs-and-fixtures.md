# Specs and fixtures reference

`atf.plugin` is a pytest plugin. It is enabled from a `conftest.py` at the root of a suite — pytest
only honours `pytest_plugins` there:

```python
pytest_plugins = ["atf.plugin"]
```

At import it loads the manifest, builds the adapters for the active environment, and loads the
catalog. A configuration or catalog error therefore surfaces during **collection**, not as a failing
test. See [Life of a run](../explanation/life-of-a-run.md#collect).

## The provisioning step {#the-provisioning-step}

```gherkin
Given the <resource_type> "<name>"
```

Provisions the named resource and its whole [closure](../explanation/glossary.md#closure), and
assigns the resulting record to `context.<resource_type>`.

`Given the account "primary"` sets `context.account`. A scenario may provision any number of
resources; each lands under its own type name.

There is one such step, not one per type: it is matched by
`parsers.parse('the {resource_type} "{name}"')`, with the type captured as a parameter. A
`resource_type` that is not in the catalog fails the test and lists the known types. A `name` with
no matching instance raises `UnknownResource`.

Ephemeral resources provisioned by this step are recorded on `context._ephemeral` and deleted when
the scenario ends.

### Scenario Outlines {#scenario-outlines}

pytest-bdd substitutes `<placeholders>` from the `Examples` table before the step is matched, so
`Given the account "<who>"` receives the concrete name and each row becomes its own test.

### Background {#background}

`Background:` steps run before every scenario in the feature, and ATF treats them as part of each
scenario: the resources they name are that scenario's resources, they appear in the cockpit's
Gherkin, and they count towards its [readiness](cockpit.md#readiness).

```gherkin
Feature: Lists
  Background:
    Given the account "primary"

  Scenario: A list belongs to its account
    Given the todo_list "groceries"
    Then the list belongs to the account
```

Every scenario in such a feature exercises `accounts.primary`.

### Tags {#tags}

Scenario tags are available as pytest markers. Two are read by ATF itself:

| Tag | Effect |
|---|---|
| `@skip` | The scenario's state becomes `skipped`, and it is listed under the cockpit's [gaps](cockpit.md#overview-gaps). |
| `@wip` | The same. |

Neither tag skips the test on its own — pytest does not know them until you register the marker and
act on it. To actually skip, add a hook in your `conftest.py`:

```python
def pytest_collection_modifyitems(items):
    for item in items:
        if "wip" in {mark.name for mark in item.iter_markers()}:
            item.add_marker(pytest.mark.skip(reason="work in progress"))
```

## Collecting a feature {#collecting}

A `.feature` is normally handed to pytest by a module that calls `scenarios("…")`. For a feature
that needs step code of its own, that module is where the code lives. For one written entirely in
the vocabulary ATF provides, it is a file whose whole content is an import and a call.

**ATF collects a `.feature` nobody bound.** The file becomes a module that was never on disk, one
test per scenario, built with pytest-bdd's own `scenario()` — so the nodeids, the failures and the
report are exactly what a hand-written binding would produce.

What such a feature can reach, and what it cannot, is pytest's fixture rule and nothing new:

| Reachable from an auto-collected feature | Not reachable |
|---|---|
| every step ATF defines | a step declared in some *other* module |
| every [phrase](phrasebook.md) this suite writes | |
| anything a `conftest.py` above it declares | |

A feature needing a `@when` of its own therefore still wants its module — or the step moves into a
`conftest.py`, where every feature can see it. A feature some module already binds is left alone;
collecting it twice would run every scenario twice.

## Acting on a system {#acting}

```gherkin
When I <action> the <type> "<name>"
When I list every <type>
When I run "<command line>"
```

An adapter offers *mechanical* verbs; the catalog names a *domain* action in terms of them; the
spec says the domain action. Nothing in between needs code.

```yaml
task:
  system: rest
  path: /tasks
  actions:
    complete: { patch: { done: true } }
    reopen:   { patch: { done: false } }
```

```gherkin
Given the task "laundry"
When I complete the task "laundry"
Then the task "laundry" is done
```

The action's body is adapter configuration, exactly as `path` is: ATF validates its shape and reads
nothing into it. See [`actions:`](catalog.md#actions) for what the built-in `rest` adapter
understands, and [`act`](adapter-spi.md#act) for writing your own.

**`delete` is ATF's own** and needs no declaration — every adapter has one, and a backend without
deletion no-ops it through `NoopDelete`, so the claim after it reads the resource back and finds
out. A type may not declare an action by that name.

**`I list every <type>`** reads back everything of a type the environment holds, onto
[`result`](#slots) — which is [`browse`](adapter-spi.md#browse), the optional half of the SPI. A
type whose listing is scoped to a parent says so rather than guessing at one, and an adapter that
cannot list says that.

**`I run "<command line>"`** runs a command line through the [`command`](manifest.md#command-settings)
system this environment configures, and puts what came back on `result` — the exit code, both
streams, and `ok`. The line is written the way a person writes one: `atf seed local`, split the way
a shell splits it.

An action puts what it produced on `result`, so a scenario can claim something about the response
as well as about the resource. A system that says nothing useful leaves the record the action was
performed on, so there is always something there.

## Acting on an interface {#ui}

A page is a resource like any other, and the controls on it are named **inline**, by **role** and
**accessible name** — never in the catalog, and never with a selector.

```yaml
# The only thing a catalog says about a page is where it is.
page:
  system: html          # what the server sent — no browser
  mode: data
  natural_key: at
  id_field: at

screen:
  system: browser       # the same page, after it has run
  mode: data
  natural_key: at
  id_field: at
```

**Two systems, one vocabulary.** [`html`](manifest.md#html-settings) reads the page a server sent
and [`browser`](manifest.md#browser-settings) reads the page a browser ran. They answer the same
claims, so which one a suite configures decides what a claim *costs*, never what it says — and most
of what there is to say about a server-rendered interface is true of the response, which needs
nothing installed.

Where they differ is honest and narrow. Only a browser can see a stylesheet apply, a fragment swap
in or a combobox open — and only a browser can be *acted* on, because reading a response can never
click anything. The acting steps say so where there is no browser rather than quietly doing less.

```gherkin
Given the screen "compose"
When I click the combobox "what is this about…"
And I type "groceries" into the combobox "what is this about…"
Then the option "groceries" is showing
And the option "every owner" is not showing
```

| Step | What it does |
|---|---|
| `When I click the <role> "<name>"` | clicks it |
| `When I type "<text>" into the <role> "<name>"` | replaces its contents |
| `When I choose the <role> "<name>"` | picks an option |
| `Then the <role> "<name>" is showing` | it is there and visible |
| `Then the <role> "<name>" is not showing` | it is not — *hidden* counts, which is what a person means |
| `Then the <role> "<name>" reads "<text>"` | compares what it says |
| `Then the <role> "<name>" is disabled` | it is there and refuses to be used |
| `Then the <role> "<name>" is enabled` | it is there and usable |
| `Then the words "<text>" are showing` | prose, which has no accessible name |
| `Then the words "<text>" are not showing` | it does not |

**Why role and name.** They are what a screen reader announces, so a scenario written in them is a
scenario about what a person can perceive — and they are what an accessibility tree exposes, so they
are also the most stable thing to automate against. A selector describes today's markup; a role and
a name describe the thing. A catalog node per control would be a Page Object with a YAML file for a
class, and would put the shape of a template into the file that describes the domain.

**Prose is the exception.** ARIA computes an accessible name for things you can *do* something to,
and a paragraph is not one — so what a page *says* is claimed with `the words "…"`, which is still
what a reader reads and still not a selector.

**Disabled is not the same as absent**, and the difference is worth a claim of its own: an
interface that hides what you may not do teaches nothing, and one that offers it and then refuses
is worse. Disabled, with the reason beside it, is the third option.

**A claim waits, where waiting means anything.** In a browser, `is showing` and `the words …` wait
for what they name to arrive, because an interface that swaps a fragment in after a request has
settled is asynchronous, not broken. A response is finished when it arrives, so `html` answers at
once.

**A failure says what is there.** Naming a control that is not on the page lists the ones that are,
with that role, so a wrong name is one line to fix rather than a hunt.

**What `html` reads is a documented subset of ARIA**: the implicit role HTML gives an element, with
an explicit `role=` winning, and the accessible name computed in the specification's order —
`aria-labelledby`, `aria-label`, what HTML names it natively (a label, an `alt`, a caption, what is
written on it), then `title`. It cannot see layout or a stylesheet, so only an inline
`display: none`, a `hidden` or an `aria-hidden` hides something from it. A page whose naming it
cannot follow is a page to look at with `browser`.

Playwright is an optional dependency (`uv sync --group browser`). Without it that adapter reports
itself [unavailable](adapter-spi.md#unavailable) and scenarios tagged as needing it
[skip with the reason](manifest.md#requires) — while everything `html` can answer still runs.

## Read-and-compare steps {#read-and-compare-steps}

A family of steps, registered by the plugin, available in every suite without writing anything. They
exist because every project was writing the same family for itself: `the plan is "standard"` is not
domain knowledge, it is a record read through an adapter ATF already has and compared with a value
you already wrote.

Each one is about **a resource** the catalog declares, **a slot** a step put on the context, or
**a whole type** of resource.

About a resource:

| Step | Passes when |
|---|---|
| `Then the <type> "<name>" exists` | Reading the resource back finds it. |
| `Then the <type> "<name>" is gone` | Reading it back finds nothing. |
| `Then the <type> "<name>" field "<f>" is "<v>"` | The record's `<f>` compares equal to `<v>`. |
| `Then the <type> "<name>" field "<f>" is not "<v>"` | It does not. |
| `Then the <type> "<name>" field "<f>" contains "<v>"` | The record's `<f>` [holds](#containment) `<v>`. |
| `Then the <type> "<name>" field "<f>" does not contain "<v>"` | It does not. |
| `Then the <type> "<name>" field "<f>" is empty` | The record's `<f>` is absent, or is text, a list or a record with nothing in it. |
| `Then the <type> "<name>" field "<f>" is not empty` | It holds something. |

About [a slot](#slots) — `<s>` is the name a step wrote it under, usually `result`:

| Step | Passes when |
|---|---|
| `Then the <s> contains the <type> "<name>"` | One of the records in `context.<s>` is that resource. |
| `Then the <s> does not contain the <type> "<name>"` | None of them is. |
| `Then the <s> field "<f>" is "<v>"` | The single record in `context.<s>` has that `<f>`. |
| `Then the <s> field "<f>" is not "<v>"` | It does not. |
| `Then the <s> field "<f>" contains "<v>"` | It [holds](#containment) `<v>`. |
| `Then the <s> field "<f>" does not contain "<v>"` | It does not. |
| `Then the <s> field "<f>" is empty` | It is absent or holds nothing. |
| `Then the <s> field "<f>" is not empty` | It holds something. |

About a whole type:

| Step | Passes when |
|---|---|
| `Then the environment has <n> <type>` | The environment holds exactly `<n>` records of that type. |

They name a field; they never require one. ATF reads the field you named and compares it with the
value you wrote, and knows nothing else about it — see
[where the line on record shape falls](../explanation/the-model.md#record-shape).

Counting needs the adapter to be able to *list* what a type holds, which is the optional
[`browse`](adapter-spi.md) half of the SPI. An adapter without one makes the claim say so and name
what is missing, rather than failing obscurely.

### Tables: one node, many variations {#tables}

A catalog is a set of named resources, which is fine until every variation of one needs another
entry — `task`, `overdue_task`, `done_task`, `overdue_done_task`. That is the **Object Mother**
pattern: a global set of factories where every variation needs a new one and every scenario couples
to a specific one. A table says what is different where it is needed, and the catalog keeps one
node.

```gherkin
Scenario: An overdue task is still an ordinary task
  Given the task "milk" but:
    | due_at | ${now-1d 09:00} |
  Then the task "milk" is:
    | title  | Buy milk |
    | done   | false    |
    | uuid   | #notnull |
```

**`Given the <type> "<name>" but:`** provisions that node with part of its body written differently,
**for this scenario only** — the catalog is session state every other scenario reads, so the
variation is a copy and never outlives the scenario that asked for it. The varied body is what
`find` matches on as well as what `create` sends, so overriding a field of the
[natural key](../explanation/glossary.md#natural-key) genuinely selects a different resource.

**`Then the <type> "<name>" is:`** and **`Then the <s> is:`** compare a whole table of fields in one
claim. The table says **what must match, not what may exist**: a field the table does not mention is
not looked at, because a record carries ids and timestamps a scenario has no opinion about and
requiring it to list them all would make every backend change a hundred red scenarios. `#absent` is
how a scenario says a field must *not* be there.

A failure lists **every** field that disagrees, so they are fixed in one pass rather than one run
each.

#### Markers {#markers}

Sometimes the value is not the point: an id is whatever the backend assigned, a timestamp is
whatever `now` was. A marker says what *kind* of thing must be there instead.

| Marker | Passes when the field |
|---|---|
| `#present` | is there, whatever it holds |
| `#absent` | is not there at all |
| `#notnull` | is there and holds something |
| `#null` | holds nothing |
| `#string` | holds text |
| `#number` | holds a number (and not `true`/`false`) |
| `#boolean` | holds a true/false value |
| `#uuid` | holds a UUID |

A closed list, on purpose: every entry is something ATF can decide, and a pattern language here
would be a schema language nobody asked for — and could not be offered in a dropdown, which is what
[the composer](cockpit.md) needs.

`${...}` resolves inside a table's cells, which it has to do explicitly: pytest-bdd hands a table
over as one argument rather than as step values, so it never reaches the hook that resolves them
everywhere else.

**A table step is not offered by the composer.** The builder has no way to write the table under the
line, and offering a line it cannot finish is worse than not offering it — so these are written by
hand, or in the composer's text mode, which is held to exactly the same checks.

### What `contains` means {#containment}

Containment means one thing per kind of value, and only the kinds where it means something
decidable are answered:

| Field holds | `contains "<v>"` passes when |
|---|---|
| text | `<v>` is a substring of it |
| a list | one of its items [matches](#comparing) `<v>`, so `contains "3"` finds the number `3` |
| a number or a boolean | its text holds `<v>` |
| nothing (`null`) | never |
| a record | **refused** — a record holds keys and values both, so name the field inside it instead |

`is empty` is true of `null`, `""`, `[]` and `{}`. A number is never empty and neither is `false`:
`0` and `false` are values a backend returned, and reading them as absence is the mistake the
[comparison rules](#comparing) are ordered to avoid.

### They read the resource back, not the context {#reading-back}

Each step resolves its resource from the catalog and asks the adapter for it *at the moment the step
runs*. It never looks at what an earlier step left on [`context`](#context).

That is what keeps an assertion independent of the action before it:

```gherkin
Given the task "laundry"
When I complete the task                        # your code, a PATCH against the API
Then the task "laundry" field "done" is "true"  # ATF's, and it re-reads
```

The `When` is real code because performing an action is; the `Then` is still generic, because it
goes back to the backend and looks. A step that compared against the record the scenario was handed
would still be reporting `false`.

The listing cache is dropped before each read, so a step always sees the environment as it is now.

**Ephemeral resources are the exception, and a forced one.** An
[ephemeral](../explanation/lifecycles.md) resource is never looked up — that is what ephemeral
means — so these steps use the record the scenario built. `is gone` therefore refuses on an
ephemeral type rather than passing vacuously.

### Comparing a written value with a real one {#comparing}

Gherkin has only strings; records have booleans, numbers, timestamps and `null`. The *record's*
value decides how the written one is read, never the other way round:

| Record holds | `"<v>"` matches when it is |
|---|---|
| a boolean | `true`/`yes`/`1`, or `false`/`no`/`0`, in any case |
| a number | any spelling of the same number — `3`, `3.0` |
| nothing (`null`) | empty, `null` or `none` |
| a timestamp | the same instant, however it is spelled — `Z` or `+00:00` |
| a list or mapping | its JSON |
| text | exactly that text |

Reading the *written* side first is how `"0"` starts matching `false`, so ATF does not. The same
rule decides whether an adapter's `find` recognised an existing resource — one comparison, in
`atf.compare`.

### What they say when they fail {#failures}

A failure names the field, both values, and what kind of thing each is:

```
task 'milk' field 'done' is true (a true/false value), not "false"
```

A resource that could not be read names what was looked for; an unknown field lists what the record
actually carries; an unknown type or instance lists the ones the catalog declares.

### Slots: `the result`, and anything else a step names {#slots}

A **slot** is any attribute a step wrote on [`context`](#context). `result` is the name ATF suggests
for what a `When` produced, and a suite with one action per scenario will only ever need that one.

```python
@when("I list the owner's lists")
def _(context, api):
    context.result = api.lists_of(context.owner)
```

```gherkin
Then the result contains the todo_list "groceries"
```

Naming the slot is what lets a scenario with **two** actions say which of them it means — with one
slot, only the second survives:

```python
@when(parsers.parse('I list the lists of "{who}", holding them as {slot:w}'))
def _(context, api, who, slot):
    setattr(context, slot, api.lists_of(who))
```

```gherkin
Then mine contains the todo_list "groceries"
And theirs does not contain the todo_list "groceries"
```

A field assertion on a slot needs *one* record — a listing of five has no one `title`, so it is
refused rather than guessed at, and the message points at `contains`. A slot that was never set
names the ones the scenario is actually holding, so a mistyped name is one line to fix.

**What counts as a record** is one decision, made in `atf.records`: a mapping, a dataclass, a
`NamedTuple`, or an object offering `to_dict()` / `model_dump()`. A dataclass's public properties
are fields too — `Outcome` keeping `stdout` and `stderr` and joining them in an `output` property is
exactly the case, and `the result field "output" contains "…"` is what a suite would otherwise have
hand-written a `@then` for. Anything else is not a record, and the failure says so.

Together with a [provider](providers.md), that closes the loop on an action that takes a value in
and hands one back:

```gherkin
Given the todo_list "groceries"
When I rename it to "${fake:company}"
Then the result field "title" is "${fake:company}"
```

Both lines write the same expression and see the same company, because a provider call is
[evaluated once per scenario](providers.md#one-evaluation). Every value a step is handed has its
placeholders resolved, whoever wrote the step — so this works in a step written this morning, with
nothing added to it.

## Fixtures {#fixtures}

| Fixture | Scope | Value |
|---|---|---|
| [`context`](#context) | function | An empty `atf.context.Context`, the per-scenario scratchpad. |
| [`<resource_type>`](#resource-type-fixtures) | function | `Callable[[str], Record]` — provisions that type by instance name. |
| [`materializer`](#materializer-fixture) | session | The `Materializer` for the active environment. |
| [`env`](#env) | session | The active environment name. |
| [`client_config`](#client_config) | function | `environments.<env>.clients`, with `*_env` pointers resolved. |

Everything else in a suite is your own. Type names are validated against these names when the
catalog loads; see [reserved type names](catalog.md#reserved-names).

### `context` {#context}

The per-scenario scratchpad, and the only channel between steps. ATF sets
`context.<resource_type>` for each provisioned resource and `context._ephemeral` for teardown; every
other attribute belongs to your suite.

The record assigned is whatever the adapter returned, untouched. Its field names are the suite's
contract with its own backend — ATF neither defines nor validates them.

It behaves exactly like the `types.SimpleNamespace` it used to be — `context.foo = x`,
`context.foo`, `del context.foo`, and an `AttributeError` for anything never set — so no existing
step changes. It additionally *describes* what is set on it:

| Member | Value |
|---|---|
| `values` | Everything a step put here, without ATF's own bookkeeping. |
| `slots` | A `Slot` per attribute: its `name`, `kind`, the `fields` it carries, a `count`, and the `resource_type` it is or looks like. |
| `note(name, …)` | Say what a slot is when the setter knows more than the value shows. The provisioning step uses it. |

A `Slot` never holds a value, only names, kinds and counts. What a scenario was holding when it
finished is reported to the run and kept in [run history](cli.md#atf-import-run) on disk, and a record
carries a token as readily as a title.

Two attribute names mean something to ATF:

- **`result`** — what a step produced. Only a suggested name: [any slot can be asserted on](#slots)
  by the name a step gave it. `result` is what a suite with one action per scenario will use, and
  what the cockpit's composer offers first.
- **`_ephemeral`** — the ephemeral resources this scenario built, read by teardown and by an
  assertion on one of them. Attributes starting with `_` are ATF's own and are not described.

### `<resource_type>` {#resource-type-fixtures}

One fixture is generated per type in the catalog, named after the type. It is a callable taking an
instance name and returning that resource's record, provisioning the closure if needed and tracking
any ephemeral resources it created for teardown.

Because it is an ordinary fixture, it works in a plain pytest test as well as behind a Gherkin step:

```python
def test_plan(account):
    assert account("primary")["plan"] == "standard"
```

### `materializer` {#materializer-fixture}

The [provisioning engine](#materializer) for the active environment, session-scoped. Reach for it
when you need something the generic step does not express — provisioning inside a `When`, or reading
status.

### `env` {#env}

The active environment name: `ATF_ENV` if set, else the manifest's `default_env`. Useful for a step
that must behave differently against staging, though needing it often means the difference belongs
in the manifest instead.

### `client_config` {#client_config}

The mapping under `environments.<env>.clients`, with `*_env` pointers resolved. ATF does not
interpret it; your own fixture consumes it:

```python
@pytest.fixture
def api(client_config):
    return MyClient(**client_config["api"])
```

For that fixture to be visible to specs, import it in a `conftest.py` at or above the specs
directory.

## Teardown {#teardown}

An autouse, function-scoped fixture calls `materializer.teardown(context._ephemeral)` after every
test.

Deletion is best-effort: failures are logged under the `atf.materializer` logger, never raised. A
test that passed has told you something true, and a broken deletion endpoint should not overturn
that verdict. Persistent resources are left in place.

## `Materializer` {#materializer}

The object behind the [`materializer`](#materializer-fixture) fixture, and the same object adapters
receive as `ctx`.

| Member | Signature | Description |
|---|---|---|
| `nodes` | `dict[str, Node]` | Every catalog node by id. |
| `types` | `dict[str, dict]` | The type registry. |
| `env` | `str` | The active environment. |
| `reload` | `() -> None` | Re-reads the catalog and clears caches. |
| `resolve_id` | `(type, name) -> str` | The node id for a type and instance name. Raises `UnknownResource`. |
| `ensure` | `(type, name) -> Record` | Provisions the resource and its closure; returns its record. Raises `ProvisioningError` naming the offending node. |
| `ensure_closure` | `(type, name) -> tuple[Record, dict[str, Record]]` | The same, plus every record provisioned on the way — what the generated fixtures use, so ephemerals reached through a dependency can be torn down. |
| `find_existing` | `(node) -> Record \| None` | Looks a node up without creating it. Returns `None` for ephemeral nodes. |
| `status` | `(collection=None) -> dict[str, dict]` | Per-node `{status, detail, identity?}`. Never raises. |
| `closure` | `(node_id) -> list[str]` | That node plus every transitive dependency. |
| `materialize` | `(subset, keep_going=False) -> dict` | Provisions an iterable of node ids, and their dependencies, in dependency order. Returns `{"results": [...], "records": {...}}`. |
| `create_closure` | `(node_id, keep_going=False) -> dict` | `materialize` over that node and its dependencies. |
| `create_all` | `(keep_going=False) -> dict` | `materialize` over the whole catalog. |
| `teardown` | `(records) -> None` | Deletes the ephemeral resources among `records`. Never raises. |

`materialize` results are `{"id", "action", "ok"}` with `"detail"` when `ok` is `False`. `action` is
one of `created`, `exists`, `reference`, `error`, `unsupported`, `blocked`. It stops at the first
failure unless `keep_going`, which instead reports a failure's dependents as `blocked` and continues
with independent subtrees.

`ensure` never continues past a failure: the spec needs that one resource, so there is nothing to
continue toward.

## Exceptions {#exceptions}

| Exception | Module | Raised when |
|---|---|---|
| `ConfigError` | `atf.config` | The manifest is missing, invalid, or names an unset environment variable. |
| `CatalogError` | `atf.catalog` | The catalog fails validation. Carries `.problems`, a list of every problem found. |
| `ProvisioningError` | `atf.materializer` | `ensure` could not provision a resource. Carries `.node_id` and `.detail`. |
| `UnknownResource` | `atf.materializer` | A type and name do not match any node. Subclasses `LookupError`. |
| `Unresolved` | `atf.placeholders` | A `${...}` placeholder cannot be resolved. Carries `.expression`. |
| `AuthError` | `atf.http` | An auth scheme is unknown or incomplete, or a session login failed. |

## Timeouts {#timeouts}

| Operation | Limit | Constant |
|---|---|---|
| Discovery (`pytest --collect-only`) | 300 s | `atf.discovery._COLLECT_TIMEOUT` |
| A synchronous run (`atf run`) | 1800 s | `atf.runner.DEFAULT_TIMEOUT` |
| A cockpit background run | 1800 s | `atf.jobs.DEFAULT_JOB_TIMEOUT` |

None are settable from the manifest. A run that exceeds its limit is killed, reported as timed out,
and releases the environment's run slot.

## Concurrency {#concurrency}

**Single-worker only.** The session materializer, its listing cache and get-or-create are not safe
under parallel workers: two workers can each find a resource absent and each create it. Do not
enable `pytest-xdist`.

If you need parallelism, split by environment — one worker per environment, never several per
environment. For the same reason, avoid two pipelines provisioning one environment at once.

## Where to go next

- [How to add a scenario](../how-to/add-a-scenario.md) — this surface, used.
- [Life of a run](../explanation/life-of-a-run.md) — what the provisioning step sets in motion.
- [Catalog reference](catalog.md) — the nodes the step resolves against.
- [About the model](../explanation/the-model.md) — why resources, specs, tests and fixtures are
  separate things.
