# How to add a scenario

Add one more behaviour to a feature that already exists. This is the loop you will be in most days.

## Find the feature it belongs to

Features live under the manifest's `specs` directory, and each is bound to a steps module by a
`scenarios(...)` call:

```python
# specs/steps/test_accounts.py
scenarios("../features/accounts.feature")
```

Add the scenario to the feature whose steps you will be reusing. A behaviour that shares no
vocabulary with anything in the file usually wants a feature of its own.

## Write the scenario

```gherkin
  Scenario: A closed account cannot be billed
    Given the account "closed"
    When I attempt to bill the account
    Then the request is rejected
```

Write it in the language of the domain. `Given` lines declare what must exist; `When` is the one
thing being done; `Then` is what should be true afterwards. If you find yourself writing three
`When`s, you probably have two scenarios.

The `Given the <type> "<name>"` step is ATF's, and works for anything in the catalog with no
registration. See the
[specs and fixtures reference](../reference/specs-and-fixtures.md#the-provisioning-step).

## Reuse a resource, or add one

Look first for an instance that already says what you mean. Reusing `accounts.primary` is free; a
second identical account is one more thing to keep alive in every environment.

Reuse it only if your scenario **reads** it. A scenario that changes a persistent resource must have
its own:

> Read-only scenarios can share a resource; a scenario that changes one needs its own.

That is the rule that stops a suite passing on Monday and failing on Tuesday, and it is worth
understanding rather than memorising — [About lifecycles](../explanation/lifecycles.md#a-scenario-that-mutates-a-persistent-resource-must-own-it)
explains why.

When you do need a new instance, it is one YAML block; see
[How to add a resource](add-a-resource.md).

## Check whether you need to write anything at all

Before writing a step, look at what a `Then` is really claiming. If it is a field of a resource the
catalog declares, ATF already has a step for it:

```gherkin
  Scenario: A closed account is on no plan
    Given the account "closed"
    Then the account "closed" field "plan" is ""
    And the account "closed" field "status" is not "active"
```

Those need no code, in any suite. They read the resource back through the adapter at the moment they
run, so they hold even after a `When` of yours has changed it — see
[read-and-compare steps](../reference/specs-and-fixtures.md#read-and-compare-steps). Writing a step
by hand to compare one field is re-implementing something the framework does.

## Add the missing vocabulary

What is left after that is genuinely yours: performing an action, and any claim that is not about
one field of one resource. Each is a function in the steps module:

```python
@when("I attempt to bill the account")
def _(context, api):
    context.result = api.bill(context.account["id"], expect_error=True)


@then("the request is rejected")
def _(context):
    assert context.result.status_code == 422
```

Steps talk to each other only through `context`. The provisioning step put the record there as
`context.account`; your `When` puts its answer there for your `Then` to read.

Prefer extending an existing step over adding a near-duplicate. Two steps differing by one word are
harder to read than one step with a parameter:

```python
@then(parsers.parse('the request is rejected with "{code:d}"'))
def _(context, code):
    assert context.result.status_code == code
```

## Cover several cases at once

When the same behaviour should hold for a handful of inputs, use an `Examples` table rather than
copying the scenario:

```gherkin
  Scenario Outline: Accounts report their own plan
    Given the account "<who>"
    Then the account "<who>" field "plan" is "<plan>"

    Examples:
      | who       | plan     |
      | primary   | standard |
      | secondary | trial    |
```

Each row becomes its own test, and each row's resources are provisioned for that row only.

## Run just what you added

```sh
atf run 'specs/steps/test_accounts.py::test_a_closed_account_cannot_be_billed'
```

pytest-bdd names the test after the scenario, lower-cased with underscores. Running the file alone
also works while you iterate:

```sh
atf run specs/steps/test_accounts.py
```

Then run the whole suite once before you push. A new scenario that mutates something is exactly the
kind of change that only shows up in the scenario *after* it.

## Check it against the other environments

Open the cockpit and find your scenario in each environment the suite runs against:

```sh
atf serve
```

A scenario naming a resource that environment does not have yet is fine — running it is what creates
it, and the page says how many it would create. You can provision them ahead of time from the
resource type page, or leave it to the first run.

A scenario shown as **blocked** is the one to act on. It names something a run cannot fix: a system
with no adapter configured there, an adapter that raised, or a missing
[reference](../reference/catalog.md#mode) resource. See
[How to find out why an environment is red](find-out-why-an-environment-is-red.md).

A new scenario is blocked most often because it is the first to name a reference resource that only
your dev environment happens to have.

## Where to go next

- [How to add a resource](add-a-resource.md) — when the scenario needs something new to exist.
- [How to find out why an environment is red](find-out-why-an-environment-is-red.md) — when it does
  not pass.
- [Specs and fixtures reference](../reference/specs-and-fixtures.md) — tags, `Background:`, and the
  fixtures your steps can ask for.
- [About lifecycles](../explanation/lifecycles.md) — sharing a resource, and when not to.
