# Write a step in Python

For the part that is genuinely yours, bind a sentence to a function — in the shape pytest-bdd made
familiar — and import `claims`, so it fails as well as a built-in does.

## The shortest path

Put a `.py` file anywhere under `specs:`. ATF imports it for what it registers.

```python
from atf import claims, when, then

from resources import Owner, TodoList


@when("I list the owner's lists")
def _(shell, owner: Owner):
    return shell(f"todo show {owner.email}")


@then('the listing exit code is "{code}"')
def _(result, code):
    claims.field_is(result, "exit_code", code)
```

```gherkin
  Scenario: an owner's lists are shown
    Given the todo_list "groceries"
    When I list the owner's lists
    Then the listing exit code is "0"
```

The functions are named `_` because nothing calls them by name. The sentence is the name. `when`,
`then` and `claims` all come from `atf`, so a step needs one import and no plugin configuration.

## Import `claims` and use it

Every built-in `Then` is a call into `claims`, so a step that uses it produces the same failure
message a built-in would: the record, the field, what was expected, what was there.

```python
@then('the list is called "{slug}"')
def _(groceries: TodoList, slug):
    claims.field_is(groceries, "slug", slug)
```

A bare `assert` works, and costs you the message. `assert record["slug"] == slug` fails with two
values and no idea which record they came from.

Captures arrive as text. `claims.field_is` compares them the way the built-in
`field "…" is "…"` sentence does, which is why the example above compares against `"0"` and not `0`.

## A `When` produces a value onto a slot

What a `When` returns lands on the default slot, `result`. A `Then` asks for the slot by name and gets
it as a fixture — the `result` parameter in the first example.

When a scenario does two things, name the results with `as "…"` and the slot takes that name:

```gherkin
    When I run "todo add primary@example.com ideas" as "creation"
    And I run "todo show primary@example.com" as "listing"
    Then the creation succeeded
```

```python
@then("the creation succeeded")
def _(creation):
    claims.field_is(creation, "exit_code", "0")
```

A slot is a fixture, so the name in the feature file is the parameter name in Python. Nothing
registers it; saying `as "creation"` is the registration.

## How a step gets the resource the test is about

Ask for it by name, typed by annotation. That is pytest's own rule for fixtures.

```python
@when("I list the owner's lists")
def _(shell, owner: Owner):          # any owner in scope
    return shell(f"todo show {owner.email}")


@when("I list the primary owner's lists")
def _(shell, primary: Owner):        # that one, by name
    return shell(f"todo show {primary.email}")
```

Inside a scenario, `owner: Owner` resolves to whatever the scenario arranged — `Given the todo_list
"groceries"` brings `primary` with it. In a plain pytest test nothing arranged anything, so the
[factory](../reference/arrange.md#factory) builds one. The step body is the same either way. Two
owners in scope is an error, and the message asks you to say which.

[`shell`](../reference/act.md#shell) is the fixture the command system provides: it runs a command
against this environment's `command` configuration and returns a record with `exit_code` and
`output`. See
[test a command line](test-a-command-line.md) for what the environment has to say for that to work.

## Where steps live

Any `*.py` under a path in `specs:`. There is no `conftest.py` to register, and no import to add.
Steps join one flat namespace for the whole suite, the same way
[phrases](teach-atf-a-sentence.md) do.

## Write a phrase first

A step moves a sentence's meaning out of the feature file and into Python, where the feature file
cannot show it. A [phrase](teach-atf-a-sentence.md) leaves it where the rest of the scenario is.
Reach for a step only when the sentence needs something Gherkin has no way to say: a computation, a
value from outside the suite, a client of your own.

The reverse mistake happens as often. A step that wraps one built-in sentence and adds nothing is a
phrase that took the long way round.

## When it goes wrong

**"No sentence matches …"** — the module is outside `specs:`, or the string in the decorator differs
from the sentence by a character. The failure prints both.

**A failure that says only `assert False`** — a step asserted by hand. Route it through `claims`.

**A fixture that does not exist** — a `Then` asking for `listing` when the feature said
`as "creation"`. The slot name and the parameter name are the same name; there is no aliasing.

**Two resources of a kind in scope** — annotate for the type and name the instance: `primary: Owner`
rather than `owner: Owner`.

## Where to go next

- [Assert a record field by field](assert-a-record-field-by-field.md) — before writing a `Then`, check whether
  a field claim and a marker already say it.
- [Teach ATF a sentence](teach-atf-a-sentence.md) — the cheaper half of the same job.
- [Extending ATF](../reference/extending-atf.md) — steps, claims you register, and adapters, with the
  signatures each one has to have.
