# Keep a large suite fast

Cut what a run does, in the order that pays: run only what a change could have broken, keep records
between runs, and pay for teardown only where a test writes.

## The shortest path

```sh
atf run --select +groceries
```

That runs the tests that could have broken when `groceries` changed — the ones that name it, the
resources carrying a `TodoList` field, and the tests that name those. The edges come from
[lineage](../reference/arrange.md#lineage), so nobody maintained a map for this to work.

[Run only what a change touched](run-only-what-a-change-touched.md) covers the three forms of the
selector, `atf impact` for asking before you run, and the trade-off: the graph knows what a test
declares, not what it incidentally touches.

## Run what cannot interfere at the same time

```sh
atf run --jobs auto
```

What each test touches is read off its sentences before anything runs: a `Given` reads the resource
it names and everything that resource needs, a declared action writes the one it names, and asking
for anything not `persistent` writes it, since the test makes it and takes it away again. Two tests
where neither writes what the other touches cannot interfere, so they go at once.

A sentence whose effect nothing declares — `When I run "…"`, a browser step, a step you wrote — is
`opaque`. Those tests run alone, with nothing beside them. That is the honest half of the trade, and
it is countable:

```console
$ atf run --explain
70 tests
  10 can run beside something else, in 1 sets
  60 run alone
        41  "I run "status local"" has an effect nothing declares
        19  "I read "/api/catalogue" from the editor" has an effect nothing declares
```

That number is what declaring bought you. It goes up when a step says what it does:

```python
@when('I archive the {kind} "{name}"', effect=WRITES)
def _archive(kind: str, name: str, atf): ...
```

For CI across several machines, `--shard 2/5` takes one slice of the same layout every other shard
is slicing, and no conflict set is split across two of them.

## Persistent is the default, and that is why re-runs are cheap

`scope="persistent"` outlives the process. The first run creates `primary` and `groceries`; every
run after it finds them and moves on. Provisioning a large suite the second time is a read per
resource, not a write.

That is the single largest thing keeping a run short, and it is what you get by saying nothing. It
also means the environment accumulates, and a record a test dirties stays dirty — [Share an
environment](share-an-environment.md) names what that costs when other people are in there too.

The way to lose it is to rebuild the environment between runs. A CI job that drops the database
before every run pays full creation every time, and no scope will help. Keep the environment and let
recognition do the work.

## `scope="function"` costs a create and a delete per test

Every test that asks pays both, and pays them for the whole closure that is not longer-lived.

```python
@sqlite(table="guests", unique_by="nickname", scope="function")
class Guest:
    nickname: str
```

`Guest` is one row, so that is cheap. A function-scoped resource three fields deep is not: a `Task`
whose `TodoList` is also function-scoped, whose `Owner` is also function-scoped, is six operations
before the test does anything, multiplied by the number of tests that ask.

Use it where a test writes to the record, and nowhere else. A test that only reads can have the
persistent one. `atf impact` prints the closure, so you can see what a scope is actually buying
before you set it:

```console
$ atf impact laundry
Task laundry
  depends on
    TodoList groceries
    Owner primary
```

## Seed ahead of CI

Provision in its own step, before the gate:

```sh
atf make staging
atf run --env staging --report ctrf:atf-run.json
```

The run then finds everything. That is faster than provisioning inside the run for the same reason a
second local run is faster than the first — and a provisioning failure is reported as one, in the
step that caused it.

On an environment you seed this way, `--no-make` makes it strict:

```sh
atf run --env staging --no-make
```

Nothing is created during the run, and a test whose resource is absent fails naming it. Use it where
seeding is somebody's job and a run creating things would hide that the job did not happen.

## What actually gets slow

Two things dominate, and neither is the number of tests.

**Browser tests.** A real browser, a real page load, a real wait for a state to settle. One of these
costs more than a hundred command-line tests. Tag them and give them their own job:

```gherkin
@interface
Scenario: paying with a card
  Given the screen "checkout"
  When I click the button "Pay now"
  Then the words "Payment received" are showing
```

```sh
atf run --tag interface
```

Run everything else on every push and the interface job less often, or in parallel with it. The tag
is your suite's convention; `--tag` is repeatable and repeats are OR.

**Resources whose closure is deep.** A test asking for a `Task` asks for a `TodoList` and an `Owner`
too, because the fields say so. Persistent, that is three reads. Function-scoped, it is three
creates and three deletes. Depth is free until you make something in it short-lived, and then it
multiplies.

Everything else — collecting scenarios, compiling steps, matching phrases — happens once and does
not grow with the environment.

## Ask what a selection will run before running it

```console
$ atf run --select +groceries --dry-run
specs/lists.feature::a list shows under its owner
specs/tasks.feature::completing a task
tests/lists/test_show.py::test_show_lists_nothing_yet
```

Nothing runs, nothing is recorded, and the exit code is `0`. It is how you tell "selected nothing"
from "selected everything" before a pipeline spends ten minutes proving it.

While fixing a failure, narrow further:

```sh
atf run --failed
```

Only the tests whose last outcome in this environment's
[history](../reference/the-record.md#history) was `failed`. It selects nothing on an empty history,
so it is a loop to tighten with, not a gate.

## When it goes wrong

**A selected run is green and a full run is red.** The difference is a dependency nothing declared.
Find it and add the field; it is usually a bug in the test rather than in the product. Keep running
everything on the main branch — the full run stays the final word.

**The second run is as slow as the first.** Something is removing what the first run made. Either the
environment is rebuilt between runs, or resources are function-scoped that did not need to be. Check
with `atf status` immediately after a run: persistent records should read `present`.

**The suite got slower after one declaration changed.** Look for a `scope="function"` added to
something with dependents. Every test downstream of it now pays for the whole closure.

**Exit `2`, `unknown selector "grocerys"`.** The name matched no resource and no type, so the run
never started. A typo cannot go green.

**A green run that selected no tests.** The name matched a real resource that nothing depends on.
That is an answer, so it exits `0`. Use `--dry-run` when a pipeline needs to tell the two apart.

## Where to go next

- [Run only what a change touched](run-only-what-a-change-touched.md) — selection and `atf impact` in
  full, including where the graph does not see an edge.
- [Make something fresh for each test](make-something-fresh-for-each-test.md) — the three lifetimes,
  and how to prove teardown happened before you trade it away.
- [Run ATF in CI](run-atf-in-ci.md) — where the seeding step, the tags and the report belong in a
  pipeline.
