# Make something fresh for each test

Have a resource built before each test that asks for it and removed afterwards, and prove that the
removal happens.

## The shortest path

Declare it with `scope="function"`.

```python
# resources.py
from adapters.todo import todo


@sql.row(table="guests", unique_by="nickname", scope="function")
class Guest:
    nickname: str


visitor = Guest(nickname="visitor")
```

Ask for it as usual.

```gherkin
Scenario: a guest sees no lists
  Given the guest "visitor"
  When I run "todo show visitor"
  Then the result field "output" contains "no lists"
```

The record is created before this scenario and removed after it, whether the scenario passed or
failed. The next test that names `visitor` gets a new one.

## The three lifetimes

`scope="function"`
:   Made for one test, torn down when that test ends.

`scope="session"`
:   Made for one run, torn down when the run ends.

`scope="persistent"`
:   Outlives the process. **The default**, and never torn down by ATF.

`persistent` is what you get if you say nothing: the record is made once, found by
[recognition](../reference/arrange.md#recognition) on every run after that, and left behind when the
process exits. Nothing in pytest works this way, and it is what makes re-runs cheap.

`session` is for a record that must not survive the run but is too expensive to rebuild per test — a
tenant, a signed-in account. `function` is for the records tests mutate. See
[scope](../reference/arrange.md#scope) for what each value costs.

## Teardown

Removal is the system's own delete, run in reverse of provisioning order — dependents first. You
write neither it nor the ordering; the ordering follows `depends_on`.

**Teardown runs after a failing test**, so one failure does not become a run's worth of noise.

**Teardown needs a changeable environment.** `mutable` is false unless stated, and an environment that
may not be changed can neither create nor remove. See
[may be changed](../reference/the-ground.md#may-be-changed).

**Lifetimes may not invert.** A resource may depend on one that lives at least as long as it does —
`function` on `session`, `session` on `persistent`, either on `persistent`. The reverse would leave
the longer-lived record pointing at something already gone.

```console
$ atf check
lifetime inversion: TodoList (session) depends on Guest (function)
```

`atf check` reads the scopes off the declarations and the ordering off `depends_on`, so an
impossible pair is named before anything touches an environment.

## The check that actually proves it

Run the same suite twice in a row, against the same environment.

```console
$ atf run && atf run
```

A suite that passes once and fails the second time is leaking. Persistent records are not the leak —
they are supposed to be there. What the second run looks for is a `function` or `session` record that
outlived the lifetime you gave it.

**One green run says nothing about teardown.** Residue does not fail where it is made; it fails in a
stranger's test on a later run, and reads as flakiness until somebody proves otherwise.

A second check costs less. Ask the environment what it holds when the run is over.

```console
$ atf run
$ atf status local
resource   instance   state
Owner      primary    present
Guest      visitor    absent
```

`visitor` is absent because it was removed. `primary` is present because it is persistent. If
`visitor` is present after a run, teardown did not happen.

Put both in CI: `atf run && atf run` on a branch that changed a resource declaration, and `atf status`
after every run.

## Variations

**Fresh and uniquely named.** A fixed `nickname` means two tests running at once against one
environment fight over the same record. Give the resource a factory so each test gets its own
recognition value.

```python
@sql.row(table="guests", unique_by="nickname", scope="function")
class Guest:
    nickname: str

    @classmethod
    def factory(cls) -> Self:
        return cls(nickname=faker.user_name())
```

Scenarios then say `Given a guest`, and each one gets a nickname of its own.

**A persistent resource that a test dirties.** Scope does not help, and the default makes it likelier:
the record is recognised as present, so it is not remade, and the change survives the run. A field you
declared is put back on the next run; a field you did not is not. Either move that resource to
`scope="function"` and pay for the rebuild, or have the test put back what it changed in its own
`When`.

**The cost.** Function scope pays a create and a delete for every test that asks. On a resource with a
deep closure that is the difference between a suite you run on save and one you run before pushing.

## When it goes wrong

**The record is still there after the run.** Check the environment is `mutable`, then check whether
the process survived. A killed process — `Ctrl-C`, a CI timeout — never reached teardown. `atf status`
names what was left, and `atf make` is not what removes it; delete it in the system.

**`lifetime inversion`.** Something depends on a resource that will be gone before it is. Move the
dependency, or move the scope.

**`atf run --failed` passes.** In isolation the residue is not there. That is the tell, not the
exoneration. Reach for `atf run && atf run` instead.

**Recognition collides across tests.** Two function-scoped instances that generate the same
recognition value are the same record to ATF, so the second test finds the first one's leftovers.
Generate from something with room in it.

## Where to go next

- [Give a resource a factory](give-a-resource-a-factory.md) — the generated recognition value that
  lets function-scoped resources run in parallel.
- [Run ATF in CI](run-atf-in-ci.md) — where the two-run check and the post-run `atf status` belong.
- [Arrange](../reference/arrange.md#scope) — scope's three values, and how teardown order is derived
  from lineage.
