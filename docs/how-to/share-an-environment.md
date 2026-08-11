# Share an environment

Point several people and a CI pipeline at one staging environment, and keep their runs out of each
other's way.

## The shortest path

Seed it once, in one place, and let every run find what is already there.

```sh
atf make staging
```

```sh
atf run --env staging
```

`atf make` creates what is absent and updates what differs. After it, every test in every run does
the same thing to the environment — find — and finding is safe to do at the same time as anybody
else.

## Why this mostly works already

[Recognition](../reference/arrange.md#recognition). Every suite declares `Owner` as recognised by
`email`, so `primary@example.com` is the same owner to everyone. The first person to run makes it;
everyone after that finds it. Nobody gets a second one.

```python
@todo.owner()
class Owner:
    email: str


primary = Owner(email="primary@example.com")
```

Nothing is remembered between runs to make that true. ATF asks the environment what it holds, every
time, and acts on the difference — so a colleague's run, a CI run and a row somebody inserted by
hand are all the same answer to the same question. [Why there is no state
file](../explanation/why-there-is-no-state-file.md) is the long form; the short form is that a
shared environment has no shared file to get out of step with.

## What `persistent` means here

`persistent` is the default [scope](../reference/arrange.md#scope): the record outlives the process
and ATF never removes it. On a shared environment that is what you want. `primary` and `groceries`
are made once, on somebody's first run, and every run after that finds them in the state the
declaration describes.

Name the cost. A persistent record is shared mutable state:

- A test that writes to `groceries` leaves it written for the next person. Nothing rebuilds it.
- Fields you **declared** are brought back into line on the next run, because provisioning is
  reconciliation. Fields you did not declare are left exactly as the last test left them.
- Two people changing the same declared field in `resources.py` and running in turn means the last
  run wins, quietly.

Declare the fields that matter to a test, and the environment repairs itself.

## The resource that must not collide

Where a test writes to a record, give that record its own lifetime and its own name.

```python
@sql.row(table="guests", unique_by="nickname", scope="function")
class Guest:
    nickname: str

    @classmethod
    def factory(cls) -> Self:
        return cls(nickname=faker.user_name())
```

`scope="function"` builds it before the test and removes it afterwards. The factory is the half that
makes it safe to share: a fixed `nickname` means two runs against staging fight over one row, and a
generated one means they never meet. Scenarios say `Given a guest`, and each run gets its own.

This costs a create and a delete per test. Spend it on the records tests write to, not on the
records tests read.

## Seed ahead of a run

Make `atf make` somebody's job rather than every run's accident — a deploy hook, a nightly job, or
its own CI step before the gate.

```sh
atf make staging
atf run --env staging --report ctrf:atf-run.json
```

Two things follow. A provisioning failure is reported as a provisioning failure, in its own step,
instead of arriving later as a red test. And the runs that follow only ever find, which is the
property that makes a shared environment tolerable at all.

Add `--dry-run` where you want to see what provisioning would create and change before it happens.

```console
$ atf make staging --dry-run
would make    TodoList  groceries    slug=groceries
would change  Owner     primary      email: "old@example.com" → "primary@example.com"
```

## Make what nobody should write to unwritable

`mutable` is false unless stated, so an environment nobody added the line to already refuses every
create and delete.

```yaml
environments:
  staging:
    mutable: true
    sql: { path: $STAGING_DB }

  production:
    sql: { path: $PRODUCTION_DB }
```

Against `production`, `atf make` refuses and exits `2`, no `scope="function"` resource is built or
removed, and a test naming an absent resource fails naming it rather than creating it. That is the
protection: it is a property of the environment, not a convention people remember.

Inside a shared environment, the same idea applies per resource. Anything the environment owns and
nobody's test should create — a plan, a region, a feature flag — is declared
[`when_absent="require"`](require-something-you-cannot-create.md):

```python
@sql.row(table="plans", unique_by="code", when_absent="require")
class Plan:
    code: str
```

A missing plan then fails the test naming the plan, instead of one person's run inventing a plan row
that everyone else's assertions have to live with.

## What this does not solve

**Two runs creating the same resource at the same moment can race.** Both ask, both are told nothing
is there, both create. What happens next belongs to the system: a unique constraint raises and one
run goes red, or there is no constraint and you have two rows.

**ATF holds no lock and no queue.** There is no coordination between processes, and adding one would
mean a shared piece of state that the whole design exists without.

The mitigation is the shortest path at the top of this page: seed with `atf make` before the runs
start, so no run is ever the one creating. Where a resource genuinely cannot be seeded ahead —
because each test needs its own — give it `scope="function"` and a factory, so the two runs are not
asking for the same record in the first place.

Between those two, what is left racing is the case where somebody adds a new declaration and two
people run before anybody has seeded it. Run `atf make staging` after a change to `resources.py`.

## When it goes wrong

**A create fails on a unique constraint.** Two runs created at once. Seed first; the second run then
finds.

**`Then the environment has 2 todo_list` fails.** A claim about the whole environment is not a claim
you can make about a shared one — somebody else's run put a third list there. Claim the records you
care about, one sentence each.

**`atf status staging` says something you seeded is absent.** A `function`-scoped resource is
supposed to read that way between runs. For anything else, check which environment `atf make` was
given — it takes one as an argument and never falls back to `default_env`.

**Exit `2`, `refused: environment "staging" is not mutable`.** No `mutable: true`. Add it, or declare
the resources `when_absent="require"` and let whoever owns the environment seed it.

**A field changes under someone mid-afternoon.** Somebody edited `resources.py` and ran; provisioning
reconciled the declared field for everyone. That is the mechanism working. Treat `resources.py` as
shared configuration of a shared place, and review changes to it.

**Exit `2`, `unreachable: todo`.** The environment did not answer. Nothing was tested, and it is not
a test failure — see the three states in [The ground](../reference/the-ground.md#environment).

## Where to go next

- [Run ATF in CI](run-atf-in-ci.md) — where the seeding step and the gate belong in a pipeline, and
  the exit codes it reads.
- [Make something fresh for each test](make-something-fresh-for-each-test.md) — `scope="function"`,
  its teardown, and how to prove the teardown happened.
- [Configure an environment](configure-an-environment.md) — `mutable`, secrets through variables, and
  why a new environment starts unable to change anything.
