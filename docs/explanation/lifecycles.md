# About lifecycles

Every resource in an ATF catalog is either **persistent** or **ephemeral**. It is a one-word choice
with consequences that reach into how your suite behaves on its second run, whether scenarios can
interfere with each other, and how much garbage accumulates in your test environment.

## The two kinds

A **persistent** resource is found-or-created and then left alone. ATF asks the adapter whether it
exists; if it does, that record is used as-is, and if it does not, it is created. Nothing deletes
it. The next run finds it and reuses it. This is the default, and most resources should be this.

An **ephemeral** resource is built fresh every time and deleted when the scenario that used it ends.
ATF never looks for an existing one — the adapter's `find` returns `None` by definition — so every
run creates a new instance, and the plugin's teardown removes it afterwards.

## Why persistence is the default

The instinct from unit testing is that every test should build its own world and destroy it
afterwards. That instinct is right when the world is a Python object and wrong when it is a row in
someone else's database.

End-to-end resources are expensive. Creating an account may fan out to a billing system, a search
index, and an email provider. Doing that for every test turns a fast suite into a slow one, and
turns a flaky downstream service into a flaky test suite. Reuse is what keeps end-to-end testing
affordable.

Reuse also makes failures legible. When a test fails against `accounts.primary`, that account is
still there afterwards, with its real identity, and you can go and look at it. A resource that
deletes itself on the way out takes the evidence with it.

The cost is that persistent resources accumulate state. Which brings us to the rule that matters
most.

## A scenario that mutates a persistent resource must own it

This is the one lifecycle mistake that will bite you, and it does not bite immediately — it bites on
the *second* run.

Suppose one scenario asserts that a task is open, and another completes that same task. Both pass
the first time, because the environment starts clean. On the second run the task is already
complete, and the first scenario fails. The suite has become order-dependent and
history-dependent, which is the specific failure mode end-to-end suites are notorious for.

The fix is not to make the resource ephemeral. It is to give the mutating scenario a resource of its
own — one task the assertions read, a second the completion spec closes. Two nodes instead of one,
and the coupling is gone.

Or one node and a line in the spec:
[`Given a fresh task "laundry"`](../reference/specs-and-fixtures.md#fresh) says the same
thing where only one scenario needs it, without the catalog carrying a node that exists for a
single test.

The catalog makes this cheap on purpose:
when adding a resource costs almost nothing, "give the mutating test its own" stops being a
discipline you have to remember and becomes the obvious move.

**Or say it in the scenario.** A second node is right when the two resources mean different things
and both are worth naming. When it would only ever be "the same thing, but mine", the scenario says
so and the catalog keeps one node:

```gherkin
Given a fresh task "laundry"
When I complete the task "laundry"
Then the task "laundry" field "done" is "true"
```

That instance is created rather than found, belongs to this scenario, and is deleted with it — the
ephemeral behaviour, borrowed for one scenario, without the type giving it up for everyone else. See
[one to yourself](../reference/specs-and-fixtures.md#fresh).

The general rule: **read-only scenarios can share a resource; a scenario that changes one needs its
own.** If you cannot tell whether a scenario mutates something, it does.

## When ephemeral earns its keep

Choose ephemeral when the resource cannot meaningfully be reused:

- **Single-use things.** A signup token, an invitation, a password-reset link. Reusing a consumed
  token is not a saving; it is a bug.
- **Things whose identity is the point.** An anonymous visitor, a fresh session. If the test is about
  what happens to a *new* one, an old one will not do.
- **Things that would collide.** A resource with a unique constraint that each run must satisfy
  differently.

Ephemeral resources are also the natural fit for multi-step provisioning — the sign-up-then-activate
flows that live in a custom adapter. Those tend to be exactly the single-use things above.

## What teardown does and does not promise

Teardown is **best-effort**. ATF calls the adapter's `delete` for each ephemeral resource the
scenario provisioned, and if that call fails, the error is logged and the run continues. A failing
teardown never fails a test.

This is deliberate. A test that passed has told you something true about your system; letting a
cleanup error overturn that verdict would mean a broken deletion endpoint reports itself as a
failure of unrelated behaviour. The trade is that ephemeral resources can leak when a backend
misbehaves, which is a mess you can see and clean up, rather than a red build you have to
investigate.

Note also what teardown does *not* cover: resources created by `atf seed`, or by the cockpit, are
not attached to any scenario, so nothing deletes them. This is why `atf seed` skips ephemeral
resources entirely when seeding a whole catalog — seeding a resource whose whole point is to be
temporary would create an orphan nothing owns.

## The third state: reference

There is a related choice that is not a lifecycle but is often confused with one. A `reference`
resource is one ATF may look up but must never create — a plan, a feature flag, a country code,
anything the environment ships with. If it is absent, that is an error worth stopping for, because
it means the environment is not configured the way the suite assumes.

Reference resources are typically persistent, but the two settings are orthogonal: `mode` says
whether ATF may create it, `lifecycle` says whether it is reused.

## Choosing, in one line each

- Reused across runs, and no scenario changes it → **persistent** (the default).
- Reused across runs, but one scenario changes it → **persistent**, and give that scenario its own
  instance: a second node when it is worth naming, `Given a fresh …` when it is not.
- Meaningless to reuse, or must be new each time → **ephemeral**.
- Must already exist, and ATF should never create it → **persistent** with `mode: reference`.

## Where to go next

- [How to add a resource](../how-to/add-a-resource.md) — where these keys go.
- [Catalog reference](../reference/catalog.md#lifecycle) — `lifecycle` and `mode` in full.
- [Life of a run](life-of-a-run.md#tear-down) — when teardown happens, and what it skips.
- [Glossary](glossary.md) — `persistent`, `ephemeral` and `reference mode` in a sentence each.
- [About the model](the-model.md) — how resources relate to scenarios and tests.
