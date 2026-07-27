# 1. Your first spec

In this lesson you will build a working test suite from nothing, watch ATF create the data the test
needs, and see it pass. Then you will add a resource and a scenario of your own.

You need Python 3.11 or newer and about ten minutes. You do not need a server, a database, an API
key, or any prior knowledge of ATF.

This is the first of three lessons. The next two point ATF at a real service and show you the
cockpit.

## Install ATF

Make a directory to work in, and install ATF into it:

```sh
mkdir atf-tutorial && cd atf-tutorial
python3 -m venv .venv
source .venv/bin/activate
pip install git+https://github.com/mde-pach/atf
```

Check that it worked:

```sh
atf --help
```

You will see a list of commands. That is all the setup there is.

## Create the suite

ATF can write a starter suite for you:

```sh
atf init todo-suite
cd todo-suite
```

It writes a complete, runnable project:

```
todo-suite/
  atf.yaml                       the manifest: environments, adapters, mutable_envs
  catalog/
    resources.yaml               the resource types
    accounts.yaml                instances
    projects.yaml
  specs/
    features/accounts.feature    scenarios, in Gherkin
    steps/test_accounts.py       your When/Then vocabulary
    api.py                       the client your steps call
  adapters.py                    custom adapters, if you ever need one
  conftest.py                    enables ATF's pytest plugin
```

It also includes a small stand-in API, so the suite has something to talk to before you have a
service of your own. Lesson 2 replaces it with yours.

## Read the two files that matter

First the catalog. This is the data your tests need:

```sh
cat catalog/accounts.yaml
```

```yaml
primary:
  resource: account
  represents: The account the rest of the catalog hangs off.
  body:
    email: primary@example.com
```

That is a [resource](../explanation/glossary.md#resource): a thing that must exist before a test can
run. Notice there is no code in it — a name, a type, and the fields it is made of.

Now the spec:

```sh
cat specs/features/accounts.feature
```

```gherkin
Feature: Accounts
  An account owns the projects created under it.

  Scenario: A project is created under its account
    Given the project "alpha"
    Then the project "alpha" exists
    And the project "alpha" field "slug" is "alpha"

  Scenario: A project is listed under its account
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the project "alpha" is listed
```

Look at the first scenario: not one of its three lines is code you wrote. `Given the project "alpha"`
names a resource in your catalog and ATF makes it exist; the two `Then` lines read it back through
the same adapter and compare a field you named. ATF provides those steps to every suite.

The second scenario is the other half. Listing projects is an action against *your* API, and "is
listed" is a claim about what came back rather than about the resource itself — so both are yours,
in `specs/steps/test_accounts.py`. Knowing which half a line falls in is most of writing a suite.

## See what does not exist yet

Ask ATF what is in the environment:

```sh
atf status dev
```

```
  accounts.primary  absent
  projects.alpha    absent

0/2 present in dev
```

Both resources are **absent**. The stand-in API is running but empty; nothing has been created.

`atf status` is read-only — it looks, and never provisions. It is the cheapest question you can ask
about an environment, and the one to start with when something is wrong.

## Run the suite

```sh
atf run
```

```
  [ passed] specs/steps/test_accounts.py::test_a_project_is_created_under_its_account  0.02s
  [ passed] specs/steps/test_accounts.py::test_a_project_is_listed_under_its_account   0.02s

2 passed, 0 failed, 0 skipped, 0 errored in dev
```

You have run your first tests, and they passed.

Notice what you did not do. You never told the test to create an account. The scenario said
`Given the account "primary"`, so ATF resolved that to the catalog node, saw that
`projects.alpha` depends on it, created the account first, substituted its real identity into the
project, created the project, and only then ran the `When` and `Then` lines. That sequence is the
whole idea, and it is written out in [Life of a run](../explanation/life-of-a-run.md).

!!! note "The stand-in forgets"

    The scaffolded stand-in API keeps everything in memory and lives only as long as the command
    that started it. So `atf status dev` still reports both resources absent, even straight after a
    run that created them. Against a real service they share one backend, and the second run finds
    what the first one made — that is [lesson 2](point-atf-at-your-api.md).

## Add a resource of your own

Add a second account. Open `catalog/accounts.yaml` and add this at the end:

```yaml
secondary:
  resource: account
  represents: A second account, to prove one account's projects stay its own.
  body:
    email: secondary@example.com
```

That is all it takes — no code, no registration step.

Check that ATF sees it:

```sh
atf status dev
```

```
  accounts.primary    absent
  accounts.secondary  absent
  projects.alpha      absent

0/3 present in dev
```

Three resources now. If you had made a mistake — a typo in the type name, a dependency that does not
exist — this command would have exited 2 and listed **every** problem it found, not just the first.

## Write a scenario that uses it

Open `specs/features/accounts.feature` and add this scenario at the end, indented like the one above
it:

```gherkin
  Scenario: A new account has no projects
    Given the account "secondary"
    When I list the projects of the account
    Then no projects are listed
```

The `Given` and `When` lines already work. The `Then` line is new vocabulary, so write it. Open
`specs/steps/test_accounts.py` and add:

```python
@then("no projects are listed")
def _(context):
    assert context.result == []
```

`context` is the [scratchpad](../explanation/glossary.md#context) the steps share: the `When` step
put the API's answer there, and your `Then` step reads it back.

Run the suite:

```sh
atf run
```

```
  [ passed] specs/steps/test_accounts.py::test_a_new_account_has_no_projects          0.01s
  [ passed] specs/steps/test_accounts.py::test_a_project_is_created_under_its_account  0.02s
  [ passed] specs/steps/test_accounts.py::test_a_project_is_listed_under_its_account   0.02s

3 passed, 0 failed, 0 skipped, 0 errored in dev
```

Three tests, all green — one per scenario. Count what you wrote: one YAML block, three lines of
Gherkin, one assertion. The account was created for you.

## What you have done

- Declared a resource as data, with no code.
- Written a scenario in plain English that named that resource.
- Watched ATF create the resource and its dependency before the test ran.
- Added a second resource and a second scenario, and seen both picked up with no registration.

## Where to go next

- **[2. Point ATF at your own API](point-atf-at-your-api.md)** — the next lesson: swap the stand-in
  for a real service, and see find-or-create do its job.
- [Life of a run](../explanation/life-of-a-run.md) — exactly what happened between `atf run` and
  the first `When`.
- [Glossary](../explanation/glossary.md) — the words this lesson used, defined once.
