# About declarative catalogs

The catalog is YAML with no code in it. That is a constraint ATF imposes on itself, and it is worth
understanding why, because the alternative — writing setup as functions — is what almost every test
suite does, and it is not obviously wrong.

## The problem with setup as code

Test setup starts simple. A helper creates an account. Then a test needs an account with a project,
so the helper takes an argument. Then something needs two accounts, and one of them must already
have a subscription that expired last month, and the helper grows a keyword argument. Eventually
nobody can answer "what does this suite assume exists?" without reading every helper, and the
answer changes depending on which test ran first.

The deeper trouble is that setup code is opaque to everything except the interpreter. You cannot ask
a function what it will create without running it. You cannot draw the dependency graph. You cannot
tell which helper is dead. The knowledge is there, but only in a form that must be *executed* to be
read.

## What data buys

Making resources data trades expressiveness for legibility, and ATF takes that trade deliberately.

Because the catalog is data, ATF can load the whole graph without touching the network and know,
before doing anything: every resource that exists, what each depends on, which adapter handles it,
and which specs name it. That is what makes the rest possible — validation that reports *every*
problem at load rather than failing at the first bad call, a dependency graph the cockpit can draw,
a `status` command that answers "what exists in staging?" without provisioning anything, and the
ability to say a scenario could not run here *before* running it. See
[About the model](the-model.md).

None of those features are clever. They are all just consequences of the setup being inspectable.

There is a human argument too. A YAML node with a `represents:` line is readable by someone who does
not write Python — a QA engineer, a product manager, a new joiner on their first day. Setup encoded
as a call graph is not. If a test suite is meant to describe how a system behaves, the description
of what the system contains should be equally approachable.

## The cost, honestly

Declarative catalogs are worse at some things, and pretending otherwise would be dishonest.

They cannot express conditionals or loops. There is no "create ten of these", no "if the environment
is staging, skip this field". Every instance is written out, by hand, with a name. For a suite that
genuinely needs a hundred near-identical records, that is tedious, and ATF has no answer beyond
"write them" or "make it one resource whose adapter creates a hundred things".

They also push complexity somewhere else rather than removing it. A resource that takes three API
calls to create still takes three API calls; the calls move into an adapter. What you gain is that
the complexity is now in one named place with a defined interface, instead of spread through the
setup helpers of whichever tests happened to need it.

And they are a poor fit for genuinely dynamic data — anything whose value must be computed at run
time from the system's own state. Placeholders cover the common cases (a dependency's identity, a
date relative to now), but they are a small, fixed vocabulary, not an expression language. That
limit is intentional: the moment placeholders become Turing-complete, the catalog stops being
inspectable and every benefit above evaporates.

## Why the escape hatch is an adapter

When declaration is not enough, ATF's answer is always the same: write an adapter. Not a hook, not a
`setup.py`, not a special resource kind — an adapter.

This matters because it keeps the catalog uniform. A resource provisioned by a three-step signup
flow with a polling loop looks exactly like one provisioned by a single POST:

```yaml
visitor:
  resource: guest
  represents: An anonymous visitor, signed up and activated fresh for every run.
  body:
    nickname: visitor
```

A spec says `Given the guest "visitor"` and knows nothing about the flow. The graph still draws. The
cockpit still shows it. `status` still reports it. All the arbitrary code lives behind one interface
with three methods, and everything upstream stays declarative.

The alternative — letting arbitrary code leak into the catalog — would buy convenience once and cost
inspectability everywhere.

## The comparison worth making

This is the same trade Terraform, Kubernetes manifests and Ansible playbooks make, for the same
reason: infrastructure described as data can be diffed, validated, visualised and reconciled;
infrastructure described as a script can only be run. ATF applies that idea to the data a test suite
needs, which is infrastructure by another name.

The reconciliation loop is the same too. ATF does not track state in a file; it asks the environment
what exists, compares that to what the catalog declares, and creates the difference. That is why
running a suite twice is safe, and why `atf seed` on a half-populated environment fills the gaps
rather than failing or duplicating.

## Where to go next

- [About the model](the-model.md) — what the catalog's nodes relate to.
- [About lifecycles](lifecycles.md) — the one axis on which resources genuinely differ.
- [Life of a run](life-of-a-run.md) — the reconciliation loop, step by step.
- [How to add a resource](../how-to/add-a-resource.md) — the practical steps.
