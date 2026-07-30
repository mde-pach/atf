# Assertions reference

One of four pages on the pytest surface `atf.spec.plugin` adds: this one covers claiming something
about a resource or a [slot](#slots) once [provisioning](provisioning.md) or
[acting](acting.md) has produced one. See also [fixtures](fixtures.md).

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

| Marker | Passes when the field | Pact's name for it |
|---|---|---|
| `#present` | is there, whatever it holds | — |
| `#absent` | is not there at all | — |
| `#notnull` | is there and holds something | — |
| `#null` | holds nothing | null matcher |
| `#str` | holds text | `match.str()` |
| `#int` | holds a whole number (and not `true`/`false`) | `match.int()` |
| `#decimal` | holds a number with a fractional part | `match.float()` |
| `#number` | holds a number of either kind | — |
| `#bool` | holds a true/false value | `match.bool()` |
| `#uuid` | holds a UUID | `match.uuid()` |
| `#date` | holds a date | `match.date()` |
| `#datetime` | holds a date and a time | `match.datetime()` |
| `#time` | holds a time of day | `match.time()` |
| `#regex <pattern>` | holds text matching the pattern | `match.regex(…, regex=…)` |

**The names follow [Pact](https://docs.pact.io)'s matchers**, because this is not a new idea and a
project that already publishes contracts should not have to learn a second vocabulary for the same
act. Two differences are worth knowing:

- **A Pact matcher wraps an example value; a marker replaces it.** `match.int(12345)` keeps the
  `12345`, because a pact file is a contract published to the provider team and needs concrete data
  in it. A marker is an assertion — nobody downstream reads it — so there is nothing to keep.
- **Presence has no Pact equivalent.** `#present`, `#absent`, `#notnull` and `#null` are about
  whether a field is *there*, which Pact expresses through the shape of the body. A claim has no
  body to shape, so it says it.

Otherwise a closed list on purpose: every entry is something ATF can decide, and every one can be
offered in a dropdown, which is what [the composer](cockpit.md) needs. `#regex` is the single
exception, because a pattern is the one expectation that cannot be enumerated and Pact treats it as
core:

```gherkin
Then the account "primary" is:
  | reference  | #regex ^AC-[0-9]{6}$ |
  | created_at | #datetime            |
  | id         | #uuid                |
```

`${...}` resolves inside a table's cells, which it has to do explicitly: pytest-bdd hands a table
over as one argument rather than as step values, so it never reaches the hook that resolves them
everywhere else.

A table step can also stand behind [a phrase](phrasebook.md#tables), written as an ordinary YAML
mapping, and **the composer writes one**: choose it as what the claim is about, and each field the
resource is known to have is offered with what it currently holds, alongside the markers. A
whole-shape claim is the most tedious thing in ATF to write by hand and the one the cockpit already
had every answer for.

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
runs*. It never looks at what an earlier step left on [`context`](fixtures.md#context).

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
`atf.model.compare`.

### What they say when they fail {#failures}

A failure names the field, both values, and what kind of thing each is:

```
task 'milk' field 'done' is true (a true/false value), not "false"
```

A resource that could not be read names what was looked for; an unknown field lists what the record
actually carries; an unknown type or instance lists the ones the catalog declares.

### Slots: `the result`, and anything else a step names {#slots}

A **slot** is any attribute a step wrote on [`context`](fixtures.md#context). `result` is the name
ATF suggests for what a `When` produced, and a suite with one action per scenario will only ever
need that one.

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

**What counts as a record** is one decision, made in `atf.model.records`: a mapping, a dataclass, a
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

## Where to go next

- [Provisioning reference](provisioning.md) — declaring the resource a claim reads back.
- [Acting reference](acting.md) — the steps that put a value on the slot a claim reads.
- [Fixtures reference](fixtures.md) — `context`, and what a slot is.
- [Catalog reference](catalog.md) — the nodes a claim resolves against.
- [About the model](../explanation/the-model.md) — why resources, specs, tests and fixtures are
  separate things.
