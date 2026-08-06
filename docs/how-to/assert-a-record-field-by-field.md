# Assert a record field by field

Claim one field per sentence, using [markers](../reference/assert.md#marker) for the values you
cannot write down in advance. When the same set of fields keeps appearing, turn the set into
[a phrase](teach-atf-a-sentence.md).

## The shortest path

```gherkin
  Scenario: a list is stored against its owner
    Given the todo_list "groceries"
    Then the todo_list "groceries" field "slug" is "groceries"
    And the todo_list "groceries" field "id" is #int
    And the todo_list "groceries" field "owner_id" is #present
```

Three sentences, three fields. **Quotes mean a literal value; `#` means a kind.** `is "int"` compares
against the string `int`. `is #int` says the id is a whole number without saying which one, and
`#present` says the foreign key is set without saying what it points at.

There is no table form. A record is no exception to
[the rule that a scenario is sentences](write-a-scenario.md#the-rule).

## When the set repeats, make it a phrase

The same three claims written in nine scenarios are a concept nobody has named yet.

```gherkin
@phrase
Scenario: the list is set up the way a new one should be
  Then the todo_list "groceries" field "slug" is "groceries"
  And the todo_list "groceries" field "id" is #int
  And the todo_list "groceries" field "owner_id" is #present
```

```gherkin
  Scenario: adding a list stores it against its owner
    Given the owner "primary"
    When I run "todo add primary@example.com groceries"
    Then the list is set up the way a new one should be
```

The scenario now says why those three fields matter. See
[teach ATF a sentence](teach-atf-a-sentence.md) for captures, nesting and the cost of the
indirection.

## What field claims say, and what they deliberately do not

Each claim says **what must match**. None says what may also exist. Fields you did not name are not
looked at, so a migration that adds a `created_at` column does not turn your suite red.

The cost is that this cannot catch a field appearing that should not have. When that is the claim you
want, make it:

```gherkin
    Then the todo_list "groceries" field "deleted_at" is #absent
```

`#absent` is how you say "not this one", one field at a time. There is no way to say "and nothing
else".

## The markers you have

The built-ins cover the kinds of value you cannot write down in advance: `#uuid`, `#datetime`,
`#date`, `#int`, `#str`, `#bool`, `#present` and `#absent`. What each one matches is in the registry —
[Assert](../reference/assert.md#marker), which is also where a marker you registered yourself appears.

A marker is a value, so it stands anywhere a value stands.

## Register a marker of your own

A marker is a predicate over one value, registered by name. Put it in any `.py` file under `specs:`,
the same place [steps](write-a-step-in-python.md) live.

```python
from atf import marker

from billing import checksum_ok


@marker("iban")
def _(value):
    return checksum_ok(value), "not a valid IBAN"
```

The name carries no sigil. `#` is how a marker is *said* in a scenario, the way `@` is how a tag is
written — so registering `iban` is what makes `#iban` a value:

```gherkin
    Then the owner "primary" field "iban" is #iban
```

Return two things: whether it held, and what to say when it did not. The message is what the failure
prints under the field name, so write the half a reader needs — "not a valid IBAN", not "failed".

Markers share one flat namespace with the built-ins. Registering `int` again is an error, not an
override.

Write a marker when the thing you cannot pin down is a *kind of value*: an IBAN, a signed URL, a
version string. When it is a whole sentence — a relationship between two fields, say — register
[a claim](../reference/extending-atf.md#registering-a-claim) instead:

```python
from atf import claim

from billing import checksum_ok


@claim('the {type} "{name}" field "{field}" is a valid IBAN')
def _(record, field):
    return checksum_ok(record[field]), f"{field} is not a valid IBAN"
```

The marker composes into any field claim. The claim reads as English. Neither replaces the other.

## Variations

**A result rather than a resource.** The same sentences work on a slot:

```gherkin
    When I run "todo show primary@example.com" as "listing"
    Then the listing field "exit_code" is "0"
    And the listing field "output" contains "groceries"
```

**Existence and counting.** `Then the todo_list "groceries" exists`, `Then the todo_list "groceries"
is gone`, `Then the environment has 2 todo_list`. A field claim is about a record that is there;
these are about whether it is.

**A screen rather than a record.** The same one-sentence-per-claim rule, addressed by role and
accessible name — see [test a web interface](test-a-web-interface.md).

## When it goes wrong

**"field `owner_id`: missing"** — the record does not have that field at all. Either the name is
wrong for this system, or the claim belongs against a different record. Markers do not rescue a
missing field except `#absent`.

**A timestamp that never matches** — comparing to a literal date fails the moment the clock moves.
`#datetime` is the answer, and if the exact value matters, claim on it in
[a step](write-a-step-in-python.md) where you can compute the expectation.

**A claim that passes when you expected red** — `is "#int"` is a literal, not a marker. Quoting a
marker turns it into the four-character string.

**A marker that matches everything** — a predicate returning one value rather than a pair passes
silently on anything truthy. Return `(bool, message)`.

**Ten claims about one record** — the record is not the subject of the scenario; something about it
is. Name that thing in a phrase and say the phrase.

## Where to go next

- [Teach ATF a sentence](teach-atf-a-sentence.md) — the answer to a set of field claims that keeps
  coming back.
- [Assert](../reference/assert.md#claim) — every claim sentence, the marker registry, and what a
  failure prints for each.
- [Write a step in Python](write-a-step-in-python.md) — for a claim that needs a computation before
  it can compare.
