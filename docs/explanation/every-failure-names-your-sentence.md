# Every failure names your sentence

A test framework is used twice: once when it is green, once when it is red. Only the red run has to
be read, so ATF treats it as a constraint on the design rather than a feature to add later. Whatever
ATF prints when a run goes red must name the sentence you wrote — not the framework's internals, not
a frame in somebody else's file.

## What the constraint forced

**A claim names both sides and their kinds.** When

```gherkin
Then the result field "exit_code" is "0"
```

fails, the message carries what was expected, what was found, and the kind of each. `"0"` and `0` are
the same three characters in a diff and a different afternoon of debugging.

**An unknown field lists the fields the record does carry.** Ask for `field "name"` on a record that
has `id`, `slug` and `owner_id`, and the failure names both. Not `KeyError: 'name'`. Records are read
through the claim library rather than by indexing, because indexing raises a good exception for a
programmer and a poor one for a person reading a scenario, and the second reader is the one stuck.

**A failure is shown on its Gherkin line.** The steps above it are shown as passed, the steps below
as skipped, in the order you wrote them. The traceback is still available; it is not the first thing,
because in a five-step scenario the useful fact is which of the five, and a stack does not say.

**An interface failure carries a screenshot and a trace.** "The button Pay now is not disabled" is
not a diagnosis on its own. The state of the page at the moment of the claim is, and it is gone the
instant the browser closes.

**A failure about a resource names the resource, not the assert that came after it.** A resource that
is missing gets created. One that *cannot* be created — a `when_absent="require"` row the environment
does not have, an [immutable](../reference/the-ground.md#may-be-changed) environment, a system that
is `unreachable` — fails the test then and there, naming the thing it could not get. There is no
blocked state: a run has three outcomes, and a fourth would put a word in every report to explain a
case most people never hit. What it must not do is fail with a red assert about a value it never had
the chance to look at.

**Blocked survives only as a prediction.** The editor can say, before a run, that these tests are
about to fail for a reason it can already see. That is the same constraint applied one step earlier.

**An exit code is not a diagnosis, so it does not pretend to be one.** `0` passed, `1` a test failed,
`2` the run never started. Deliberately coarse, because a number that encodes a reason is a number
somebody has to look up, and the reason belongs in the message. Anything that needs to branch on why
reads the structured code from `--json`.

## What it forced further back

Two decisions that look like they belong elsewhere are decisions about the red path.

`claims` is a public library. If diagnosis lived in ATF's private code, the first custom step a team
wrote would fail worse than everything around it, and the red path would decay as the suite became
more specific to that team's domain. The functions that make a built-in claim legible are the ones
you call:

```python
@then('the invoice totals "{amount}"')
def _(invoice, amount):
    claims.field_is(invoice, "total", amount)
```

[Markers](../reference/assert.md#marker) come from the same constraint. A claim should be exact about
the fields that matter and honest about the ones that cannot be predicted:

```gherkin
Then the todo_list "groceries" field "slug" is "groceries"
And the todo_list "groceries" field "id" is #uuid
```

Without markers the second line has two futures, and both are bad: it fails on every run because the
id changed, or somebody deletes it and the record stops being checked for having an id at all.
`#uuid` keeps the strict version writable — exact about the kind, silent about the value. A failure
inside a [phrase](../reference/act.md#phrase) reports the line inside the phrase as well as the
sentence that called it, because compression that hid which field went wrong would have been the
wrong trade here.

## What it costs

**A suite of scenarios diagnoses worse than unit tests when the framework itself breaks.**

A unit test that fails alone points at one function. When an adapter is misconfigured, a shared
system is unreachable, or one widely-used resource's declaration is wrong, every scenario that
depends on it goes red at once. A hundred red lines, each correctly naming its own sentence, none of
them naming the cause. Breadth is not a diagnosis.

ATF reduces this rather than removing it. `atf status <env>` answers the environment question without
running anything, and `atf check` answers the well-formedness question. Between them they turn a
hundred red lines into one sentence about a missing thing, provided you ask before you run. But a
team that has moved all of its testing into scenarios has fewer small, isolated tests to bisect with,
and that is a genuine loss. When a lot goes red at once, the first question is what changed in the
environment, not what changed in the code.

**Evidence has to be gathered before anyone knows it will be needed.** A trace cannot be started
after the failure it explains, so capture is arranged around the run and the green runs pay for the
red ones. That is why capture is part of the design rather than a plugin.

## What else was on the table

**A stack trace as the primary artifact.** It is the truthful thing, and it is truthful about the
framework rather than about the test. Declined as the *first* thing shown, kept as the last.

**`assert x == y, "a message"`** — put the burden on the person writing the test. Declined because it
is optional, which means it is absent precisely where the test was written in a hurry. A framework's
floor should not depend on discipline.

**Screenshots and traces as an opt-in plugin.** Declined because by the time you know you wanted one,
the run is over and the re-run may well be green.

**A fluent assertion library** — chained matchers with their own vocabulary. Declined on the concept
budget. Gherkin's `Then` already reads aloud, and the [claim](../reference/assert.md#claim)
vocabulary is small enough to hold in one page.

## Where to go next

- **[Work out why it is red](../how-to/work-out-why-it-is-red.md)** — this page as a procedure, for
  the morning you actually need it.
- **[One engine, two surfaces](one-engine-two-surfaces.md)** — why a pytest function and a scenario
  fail the same way.
- **[Assert](../reference/assert.md)** — every claim and marker defined once, with what each one says
  when it fails.
