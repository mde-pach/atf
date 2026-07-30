# Glossary

Every word ATF uses in a particular way, defined once. The cockpit links here: each term it renders
as a chip carries the same one-sentence definition, and its "read more" points at the matching
heading below.

Each entry is a definition and a pointer, not an essay. Where a term deserves more, the last line
says which page treats it properly.

| Term | In short |
|---|---|
| [Resource](#resource) | One thing that must exist before a test is meaningful |
| [Resource type](#resource-type) | The kind a resource is an instance of |
| [Scenario](#scenario) | A behaviour, written in Gherkin |
| [Test](#test) | What pytest collects from a scenario |
| [Catalog](#catalog) | The YAML declaration of every resource |
| [Collection](#collection) | The file a resource is declared in |
| [Adapter](#adapter) | The code that talks to one backend |
| [System](#system) | Which backend a resource type lives in |
| [Provision](#provision) | Make a resource exist in an environment |
| [Closure](#closure) | A resource plus everything it depends on |
| [Natural key](#natural-key) | How ATF recognises a resource that already exists |
| [Identity field](#id-field) | Where the record carries the resource's identity |
| [Reference mode](#reference-mode) | Look it up, never create it |
| [Ephemeral](#ephemeral) | Built fresh each run, deleted afterwards |
| [Persistent](#persistent) | Found or created, then left in place |
| [Placeholder](#placeholder) | A `${...}` value resolved at provisioning time |
| [Provider](#provider) | A named source of generated values |
| [Environment](#environment) | One deployment the suite can run against |
| [Mutable environment](#mutable-env) | An environment ATF is allowed to change |
| [Context](#context) | The per-scenario scratchpad |
| [Fixture](#fixture) | What a pytest test builds on |
| [Run](#run) | One execution of a set of tests |
| [Blocked](#blocked) | Names a resource that is absent here |
| [Flaky](#flaky) | Has both passed and failed lately |

## Resource {#resource}

One thing that must exist before a test is meaningful — an account, a list, a subscription.

A resource is a node in the catalog, and it names an *instance*: `owners.primary`, not "an owner".
It is declared as data, never as code.

Treated properly in [About the model](the-model.md) and the
[catalog reference](../reference/catalog.md#instance-files).

## Resource type {#resource-type}

The kind a resource is an instance of — `owner`, `todo_list`, `task`.

A type is declared once, in `catalog/resources.yaml`, with the [system](#system) that provisions it
and whatever that system's [adapter](#adapter) needs. Each type becomes a word your scenarios can
use and a pytest [fixture](#fixture) of the same name.

See the [catalog reference](../reference/catalog.md#resource-types).

## Scenario {#scenario}

A behaviour written in Gherkin, in the language of the domain rather than the implementation.

A scenario declares the [resources](#resource) it needs with `Given the <type> "<name>"`; ATF makes
them exist before the steps run. It says what should be true, not how to check it.

See the [specs and fixtures reference](../reference/provisioning.md#the-provisioning-step).

## Test {#test}

What pytest collects from a scenario: one test per scenario, or one per row of its `Examples` table.

Tests are not written. They are the mechanical consequence of a scenario, which is why the cockpit
shows them beneath the scenario they cover rather than as a list of their own.

See [About the model](the-model.md).

## Catalog {#catalog}

The directory of YAML files declaring every resource your suite can ask for, and how they depend on
each other.

Nothing in it is executable, so ATF can read the whole graph — and validate it — without touching
the network.

See the [catalog reference](../reference/catalog.md) and
[About declarative catalogs](why-declarative-catalogs.md).

## Collection {#collection}

The file a resource is declared in. `catalog/owners.yaml` gives every node in it an id beginning
`owners.`.

A collection is a filing choice, not a property of the resource: it decides node ids and nothing
else. Two resources of the same type may live in different files, and one file may hold several
types.

See the [catalog reference](../reference/catalog.md#directory-layout).

## Adapter {#adapter}

The code that knows how to `find`, `create` and `delete` resources in one backend.

An adapter is the only place in a suite that knows a particular system exists. Two ship built in —
`rest` and `reference` — and anything else is one class with three methods.

See the [adapter SPI reference](../reference/adapter-spi.md) and
[How to add an adapter](../how-to/add-an-adapter.md).

## System {#system}

The backend a resource type lives in, and therefore which adapter handles it.

A system is named on the type (`system: rest`) and configured per [environment](#environment), so
one adapter serves dev and staging with different URLs and credentials. A system with no settings in
an environment reports its resources as `unsupported` there.

See the [manifest reference](../reference/manifest.md#environments-name).

## Provision {#provision}

Make a resource exist in an environment: look for it, create it if it is not there, and do the same
for everything it depends on first.

Provisioning is idempotent by design — the second pass finds what the first made. It is what the
`Given` step does, what `atf seed` does, and what the cockpit's **Provision** button does.

Walked through step by step in [Life of a run](life-of-a-run.md).

## Closure {#closure}

A resource plus everything it depends on, transitively.

Provisioning anything provisions its whole closure, dependencies first. Asking for
`lists.groceries` therefore also gets you `owners.primary`, whether or not you named it.

See [Life of a run](life-of-a-run.md#walk-the-dependencies).

## Natural key {#natural-key}

The field — or fields — by which ATF recognises a resource that already exists.

The natural key is what makes a re-run reuse a resource instead of duplicating it. Choose something
stable and unique: an email, a slug, an external reference. Get it wrong and each run creates
another copy.

See the [catalog reference](../reference/catalog.md#natural_key).

## Identity field {#id-field}

The field of the backend's record that carries the resource's identity — `id` unless the type says
otherwise.

It is what a [placeholder](#placeholder) resolves to: `${owners.primary.id}` means "that resource's
identity", read through *its* identity field, whatever it is called.

See the [catalog reference](../reference/catalog.md#id_field).

## Reference mode {#reference-mode}

The resource must already exist in the environment; ATF may look it up but will never create it.

Plans, feature flags, country codes — things the environment ships with. If one is missing, that is
worth stopping for: it means the environment is not configured the way the suite assumes.

See the [catalog reference](../reference/catalog.md#mode) and
[About lifecycles](lifecycles.md#the-third-state-reference).

## Ephemeral {#ephemeral}

Built fresh for every run and deleted when the scenario that used it ends.

An ephemeral resource is never looked up and never seeded — reusing one would defeat its purpose.
Signup tokens, invitations, anonymous sessions.

See [About lifecycles](lifecycles.md#when-ephemeral-earns-its-keep).

## Persistent {#persistent}

Found or created, then left in place for the next run.

This is the default, and what keeps end-to-end testing affordable: creating an account may fan out
to a billing system, a search index and an email provider, and doing that per test is what makes
suites slow and flaky.

See [About lifecycles](lifecycles.md#why-persistence-is-the-default).

## Placeholder {#placeholder}

A `${...}` value in a resource body, resolved at provisioning time.

Two forms, and only two: `${<node id>.id}` for a dependency's real identity, and `${now+Nd HH:MM}`
for a timestamp relative to now. Anything else is rejected when the catalog loads.

See the [catalog reference](../reference/catalog.md#placeholders).

## Environment {#environment}

One deployment the suite can run against — dev, staging, production — with its own adapter settings
and secrets.

Every answer ATF gives is about one environment at a time: a resource is present *in dev*, a
scenario passed *against staging*.

See the [manifest reference](../reference/manifest.md#environments).

## Mutable environment {#mutable-env}

An environment the manifest allows ATF to change, by listing it under `mutable_envs`.

Everywhere else, provisioning and running are refused: `atf seed` exits 2 and the cockpit renders
those controls disabled. Leave production off the list and the guard is structural rather than a
matter of discipline.

See the [manifest reference](../reference/manifest.md#mutable_envs).

## Context {#context}

The per-scenario scratchpad, and the only channel between steps.

The provisioning step writes each record onto it — `context.owner`, `context.task` — and your own
steps read them back. Everything on it other than the records and `_ephemeral` belongs to your
suite. Anything a step writes there is a **slot**, and a slot can be asserted on by name:
`Then the result contains …` names the one ATF suggests calling `result`, and a scenario doing two
things names each of them instead — otherwise only the second would survive.

It remembers what it is holding. Each attribute set on it gets a description — its kind, the fields
it carries, how many records there are — which is what lets the cockpit say what a scenario had
available to assert on. Descriptions never carry values, because they are written to run history.

See the [specs and fixtures reference](../reference/fixtures.md#context).

## Provider {#provider}

A named source of values that a catalog body or a step can interpolate: `${uuid}`, `${fake:email}`,
`${now+1d 09:00}`.

Registered the way an [adapter](#adapter) is, so a project plugs in whatever it needs. Values are
fresh — an expression is evaluated once per [scenario](#scenario), so a `When` that generates one
and the `Then` that checks it see the same answer, and the next scenario generates afresh.

The one place a generated value is refused is a [natural key](#natural-key) ATF has to look up
again: a value that changes every run never matches, so every run would create another record.

See the [providers reference](../reference/providers.md).

## Fixture {#fixture}

A pytest fixture: something a test declares and pytest builds for it.

ATF generates one per [resource type](#resource-type), so a plain pytest test can ask for a catalog
resource directly, and provides a handful of its own (`context`, `materializer`, `env`,
`client_config`). The rest are yours.

See the [specs and fixtures reference](../reference/fixtures.md#fixtures).

## Run {#run}

One execution of a set of tests against one environment.

Runs are recorded under `<suite root>/.atf/runs/`, so the cockpit still knows the last outcome and
when it happened after a restart — and can tell when a scenario has become [flaky](#flaky). A run
from CI can be added to the same store with `atf import-run`.

See the [cockpit reference](../reference/cockpit.md#run-history) and
[CLI reference](../reference/cli.md#atf-import-run).

## Blocked {#blocked}

The scenario names a resource, somewhere in its closure, that is in a state **running cannot fix**:
no adapter for its system here, an adapter that raised while looking it up, or a missing
[reference-mode](#reference-mode) resource ATF is never allowed to create.

An *absent* resource is not a blocker. Naming a resource in a scenario is precisely what makes ATF
create it, so absent-and-creatable is information — "running this provisions three resources" — not
a warning.

Blocked is a prediction rather than an outcome: ATF knows what a scenario names and what state each
of those is in, so it can say a run would not get to its first `When` before you click Run.

The word is also used for a resource that was not attempted because something it depends on failed
to provision — see the [CLI reference](../reference/cli.md#seed-keep-going).

## Flaky {#flaky}

A test that has both passed and failed across recent runs, without the suite changing in between.

Its verdict cannot be trusted in either direction, so the cockpit flags it rather than colouring it
green or red. The flag comes from the persisted [run](#run) history.

See the [cockpit reference](../reference/cockpit.md#run-history).

## Where to go next

- [Life of a run](life-of-a-run.md) — the sequence these words describe, in order.
- [About the model](the-model.md) — why the relationships between them are the point.
- [Catalog reference](../reference/catalog.md) — the keys that carry them.
