# Work out why it is red

Take a failing suite from red to a named cause. Work the steps in order; each one either answers the
question or hands you to the next.

## 1. Read the failing line

The failing line is a Gherkin sentence, not a traceback. Read it first.

```text
FAILED specs/lists.feature:31  completing a task

  Then the task "laundry" field "done" is "1"
    field "done" is "0", expected "1"

  Given the todo_list "groceries"
  Given the task "laundry"
  When I complete the task "laundry"
> Then the task "laundry" field "done" is "1"

  holding
    primary    Owner     email=primary@example.com
    groceries  TodoList  slug=groceries  owner=primary
    laundry    Task      slug=laundry    todo_list=groceries
    result     exit_code=0  output="ok"

  environment  staging
  run          2026-08-04 09:12  #418
```

The sentence says what was claimed. The line under it says what was true instead.
[Every failure names your sentence](../explanation/every-failure-names-your-sentence.md) sets out what
that block must contain — reach for it when one of your own steps prints less.

Two failures look alike and are not:

- An **assert** failed — the product did something else.
- An **arrange** step failed — the failing line is a `Given`, not a `Then`, and the test never got as
  far as claiming anything. Skip to step 6.

## 2. Read the steps above and below

Above, `When I complete the task "laundry"` ran and reported `exit_code=0`. The action succeeded and
the field did not change: a product bug, so look at `complete`, not the test.

Had the failing line been the first `Then` after several `When`s, you would not know which action was
at fault. Give each result a name (`as "first"`) and claim after each one.

## 3. Look at what the test was holding

`holding` lists every resource in scope with its [recognised](../reference/arrange.md#recognition)
fields, plus every named result. It catches three things.

- **The wrong instance.** `owner=primary` where the scenario meant a fresh one, because the name
  resolved to something the scenario had already arranged.
- **A factory-built resource where you expected a declared one.** A plain test asking for
  `owner: Owner` gets whatever the [factory](../reference/arrange.md#factory) made, with a faked
  email. A claim assuming `primary@example.com` is the wrong claim.
- **A stale result.** `result` holding an earlier `When`'s output because the later one never ran.

## 4. For an interface failure, open the screenshot and the trace

A failing [interface claim](../reference/assert.md#interface-claim) writes both:

```text
FAILED specs/checkout.feature:14  paying for a list

  Then the words "Payment received" are showing
    not showing; the page shows "Card declined"

  screenshot  .atf/artefacts/418/checkout-14.png
  trace       .atf/artefacts/418/checkout-14.trace.zip
```

The screenshot answers what it looked like. The trace answers what happened before that, step by
step, with the network and the console. In the editor both open from the failing step; from CI they
are in the uploaded artefacts — see [Run ATF in CI](run-atf-in-ci.md). `.atf/artefacts/` holds only
what a run produced ([Why there is no state file](../explanation/why-there-is-no-state-file.md)).

## 5. Ask whether it is flaky

A test is flaky if it has passed and failed lately without the code changing. That is a question
about [history](../reference/the-record.md#history), and it needs CI's runs as well as yours:

```sh
atf import-run staging atf-run.json
atf edit
```

The editor shows each test's recent outcomes against the commits they ran on. Read the pattern.

Failing since one commit, on every run since, is a real failure — go to that commit. Passing and
failing on the *same* commit is a flake, because nothing about the product changed between the two.
Failing only in CI and never locally is an environment difference rather than a flake: compare
`atf status` in both. Failing only when the whole suite runs is order-dependence, and that is step 8.

Check step 8 before chasing a flake through the product. Most flakes are residue.

## 6. When the arrange failed, not the claim

ATF creates what is absent, and a resource it cannot create **fails the test that asked for it**. The
reason names the resource rather than a field:

```text
FAILED specs/plans.feature:6  a plan applies to a list

  Given the plan "team"
    plan "team" is absent, and this run could not make it
    when_absent="require" — the environment's job
    environment  production

  holding
    groceries  TodoList  slug=groceries  owner=primary
```

No claim was made, so nothing about the product is implicated. Either the environment was not seeded,
or it is [not mutable](configure-an-environment.md#mutable) and something expected ATF to write to
it. Confirm from outside the run:

```sh
atf status production
```

`absent` means a system answered that the resource is not there. `unreachable` means it did not
answer at all — every test against it is noise until it does. See
[Require something you cannot create](require-something-you-cannot-create.md) for the declaration
that produces this failure deliberately.

### Blocked is a prediction, and only that

The editor marks a test **blocked** before you run it: the graph shows a resource it needs is absent
in an environment that may not be written to. No run ever records `blocked`; a run records `failed`,
with the resource named. If the two disagree, the run is right.

## 7. Ask how long it has been failing

The [verdict](../reference/the-record.md#verdict) folds a test's outcomes: `passing`, `failing`,
`skipped`, `never run`. The first run where it turned is on the test in the editor, and `atf docs`
carries it into the rendered specs.

- Failing since this morning, and something shipped this morning — that is your commit.
- Failing for three weeks — the code that broke it is long merged. Bisect the product rather than
  read it.
- `never run` — it was not selected. Check `--select` and `--tag`
  ([Run only what a change touched](run-only-what-a-change-touched.md)).

## 8. When the failure is in a different test from the cause

A test fails because an earlier test left the environment changed. The failing test is innocent and
its `holding` block looks correct: the declaration is correct and the environment is not.

Residue comes from [persistent scope](make-something-fresh-for-each-test.md), the default. When a
test **mutates** a persistent resource — completes a task, deletes a list, marks a plan used — every
later test that assumed the declared state runs against something else, and so does every later run.

### The two-consecutive-runs check

Run the suite twice against the same environment, changing nothing in between:

```sh
atf run --env staging
atf run --env staging
```

One green run says nothing. A failure that appears only in the second run is residue.

Reconciliation absorbs some of this and not all. A declared field that drifted is put back on the
second run; a field nobody declared is left as the first run left it. Residue that survives two runs
is almost always in a field the declaration never mentioned.

Sharpen it with the environment's own answer:

```sh
atf status staging
atf run --env staging
atf status staging
```

Anything that changed between the two `status` calls is what the run left behind.

### Confirming which test did it

```sh
atf run --failed
```

A test that passes alone and fails in a full run is order-dependent — confirmed. Bisect by tag or by
`--select` until one other test reproduces it. The culprit mutates the shared resource, and it is
usually one the failing test shares a `Given` with.

### The fix

Where a test mutates a shared resource, give it
[its own, per test](make-something-fresh-for-each-test.md): `scope="function"`. Where only one field
is in the way, a [variation](vary-a-resource-for-one-test.md) is cheaper than a new resource. Where
the mutation is the point of the test, claim it and then restore it in the same scenario.

Do not fix it by ordering the tests. An order that works is a fact about today's suite, and the next
test somebody adds breaks it silently.

## Where to go next

- [Make something fresh for each test](make-something-fresh-for-each-test.md) — the scope that ends
  most residue, and what it costs per test.
- [Run ATF in CI](run-atf-in-ci.md) — getting the report and the artefacts out of the pipeline, and
  the history back in.
- [The record](../reference/the-record.md) — outcome, verdict and history, and what each can tell you.
