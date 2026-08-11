# Test a web interface

Drive a browser by role and accessible name, and claim on what a user can perceive.

## The shortest path

Declare the screen as a resource:

```python
from atf import browser


@browser.page(when_absent="observe")
class Screen:
    path: str


checkout = Screen(path="/checkout")
```

`when_absent="observe"` says this is something to look at, not something ATF makes. A screen that is
not there is a failure with a reason, never an attempt to create one.

Then say what a user does:

```gherkin
Feature: Checkout

  Scenario: paying with a card
    Given the screen "checkout"
    When I type "4242 4242" into the textbox "Card number"
    And I click the button "Pay now"
    Then the words "Payment received" are showing
```

`Given the screen "checkout"` names the declared resource — the variable name, as everywhere else —
and opens it. The environment says where:

```yaml
environments:
  local:
    mutable: true
    browser: { base_url: http://localhost:8000 }
```

## Role and accessible name, never a selector

Every interface sentence identifies its target by the **role** (`button`, `textbox`, `link`,
`heading`, `combobox`) and the **accessible name** (`"Pay now"`). Nothing in a feature file mentions a
class, an id, a `data-testid` or a path through the DOM.

The pair is what a user perceives and what a screen reader announces, so a restyle or a component
rewrite does not move it. [What we borrowed](../explanation/what-we-borrowed.md) says where the
vocabulary comes from. The cost is the section on names below.

## Acting

```gherkin
    When I click the button "Pay now"
    When I type "4242 4242" into the textbox "Card number"
    When I choose "Express" from the combobox "Delivery"
```

Typing replaces what is in the field. Choosing matches the option by its visible text.

## Claiming

```gherkin
    Then the words "Payment received" are showing
    Then the heading "Order summary" is showing
    Then the button "Pay now" is disabled
    Then the button "Pay now" is showing
```

`the words "…" are showing` claims about text anywhere on the screen. The role-and-name form is for
when you care about a particular control: a button labelled "Pay now" being disabled is a different
claim from the words "Pay now" appearing somewhere.

Interface claims retry until they hold or the step gives up. There are no sleeps in an ATF feature
file, and adding one is a sign the claim is being made about the wrong thing.

## A block of the screen: several claims, then a phrase {#a-block-of-the-screen}

There is no sentence that snapshots a region. Say what must be there, one claim per line:

```gherkin
    Then the heading "Order summary" is showing
    And the words "Coffee beans" are showing
    And the words "£12.00" are showing
    And the button "Pay now" is showing
```

Nothing else on the screen is looked at, so a promotional banner appearing beside the summary does
not turn the suite red, and a missing line item does.

When the same block is claimed in several scenarios, name it:

```gherkin
@phrase
Scenario: the order summary shows the coffee order
  Then the heading "Order summary" is showing
  And the words "Coffee beans" are showing
  And the words "£12.00" are showing
  And the button "Pay now" is showing
```

```gherkin
  Scenario: the summary survives changing the delivery option
    Given the screen "checkout"
    When I choose "Express" from the combobox "Delivery"
    Then the order summary shows the coffee order
```

That is the same move [a record](assert-a-record-field-by-field.md) makes.

## When a control has no accessible name

You cannot address it, and the answer is almost always to fix the markup.

- A button with only an icon needs `aria-label="Pay now"`, or visible text.
- A text input needs a `<label>` bound to it. A placeholder is not a name.
- A block of the screen needs `aria-label` or an `aria-labelledby` pointing at its heading.

A control with no accessible name cannot be used by a screen reader or reached by voice control, so
the test that cannot find it has found a real defect. ATF offers no escape hatch.

The trade-off is that an interface you do not control, in an iframe or a third-party widget, may be
untestable this way. Drive it inside [a step you write](write-a-step-in-python.md), and keep the
accessible sentences for the interface you own.

## Headless in CI

Headless is a property of the environment, not of the test:

```yaml
  ci:
    browser: { base_url: $CHECKOUT_URL, headless: true }
```

Leave `local` headed so you can watch a scenario run. The feature files say nothing about how the
browser is started.

## Failures keep a trace and a screenshot

A failing scenario keeps a trace of the whole run and a screenshot at the moment of failure, and the
failure message names both paths. Upload them as artefacts from CI.

Passing scenarios keep nothing. Traces are large, and a suite that keeps one for every run of every
scenario stops being something you can run often. The consequence is that a scenario which failed
once and passed on rerun leaves you the first trace and nothing else.

## When it goes wrong

**"No `button` named `Pay now`"** — the name is computed from the accessible name, which may not be
the text you see in the source. Check for a wrapping element carrying its own `aria-label`, and for
trailing whitespace in the visible text.

**Two matches** — the name is ambiguous on screen, which means it is ambiguous to a user too. Make
the names distinct rather than reaching for an index.

**A claim that flakes** — the claim is about the right thing at the wrong time, usually text that
appears and is then replaced. Claim about the state you actually want to reach.

**A screen that is never there** — `atf status <env>` reports a `when_absent="observe"` resource as
absent or unreachable. Unreachable means the environment is wrong; absent means the route is.

## Where to go next

- [Assert a record field by field](assert-a-record-field-by-field.md) — the same one-claim-per-sentence rule
  for records, and markers for values you cannot write down.
- [Configure an environment](configure-an-environment.md) — where `base_url` and `headless` are
  defined.
- [Assert](../reference/assert.md#interface-claim) — every interface claim, and what each one waits
  for.
