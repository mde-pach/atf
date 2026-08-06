# Vary a resource for one test

Change one field of a declared resource for a single test, without adding an instance the rest of the
suite has to live with.

## The shortest path

Say `but` and name the field that differs.

```gherkin
Scenario: a renamed list still shows under its owner
  Given the todo_list "groceries" but "slug" is "shopping"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "shopping"
```

One field per sentence. Everything not named is taken from `groceries`, including `owner`, so
`primary` is still provisioned first.

A second field is a second sentence, joined with `And`.

```gherkin
Given the todo_list "groceries" but "slug" is "shopping"
And "owner" is "deputy"
```

The `And` lines belong to the `Given` above them. They carry no resource name because they are still
talking about the same one.

A [variation](../reference/arrange.md#variation) is not an edit. It declares a different resource for
the test that asked for it. The instance `groceries` is untouched.

## Removing a field

`null` removes the field rather than setting it to null.

```gherkin
Scenario: a list with no owner is not shown to anyone
  Given the todo_list "groceries" but "owner" is "null"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "no lists"
```

Removing `owner` removes the dependency with it, so `primary` is not provisioned for this test. This
is how you test the shape a resource has when a field is absent, which is a different assertion from
the field being empty.

Removals and replacements mix freely, one to a sentence.

## Which of the three to reach for

**A variation** when one test needs one thing different. The difference lives next to the assertion
that needs it, and nothing else in the suite sees it.

**A [factory](give-a-resource-a-factory.md)** when the identity does not matter at all. Naming a value
states something narrower than you mean, and freezes one sample.

**A second named instance** when two tests both need the same difference. The second `but` is
duplication, and duplication drifts.

If the assertion would still hold for any slug, a variation that pins the slug is noise — say
`Given a todo_list` and let the factory build one.

The moment a second scenario copies a `but` sentence, the difference deserves a name.

```python
deputy = Owner(email="deputy@example.com")
delegated = TodoList(owner=deputy, slug="delegated")
```

Scenarios then say `Given the todo_list "delegated"`.

Named instances appear in `atf status` and `atf impact`. A variation does not, because it exists only
for the test that declared it. That is the trade-off in both directions: a variation stays invisible
to the graph, and a named instance is visible to it at the price of a line everyone reads.

A run of `And` lines under one `Given` is still one variation. If a scenario needs five of them, the
resource it is asking for is not the one you declared.

## When it goes wrong

**Patching the recognition field names a different resource.** `but "slug" is "shopping"` does not
rename the `groceries` row. It declares a record recognised as `shopping`, which will be created if
it is not already there. That is usually what you want. It is not, if you were trying to test a
rename — a rename is something the system under test does, so it belongs in the `When`.

**`todo_list has no field "name"`.** A variation may only name declared fields. `atf check` catches
this across every scenario without touching an environment.

**Removing a field the system requires.** `but "slug" is "null"` on a column declared `NOT NULL`
fails when the record is created, and the failure comes from the system, quoting its own error. ATF
does not pre-empt it, because the system's rules are the thing under test.

**An `And` line that lost its `Given`.** `And "owner" is "null"` reads as a variation of whatever
`Given` came last. Put it directly under the sentence it varies; a `When` in between ends the run of
fields.

**Varying a resource somebody else in the closure also needs.** If a scenario arranges `laundry`, its
`todo_list` comes from the task's declaration, not from a variation applied to `groceries` earlier in
the same scenario. Vary the resource the test actually names.

## Where to go next

- [Give a resource a factory](give-a-resource-a-factory.md) — for the case above where the identity
  does not matter.
- [Write a scenario](write-a-scenario.md) — where `but` sits among the other `Given` forms.
- [Arrange](../reference/arrange.md#variation) — the rules in full, including a variation that names a
  dependency instead of removing it.
