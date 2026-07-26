# About the model

ATF has a small vocabulary, and it uses those words in exactly one way. The whole design follows
from a single sentence:

> A **resource** is *used by* a **test** that *covers* a **spec**. A **fixture** is *used by* a
> **test**.

Getting this vocabulary straight is most of understanding ATF, because each word names something the
framework treats as a distinct kind of thing — with its own file format, its own page in the
cockpit, and its own reason to change.

## The vocabulary

A **resource** is one entity a test needs in order to be meaningful: an account, a subscription, a
feed. It is a node in the catalog, and it names an instance — `accounts.primary`, not "an account".
A **resource type** is the kind — `account` — declared once, with many instances beneath it.

A **spec** is a behaviour, written in Gherkin, in the language of the domain rather than the
implementation. It says what should be true, not how to check it.

A **test** is what pytest collects: one per scenario, or one per row of an `Examples` table. Tests
are not written; they are the mechanical consequence of a spec.

A **fixture** is what a test builds on. Some are yours — an HTTP client, a clock. Others ATF
generates, one per resource type.

An **adapter** knows how to `find`, `create` and `delete` resources in one backend. It is the only
place that knows a backend exists.

The **context** is the per-scenario scratchpad. Steps write to it and read from it; it is the only
channel between them.

The **materializer** is the engine that turns a resource declaration into a real one — it walks the
dependency graph and calls the adapters. The **cockpit** is the web app that renders all of the
above. Neither is something you write; both are things you use.

## Why the relationships matter more than the parts

Most test frameworks have fixtures and tests. ATF adds resources and specs, and the value is not in
having four things instead of two — it is that the edges between them are known to the framework.

Because ATF knows which resources a spec names, it can answer questions no ordinary suite can:

- Which tests depend on this account? (If I break it, what goes red?)
- Which resources does no spec exercise? (What am I maintaining for nothing?)
- Which specs have no covering test? (What did I describe but never check?)

That is what the cockpit is: a rendering of those edges. It is not a test runner with a web page
bolted on; it exists because the model has edges worth looking at.

The edges are also why the catalog is not just a fixtures file with extra steps. A fixture is a
function — you can only find out what it does by running it. A resource is data, so ATF can read the
whole graph without executing anything, before deciding what to build.

## How a scenario becomes a run

Consider:

```gherkin
Scenario: A project belongs to its account
  Given the account "primary"
  And the project "alpha"
  When I list the projects of the account
  Then the project "alpha" is listed
```

Nothing here mentions creating an account. The first two lines *declare* what must exist. When the
test runs, ATF resolves `project` + `alpha` to the node `projects.alpha`, walks its `depends_on`
edges to find `accounts.primary`, orders them dependency-first, and asks the adapter for each in
turn: does this exist? If not, create it. The account's real identity is substituted into the
project's body before the project is created.

Then the last two lines run — ordinary test code, calling your system, asserting on the result.

The division of labour is deliberate. The `Given` lines are the framework's job, and they are
identical in every suite. The `When` and `Then` lines are yours, and they are the only place your
domain knowledge lives.

## Why there is one provisioning step and not one per type

ATF could generate `Given the account "..."`, `Given the project "..."` and so on. It does not: there
is a single step, `Given the {resource_type} "{name}"`, that captures the type as a parameter.

Partly this is forced. pytest-bdd names each step's fixture after the function that defines it, so
generated per-type steps collide and go undiscovered. But the constraint points at something true:
provisioning is *one* behaviour parameterised by type, not many behaviours that happen to look
alike. Adding a resource type should not add framework surface, and with one generic step it does
not — the catalog grows, the step count stays at one.

Per-type *fixtures* are a different matter, and those ATF does generate. A fixture named `account`
is discoverable by `pytest --fixtures`, injectable into a plain test, and visible in the cockpit. It
is a real thing a test can depend on; a step is not.

## What ATF deliberately does not define

The record an adapter returns is passed to your steps untouched. When a step reads
`context.account["email"]`, that field name is a contract between the suite and its own backend.
ATF neither defines nor validates it, and it never will — the moment the framework has opinions
about record shape, it stops being generic and starts being a client for one system.

The same restraint runs throughout. Nothing in ATF names a product, a domain, a URL or a secret.
Everything project-specific arrives through exactly three seams: the **adapters**, the
**catalog and specs**, and the **manifest**. If you find yourself wanting to change the framework to
accommodate your system, one of those three seams is the place — and if none of them fits, that is a
bug in the seams, not a reason to fork the engine.

## Where to go next

- [About declarative catalogs](why-declarative-catalogs.md) — why resources are data.
- [About lifecycles](lifecycles.md) — why some resources persist and others do not.
- [Specs and fixtures reference](../reference/specs-and-fixtures.md) — the exact surface.
