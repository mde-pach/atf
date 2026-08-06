# Write a scenario

A scenario is a test written in Gherkin. It compiles to what a pytest function compiles to, so
anything one can do the other can do.

## The shortest path

Put a `.feature` file anywhere under the directory named by `specs:` in `atf.yaml`:

```gherkin
Feature: Showing lists

  Scenario: an owner's lists are shown
    Given the todo_list "groceries"
    When I run "todo show primary@example.com"
    Then the result field "exit_code" is "0"
    And the result field "output" contains "groceries"
```

Then run it:

```sh
atf run
```

No Python sits beside this file. `Given the todo_list "groceries"` names a declared resource, and
naming it is what makes it exist — with its owner, because `TodoList.owner` is typed `Owner`. See
[lineage](../reference/arrange.md#lineage) for what else comes along.

The quoted string is the resource's own name, the variable it was declared as — not the value of the
recognition field. `Given the owner "primary"` arranges the owner whose email is
`primary@example.com`.

## The rule: a scenario is sentences {#the-rule}

**A scenario is sentences. Nothing else.** No pipe tables inside a step, no `"""` blocks, no YAML or
JSON. The only table in the language is `Examples`, under a `Scenario Outline`.

Anything that looks structured is written as **several sentences**:

```gherkin
    Given the todo_list "groceries" but "slug" is "weekly"
    And "owner" is "null"
    Then the todo_list "groceries" field "slug" is "weekly"
    And the todo_list "groceries" field "id" is #uuid
```

When the same sentences keep travelling together, they become one
[phrase](teach-atf-a-sentence.md).

## The sentences you already have

These need no phrase and no Python.

```gherkin
    Given the todo_list "groceries"
    Given an owner
    Given the todo_list "groceries" but "slug" is "weekly"
    When I run "todo show primary@example.com" as "first"
    When I complete the task "laundry"
    When I list every todo_list
    When I click the button "Pay now"
    Then the todo_list "groceries" exists
    Then the todo_list "groceries" field "id" is #uuid
    Then the environment has 2 todo_list
    Then the result field "output" contains "groceries"
    Then the words "Payment received" are showing
```

A `Given` names a resource, asks for any of a kind, or varies one field of one. A `When` runs a
command, performs an action a resource declares, or acts on an interface by role and name. A `Then`
claims one field, counts what the environment holds, reads a result, or claims about the screen.
[Act](../reference/act.md) and [Assert](../reference/assert.md#claim) are that grammar in full —
check both before writing any Python, and see
[assert a record field by field](assert-a-record-field-by-field.md) for quoted values against `#`
kinds.

Two of these need something declared first. `When I complete …` needs `complete` in the resource's
`actions`, and the interface sentences need a `@browser` resource.

## Background

A `Background` runs before every scenario in the file.

```gherkin
Feature: Showing lists

  Background:
    Given the todo_list "groceries"

  Scenario: the list is shown
    When I run "todo show primary@example.com"
    Then the result field "output" contains "groceries"

  Scenario: an unknown owner is refused
    When I run "todo show ghost@example.com"
    Then the result field "exit_code" is "1"
```

Put arranging in a `Background`, never acting. A `When` in a `Background` hides the action that the
second scenario is actually about.

## Rule

A `Rule` groups the scenarios that demonstrate one business rule, and may carry its own `Background`,
which runs after the feature's.

```gherkin
Feature: Adding lists

  Rule: a list needs an owner that exists

    Background:
      Given the owner "primary"

    Scenario: an existing owner gets a list
      When I run "todo add primary@example.com ideas"
      Then the result field "exit_code" is "0"

    Scenario: an unknown owner is refused
      When I run "todo add ghost@example.com ideas"
      Then the result field "exit_code" is "1"
```

`Rule` changes nothing about how the scenarios run. `atf docs` carries the grouping through to the
rendered page.

## Scenario Outline

An outline with `Examples` is one scenario per row, and its table is the one exception to
[the rule](#the-rule): the rows are genuinely one shape, and the table is above the steps rather than
inside one. Placeholders are written `<name>`.

```gherkin
Feature: Adding lists

  Scenario Outline: an unknown owner is refused
    When I run "todo add <email> ideas"
    Then the result field "exit_code" is "1"

    Examples:
      | email              |
      | ghost@example.com  |
      | nobody@example.com |
```

Each row is a separate test with its own [outcome](../reference/the-record.md#outcome), so one red row
does not hide the others. Substitution is textual: a placeholder can stand anywhere a value can,
including in a resource name.

An outline costs readability. Four rows of one sentence is worth it; four rows differing in three
columns each is usually two scenarios wearing a disguise.

## Tags

A tag is a word beginning with `@`, on a `Feature`, a `Rule` or a `Scenario`. Tags on a feature apply
to everything in it.

```gherkin
@smoke
Feature: Showing lists

  @slow
  Scenario: an owner's lists are shown
    Given the todo_list "groceries"
```

```sh
atf run --tag smoke
```

`@phrase` is reserved. A scenario tagged with it is vocabulary, never collected as a test — see
[teach ATF a sentence](teach-atf-a-sentence.md).

## Where feature files live and how they are collected

`atf.yaml` names one place:

```yaml
specs: ./specs
```

Everything under it is collected: `*.feature` files at any depth, and pytest functions in `*.py`
files alongside them. Directories do not scope anything. A feature needs no `conftest.py` and no
Python beside it. Python under `specs/` is imported for what it registers —
[steps you write](write-a-step-in-python.md), claims and markers — not as a condition of a feature
file running.

## When it goes wrong

**"No sentence matches …"** — the failure names the sentence, the file and the line. Either the
sentence is not one of the built-ins and needs [a phrase](teach-atf-a-sentence.md), or the phrase
that defines it is outside `specs:`.

**A resource name that resolves to nothing** — the quoted name is the variable name in your resources
module, not the recognition value. `atf unused` usually finds the typo from the other end.

**Everything is red before it runs** — `atf check` reads the suite without touching an environment
and reports sentences that match nothing, phrases that collide, and resources that cannot be built.
Run it first.

## Where to go next

- [Teach ATF a sentence](teach-atf-a-sentence.md) — when a scenario keeps repeating three lines, or
  carries an exit code it should not have to know.
- [Test a command line](test-a-command-line.md) — what `When I run` needs in the environment, and why
  claiming on a message is a trap.
- [Act](../reference/act.md) — the full grammar of the sentences above.
