# Run only what a change touched

Run the tests that depend on a resource you changed, and ask what they will be before you run them.

## The shortest path

```sh
atf run --select +groceries
```

That runs every test that touches `groceries`: the tests that ask for it, the resources that depend
on it, and the tests that ask for those.

## The three forms

`groceries` selects the tests that ask for that resource, and nothing else. `+groceries` adds
everything downstream: the resources carrying a `TodoList` field, and their tests. `+TodoList` does
the same for a type rather than an instance — every `TodoList`, and everything downstream of any of
them.

Pass `--select` more than once for a union:

```sh
atf run --select +groceries --select +visitor
```

The edges come from [lineage](../reference/arrange.md#lineage) — a field typed as another resource.
`Task` has a `todo_list: TodoList` field, so every `Task` is downstream of `groceries`, and so is
every test that asks for one. Nobody drew that edge.

## Ask before you run

```console
$ atf impact groceries
TodoList groceries
  depends on
    Owner primary
  depended on by
    Task laundry
  tests that touch it
    specs/lists.feature:4    a list shows under its owner
    specs/tasks.feature:9    completing a task
    tests/test_show.py::test_a_list_shows_under_its_owner
  3 tests, 2 resources
```

Read it before a change, not after a red run.

## What nothing asks for

```sh
atf unused
```

```text
weekend (TodoList)     declared, no test asks for it, nothing depends on it
archived (Task)        declared, no test asks for it, nothing depends on it
```

Delete them, or find the test that was meant to exist. `atf unused` looks at declarations only; a
resource used exclusively from [a step you write](../reference/act.md#a-step-you-write) that reaches
past the declaration is invisible to it, so read the list before acting on it.

## The trade-off

The graph knows what a test **declares**, not what it incidentally touches. A test that shells out
and writes a row nobody declared is not on that edge, and `--select` will not run it. So:

- Use selection on branches, where the cost of a full run is the thing you are avoiding.
- Run everything on the main branch, before a release, and on a schedule. The full run stays the
  final word.
- When a selected run is green and a full run is red, the difference is an undeclared dependency.
  Declare it. It is usually a bug in the test rather than in the product.

## When it goes wrong

**Exit `2`, `unknown selector "grocerys"; did you mean "groceries"`.** The name matched no resource and
no type. The run never starts, so a typo cannot go green.

**A green run that selected no tests.** The name matched, and nothing depends on it. That is an
answer, so the run exits `0`.

**A test you expected is missing.** Nothing declares the edge you had in mind. Check with
`atf impact`, then add the field.

**`atf unused` lists something in use.** It is used through a step, not a declaration.

## Where to go next

- [Depend on another resource](depend-on-another-resource.md) — the field that creates the edge
  `--select` walks.
- [Run ATF in CI](run-atf-in-ci.md) — where selection pays for itself, and how a pipeline reads the
  three exit codes a selected run can produce.
- [Declared, not executed](../explanation/declared-not-executed.md) — why the graph exists, and how
  selection compares with the coverage and tag heuristics it replaces.
