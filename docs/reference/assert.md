# Assert

Assert is the last verb: what the test says must be true. Every claim here names both sides and
their kinds when it fails, and a claim about a field the record does not have lists the fields it
does.

## Claim {#claim}

A claim is a `Then` sentence that either holds or fails. These are the ones ATF ships.

`Then the {type} "{name}" exists`
:   The environment holds a record of that type recognised by that name.

`Then the {type} "{name}" is gone`
:   It holds no such record.

`Then the {type} "{name}" field "{field}" is "{value}"`
:   The field equals the value under [the comparison rules](#comparison-rules).

`Then the {type} "{name}" field "{field}" is #{kind}`
:   The field is of that kind — see [markers](#marker).

`Then the {type} "{name}" field "{field}" is not "{value}"`
:   The field does not equal the value.

`Then the {type} "{name}" field "{field}" contains "{value}"`
:   The field's text contains the value.

`Then the {type} "{name}" field "{field}" does not contain "{value}"`
:   It does not.

`Then the {type} "{name}" field "{field}" is empty`
:   The field is absent, null, an empty string, or an empty list or object.

`Then the {type} "{name}" field "{field}" is not empty`
:   It is none of those.

`Then the environment has {n} {type}`
:   The environment holds exactly `n` records of that type.

```gherkin
Then the todo_list "groceries" exists
Then the todo_list "groceries" field "slug" is "groceries"
Then the environment has 2 todo_list
```

The type is written as it is everywhere else — the class name in snake case. `Then the environment
has 2 todo_list` does not pluralise the type; the number does that work.

Every claim is one sentence, and one sentence claims one thing. There is no table and no embedded
document anywhere after `Then`; several claims that belong together become
[one phrase](#a-whole-record), which is still sentences.

The same field family reads over a [named slot](act.md#naming-a-result), with the slot's name where
the type and name would be. `Then the result field "exit_code" is "0"` reads the default slot;
`Then the listing field "output" contains "groceries"` reads one a test named.

Every member of the field family works over a slot: `is`, `is #{kind}`, `is not`, `contains`,
`does not contain`, `is empty`, `is not empty`. `exists`, `is gone` and `the environment has` do not
— a slot is something a test produced, not something an environment holds.

### What a failure says

A field that does not match:

```text
Then the todo_list "groceries" field "slug" is "groceries"

  todo_list "groceries" field "slug"
    is       "grocery-list"  (str)
    expected "groceries"     (str)
```

Both sides, both kinds. The kinds matter because the comparison is tolerant: when `"0"` and `false`
compare equal and you did not want them to, the kinds are what tell you.

A field the record does not carry:

```text
  todo_list "groceries" has no field "titel"
    it carries: id, slug, owner_id
```

`is gone` names what was still there, and `the environment has` names the count it found and the
names it counted.

**In CI** — the failure message is the whole diagnosis: it goes to the console, into the report, and
nowhere else is needed.

**In the editor** — the same message, with the record beside it, so you can see the field you meant.

**To an agent** — a failed claim comes back structured: the sentence, the field, both values and
both kinds, as fields rather than as a string to parse.

## Marker {#marker}

A marker stands where a value would and claims a kind rather than a value. It is how you assert on a
field whose exact content you cannot know.

**Quotes mean a literal value. `#` means a kind.**

```gherkin
Then the todo_list "groceries" field "id" is "uuid"
Then the todo_list "groceries" field "id" is #uuid
```

The first holds only when the field is the four-letter text `uuid`; the second when it is any UUID.
A value you can write down goes in quotes; one you cannot goes after a `#`.

ATF ships eight, and each holds when the value is what it names.

`#uuid`
:   A UUID, in any standard casing.

`#datetime`
:   An ISO 8601 date-time.

`#date`
:   An ISO 8601 date.

`#absent`
:   Not present at all.

`#present`
:   Present, whatever it is.

`#int`
:   An integer, written as a number or as digits.

`#str`
:   A string.

`#bool`
:   A boolean, under [the comparison rules](#comparison-rules).

```gherkin
Then the todo_list "groceries" field "created_at" is #datetime
Then the todo_list "groceries" field "deleted_at" is #absent
Then the result field "exit_code" is #int
```

`#absent` is how you claim a field was removed. Every other claim on this page is about a field that
is there.

Markers are a registry, so a team adds its own:

```python
from atf import marker

@marker("iban")
def _(value):
    return checksum_ok(value), f"{value!r} is not a valid IBAN"
```

The name is registered without the sigil: `#` is how a marker is *said* in a scenario, the way `@`
is how a tag is written. The function returns whether the marker holds and the message for when it
does not.

**In CI** — a failing marker reports its own message, plus the value and its kind.

**In the editor** — the registered markers are listed with the vocabulary, built-ins and your own
together.

**To an agent** — the marker list is served with the vocabulary, so an agent uses `#uuid` instead of
inventing a literal it cannot know.

## A whole record {#a-whole-record}

There is no whole-record claim. A record is claimed one field per sentence:

```gherkin
Then the todo_list "groceries" field "slug" is "groceries"
And the todo_list "groceries" field "owner_id" is #present
And the todo_list "groceries" field "id" is #uuid
And the todo_list "groceries" field "deleted_at" is #absent
```

When that set repeats, it becomes a [phrase](act.md#phrase):

```gherkin
@phrase
Scenario: the todo_list "{slug}" is set up the way a new one should be
  Then the todo_list "{slug}" field "id" is #uuid
  And the todo_list "{slug}" field "owner_id" is #present
  And the todo_list "{slug}" field "deleted_at" is #absent
```

The scenario then says it in one line:

```gherkin
Scenario: adding a list
  Given the owner "primary"
  When I run "todo add primary@example.com groceries"
  Then the todo_list "groceries" is set up the way a new one should be
```

A failure inside the phrase names the phrase, the line within it, and the scenario that said it.

The cost is length. Four sentences are longer than four table rows, and the type and name are
repeated on every line.

Claiming four fields never claims the absence of a fifth: the record may carry `created_at` and six
fields added last week and the claims still hold, so a backend that starts returning a new field
does not turn a suite red. `#absent` switches that blindness off for the one field where removal is
the point.

**In CI** — each failing sentence is reported separately, with both sides and their kinds.

**In the editor** — the record sits beside the sentences, with the failing ones marked; a phrase
shows its body.

**To an agent** — the failures come back as a list, one entry per sentence, each with its field,
expected value and actual value.

## The comparison rules {#comparison-rules}

Gherkin has one kind of value: text. Records have several. These rules bridge the two, and they
apply to every claim on this page.

Text compares equal to a number it reads as, so `"42"` matches `42`. `true`, `yes` and `1` are the
same written word, as are `false`, `no` and `0`, so `"no"` matches `False`. Those boolean words are
matched without regard to case; string comparison is not, and text matches text exactly, so
`"groceries"` never matches `"Groceries"`.

A structured value — a list or an object in the record — compares as JSON: `'{"tone": "dark"}'`
matches `{"tone": "dark"}`. What you wrote is parsed, so key order and whitespace do not matter. If
it is not valid JSON it is compared as text, and the failure message says so. Nothing else is
coerced.

Tolerance costs precision: an `is` claim cannot tell `0` from `false`, because both are written the
same way and both match either. When the kind is the point, claim the kind — `is #int` says the
field is a number and no amount of `no` will satisfy it.

**In CI** — Not shown. The rules are the same everywhere; there is nothing to display.

**In the editor** — Not shown.

**To an agent** — Not shown.

## Interface claim {#interface-claim}

Claims about a screen address controls the way [interface acts](act.md#using-an-interface) do: by
role and accessible name, never by a selector.

These are the ones ATF ships.

`Then the {role} "{name}" is showing`
:   A control with that role and name is visible.

`Then the {role} "{name}" is not showing`
:   No such control is visible.

`Then the {role} "{name}" reads "{text}"`
:   That control's text is exactly that.

`Then the {role} "{name}" is disabled`
:   That control is present and not operable.

`Then the {role} "{name}" is enabled`
:   That control is present and operable.

`Then the words "{text}" are showing`
:   That text is visible anywhere on the page.

```gherkin
Then the button "Pay now" is disabled
Then the heading "Order summary" is showing
Then the words "Payment received" are showing
```

`the words` is the one claim that does not name a control. Use it when the text is the point and the
element carrying it is not.

There is no whole-screen claim, for the same reason there is no whole-record one. A region is
claimed by the controls that matter, and a set that repeats becomes a phrase:

```gherkin
@phrase
Scenario: the order summary is showing
  Then the heading "Order summary" is showing
  And the words "Coffee beans" are showing
  And the words "£12.00" are showing
```

The trade-off is the same one: a snapshot of the whole region would have caught a control you never
thought to name, and sentences catch only what you named.

A claim about a control that is not there lists the controls of that role that are:

```text
  no button "Pay Now" on /checkout
    buttons on the page: "Pay now", "Cancel", "Edit basket"
```

**In CI** — headless. The failure message names the role, the name, the page, and what was there
instead.

**In the editor** — the browser is visible, so the message and the screen sit side by side.

**To an agent** — the failure comes back with the ARIA snapshot of the page, which is a structure an
agent can read rather than a screenshot it cannot.

## A claim you register {#a-claim-you-register}

When the sentence you want is neither a marker nor a composition of the claims above, register it.
It is a sentence and the function that answers it.

```python
from atf import claim

@claim('the {type} "{name}" field "{field}" is a valid IBAN')
def _(record, field):
    return checksum_ok(record[field]), f"{field} is not a valid IBAN"
```

The function returns whether the claim holds and the message for when it does not. The sentence is
then said like any other:

```gherkin
Then the owner "primary" field "iban" is a valid IBAN
```

Register a claim when the check is a rule about a value that a whole sentence should carry. Register
a [marker](#marker) when it is a kind that any field could be. The marker is the smaller of the two
and composes with every claim on this page, so reach for it first.

**In CI** — a registered claim fails exactly as a built-in does, with your message and the value.

**In the editor** — it appears in the vocabulary beside the built-ins, with the file it is defined
in.

**To an agent** — it is served in the same vocabulary, with its placeholders, so an agent says it
rather than inventing it.

[Extending ATF](extending-atf.md#registering-a-claim) has the rest: where registrations are loaded
from and how to ship a set of them as a package.

## Claims as a Python library {#claims-as-a-python-library}

`claims` is a public library. Import it and a plain pytest test gets the same comparison rules and
the same messages a scenario gets.

```python
from atf import claims

def test_a_new_list_is_set_up(groceries: TodoList):
    claims.field_is(groceries, "slug", "groceries")
    claims.field_is_a(groceries, "id", "uuid")
    claims.field_is_a(groceries, "deleted_at", "absent")
```

The field sentences and the functions that say them:

`field "{f}" is "{v}"`
:   `claims.field_is(record, f, v)`

`field "{f}" is #{kind}`
:   `claims.field_is_a(record, f, kind)`

`field "{f}" is not "{v}"`
:   `claims.field_is_not(record, f, v)`

`field "{f}" contains "{v}"`
:   `claims.field_contains(record, f, v)`

`field "{f}" does not contain "{v}"`
:   `claims.field_does_not_contain(record, f, v)`

`field "{f}" is empty`
:   `claims.field_is_empty(record, f)`

`field "{f}" is not empty`
:   `claims.field_is_not_empty(record, f)`

One function per sentence, and no function that takes a whole record, because there is no sentence
that claims a whole record.

`field_is_a` is where the sigil goes in Python. A scenario distinguishes a literal from a kind by
`"uuid"` against `#uuid`; Python does it by which function you call, with the marker name written
without the sigil, as it is registered.

Each function raises `AssertionError` carrying the message its sentence would have carried: both
sides, both kinds, and the record's fields listed when the field is unknown. This is what
[a step you write](act.md#a-step-you-write) calls, so read it before writing one.

**In CI** — a `claims` failure in a plain pytest test reads like a claim failure in a scenario,
because it is one.

**In the editor** — Not shown. The editor works in sentences; `claims` is for Python.

**To an agent** — Not shown.

## Where to go next

- [Act](act.md) — the acts that fill the slots the field claims read from, and the interface verbs
  the interface claims pair with.
- [Arrange](arrange.md) — how a type and a name resolve to the record that `exists` and the field
  claims are asking about.
- [Extending ATF](extending-atf.md) — where a registered claim and a registered marker are loaded
  from, and how to share a set of them between suites.
