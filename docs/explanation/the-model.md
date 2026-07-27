# About the model

ATF has a small vocabulary, and it uses those words in exactly one way. The whole design follows
from a single sentence:

> A **resource** is *used by* a **test** that *covers* a **spec**. A **fixture** is *used by* a
> **test**.

Getting this vocabulary straight is most of understanding ATF, because each word names something the
framework treats as a distinct kind of thing — with its own file format, its own place in the
cockpit, and its own reason to change.

Every one of those words is defined once, crisply, in the [glossary](glossary.md). This page is
about why they are separate words at all.

## Three distinctions worth holding on to

**A resource is an instance, not a kind.** `accounts.primary`, not "an account". The kind is a
[resource type](glossary.md#resource-type), declared once, with as many instances beneath it as your
specs need. Almost everything ATF does is per instance; almost everything you configure is per type.

**A scenario and a test are not the same thing.** A scenario is a behaviour, written in Gherkin. A
test is what pytest collects from it — one per scenario, or one per row of an `Examples` table.
Tests are never written; they follow. (The directory is called `specs/`, and "spec" and "scenario"
are used interchangeably for what lives in it.)

**A resource is not a fixture.** A fixture is a function: the only way to learn what it does is to
run it. A resource is data: ATF can read the whole graph, validate it, and draw it, without
executing anything. That difference is what the rest of this page is about.

## Why the relationships matter more than the parts

Most test frameworks have fixtures and tests. ATF adds resources and specs, and the value is not in
having four things instead of two — it is that the edges between them are known to the framework.

Because ATF knows which resources a scenario names, it can answer questions no ordinary suite can:

- Which scenarios depend on this account? (If I break it, what goes red?)
- Which resource types does no scenario exercise? (What am I maintaining for nothing?)
- Would this scenario even get off the ground in staging? (Or is something it needs missing?)

That is what the cockpit is: a rendering of those edges. It is not a test runner with a web page
bolted on; it exists because the model has edges worth looking at.

The edges have to be real ones. An earlier version of the cockpit also asked "which specs have no
covering test?", which sounds like the same kind of question and is not: pytest-bdd binds a test to
every scenario, so the answer was always "none" and the number could never move. A question whose
answer is fixed by construction is not worth a reader's attention, however good it looks on a
dashboard.

The same edges are why the cockpit can tell you a scenario would not get off the ground before you
run it. It knows what the scenario names and what state each of those is in — see
[readiness](../reference/cockpit.md#readiness).

## Where the line between you and the framework falls

```gherkin
Scenario: A project belongs to its account
  Given the account "primary"
  And the project "alpha"
  When I list the projects of the account
  Then the project "alpha" is listed
```

The `Given` lines are the framework's job, and they are identical in every suite: declare what must
exist, and ATF resolves, orders and provisions it. The `When` and `Then` lines are yours, and they
are the only place your domain knowledge lives.

That division is the whole bargain. You give up writing setup; in exchange you write setup as data
that something else can read. The sequence ATF runs on your behalf is walked through in
[Life of a run](life-of-a-run.md).

## Why there is one provisioning step and not one per type

ATF could generate `Given the account "..."`, `Given the project "..."` and so on. It does not: there
is a single step, `Given the {resource_type} "{name}"`, that captures the type as a parameter.

Partly this is forced. pytest-bdd names each step's fixture after the function that defines it, so
generated per-type steps collide and go undiscovered. But the constraint points at something true:
provisioning is *one* behaviour parameterised by type, not many behaviours that happen to look
alike. Adding a resource type should not add framework surface, and with one generic step it does
not — the catalog grows, the step count stays at one.

Per-type *fixtures* are a different matter, and those ATF does generate. A fixture named `account`
is discoverable by `pytest --fixtures`, injectable into a plain test, and named on the type's page in
the cockpit. It is a real thing a test can depend on; a step is not.

## Where the line on record shape falls {#record-shape}

The record an adapter returns is passed to your steps untouched. When a step reads
`context.account["email"]`, that field name is a contract between the suite and its own backend —
and it is the *suite's* contract, not the framework's.

It is tempting to state that as "ATF has no opinions about record shape", but that is drawn in the
wrong place, and it is not what ATF has ever done. `natural_key: email` names a field. So does
`id_field: uuid`, and so does every key of a body. Naming a field and having ATF read it is the
oldest thing in the catalog.

The line that actually holds is between two different acts:

> **ATF never decides what a record contains.** It requires no field to exist, infers nothing from a
> field's name, and interprets no value beyond comparing it with the one you wrote. **What it will do
> is read a field you named.**

That is why [the read-and-compare steps](../reference/specs-and-fixtures.md#read-and-compare-steps)
are not a breach of the principle: `Then the task "milk" field "done" is "false"` names the field in
the scenario, exactly as `natural_key` names one in the catalog. ATF reads `done`, compares it with
`false`, and knows nothing else about it — not that tasks have a `done`, not that `done` is a
boolean, not that a done task is finished.

The test to apply to any new feature: could the framework be pointed at an entirely different
backend without changing a line of its own code? Reading a field the author named passes. Assuming a
task has a boolean called `done` does not, and would make ATF a client for one system.

The same restraint runs throughout. Nothing in ATF names a product, a domain, a URL or a secret.
Everything project-specific arrives through exactly three seams: the **adapters**, the
**catalog and specs**, and the **manifest**. If you find yourself wanting to change the framework to
accommodate your system, one of those three seams is the place — and if none of them fits, that is a
bug in the seams, not a reason to fork the engine.

## Where to go next

- [Glossary](glossary.md) — every one of these words, defined once.
- [Life of a run](life-of-a-run.md) — the sequence the `Given` lines set in motion.
- [About declarative catalogs](why-declarative-catalogs.md) — why resources are data.
- [About lifecycles](lifecycles.md) — why some resources persist and others do not.
- [Specs and fixtures reference](../reference/specs-and-fixtures.md) — the exact surface.
