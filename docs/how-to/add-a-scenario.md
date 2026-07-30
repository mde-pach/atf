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
[specs and fixtures reference](../reference/provisioning.md#the-provisioning-step).

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
[read-and-compare steps](../reference/assertions.md#read-and-compare-steps). Writing a step
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

## When your scenario changes something others read

A scenario that completes a task another scenario asserts is open makes the suite depend on the
order it ran in, which is the failure mode end-to-end suites are known for. Ask for your own:

```gherkin
Given a fresh account "primary"
```

That builds an instance of the same catalog node that belongs to this scenario and is taken away
with it — the shared one is untouched, and no other scenario notices. The catalog does not change,
because wanting one to yourself is a fact about a *scenario* and the type is usually one everybody
else is happy to share. See [One to yourself](../reference/provisioning.md#fresh).

## Write down what you could not answer

Half of what comes out of talking through a behaviour is questions nobody in the room could settle.
Write them where the answer will go:

```gherkin
  Rule: A closed account cannot be billed

    # ? What happens to an invoice already in flight when the account closes?

    Scenario: A closed account cannot be billed
      ...
```

ATF shows these under the rule in the cockpit, counts them on the overview, and puts them on the
page [`atf docs`](../reference/cli.md#atf-docs) writes — which is how they reach somebody who can
answer one. It is a comment, so the file is still ordinary Gherkin, and answering one is deleting
two characters. See [Questions](../reference/provisioning.md#questions).

## Run just what you added

```sh
atf run -k 'a closed account cannot be billed'
```

[`-k`](../reference/cli.md#run-k) takes the words of the title. A tag works too, if you tagged it:

```sh
atf run --tag wip
```

And after you have fixed something, `atf run --failed` runs only what did not pass last time.

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
- [Provisioning reference](../reference/provisioning.md) — tags and `Background:`.
- [Fixtures reference](../reference/fixtures.md) — the fixtures your steps can ask for.
- [About lifecycles](../explanation/lifecycles.md) — sharing a resource, and when not to.
