# Provisioning reference

One of four pages on the pytest surface `atf.spec.plugin` adds: this one covers declaring what a
scenario needs. See also [acting](acting.md), [assertions](assertions.md) and [fixtures](fixtures.md).

`atf.spec.plugin` is a pytest plugin. It is enabled from a `conftest.py` at the root of a suite — pytest
only honours `pytest_plugins` there:

```python
pytest_plugins = ["atf.spec.plugin"]
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

### One to yourself {#fresh}

```gherkin
Given a fresh <resource_type> "<name>"
Given a fresh <resource_type> "<name>" but:
```

The same catalog node, provisioned as an instance **this scenario alone holds** — created rather
than found, and deleted when the scenario ends, exactly as an
[ephemeral](../explanation/lifecycles.md) resource is. The catalog does not change, and no other
scenario notices: `Given the todo_list "groceries"` still gets the shared one.

This is the article doing the work. `the todo_list "groceries"` is *the* list — found once, left in
place, the same one for everybody. `a fresh todo_list "groceries"` is one of them. Isolation is
something a **scenario** needs, and the type it needs one of is usually a type another scenario is
perfectly happy to share — so it is said where it is needed rather than declared once for everyone.

**It gets a name of its own.** Two instances of a node are only two things if something tells them
apart, and what ATF already understands about that is the
[natural key](../explanation/glossary.md#natural-key). Each key field the body writes as text gets a
discriminator appended — `slug: groceries` becomes `groceries-fresh-4a1c8e02` — from the same
[`${uuid}`](providers.md) a suite would write itself. A key field holding `${<node>.id}` is left
alone: that is the link to the resource's parent, and a copy pointing at nothing is not a copy.

Because it has a key of its own, it is read back like anything else. Every claim in
[the assertions reference](assertions.md) resolves against **this scenario's instance** for the rest
of the scenario, so `When I delete it` followed by `Then it is gone` says what it looks like it says
— about the copy, never about the resource everyone shares.

**It does not cascade.** Its dependencies are provisioned exactly as usual: found-or-created and
shared. That is the whole point — the expensive scaffolding stays seeded once, and only what this
scenario needs to itself is built per scenario. A chain of them is a line per link, and each hangs
off the previous one:

```gherkin
Given a fresh owner "primary"
And a fresh todo_list "groceries"    # under the owner this scenario just made, not the shared one
```

**`but:` means what it means everywhere else** — this node's body, varied for one scenario — with
one addition: a field the table writes is taken *exactly* as written, discriminator and all. That is
how a scenario says what makes its copy different when appending would spoil the value, which is
what happens to anything with a shape:

```gherkin
Given a fresh owner "primary" but:
  | email | mine@example.test |
```

**Three things it refuses**, each naming what to write instead:

| Asked for | Why not |
|---|---|
| a type that is already `lifecycle: ephemeral` | every scenario already gets its own — `Given the …` is one |
| a type in [`mode: reference`](catalog.md#mode) | ATF never creates one, so there is nothing to make a copy of |
| a type in [`mode: data`](catalog.md#mode) | an observation is not a resource ATF makes |

It also refuses a node it could not tell from the shared one — a type with no `natural_key`, or one
whose every key field is a link to another resource. Give the type a key, or say what makes this one
different with `but:`.

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

### Questions {#questions}

Example Mapping — the discovery practice `Rule:` exists to carry into a file — produces three kinds
of card: a **rule**, the **examples** that show it, and the **questions** nobody in the room could
answer. Gherkin has a keyword for the first two and none for the third, so the red cards end up in a
photograph of a table and are never seen again.

Write one as a comment beginning `# ?`:

```gherkin
  Rule: A card is charged once per basket

    # ? What happens if the card is declined after the basket was emptied?
    # ? Who owns the refund when a partial capture times out?

    Scenario: A basket is paid for
      ...
```

It belongs to the `Rule:` above it, or to the feature where there is none. ATF shows them under that
rule in [the cockpit](cockpit.md), counts them on the overview beside the other gaps, and renders
them on the page [`atf docs`](cli.md#atf-docs) writes — which is the point: a question read by the
people who wrote it is a question nobody can answer, and a documentation site is read by the people
who can.

**A comment, deliberately.** Gherkin already ignores them, so a feature carrying questions is still
a feature every other tool can read — ATF adds meaning on top rather than a keyword nothing else
knows. And a question's whole life is to stop being one: it gets answered and becomes a rule or a
scenario, so it has to sit where that answer will be written, two characters from being deleted.

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

## Where to go next

- [Acting reference](acting.md) — doing something to what this step provisioned.
- [Assertions reference](assertions.md) — claiming something about it afterwards.
- [Fixtures reference](fixtures.md) — the pytest fixtures this plugin generates.
- [How to add a scenario](../how-to/add-a-scenario.md) — this surface, used.
- [Life of a run](../explanation/life-of-a-run.md) — what this step sets in motion.
- [Catalog reference](catalog.md) — the nodes the step resolves against.
