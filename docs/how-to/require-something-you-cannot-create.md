# Require something you cannot create

Declare a resource that the environment owns — a plan, a feature flag, a region — so that its absence
fails the tests that need it by name, instead of producing a failure somewhere else.

## The shortest path

Declare it with `when_absent="require"`.

```python
# resources.py
from adapters.todo import todo


@sql.row(table="plans", unique_by="code", when_absent="require")
class Plan:
    code: str


pro = Plan(code="pro")
```

Ask for it the same way you ask for anything else.

```gherkin
Scenario: a pro owner may keep more than one list
  Given the plan "pro"
  And the owner "primary"
  When I run "todo add primary@example.com groceries"
  And I run "todo add primary@example.com books"
  Then the environment has 2 todo_list
```

ATF now reads `plans` and never writes to it. If the `pro` row is there, the scenario runs. If not,
the scenario fails on the plan rather than on anything it asserts.

```text
FAILED specs/plans.feature:3  a pro owner may keep more than one list
  Plan "pro" is absent in staging and may not be created (when_absent="require")
```

A resource that cannot be made is a failed test. There is no third result. The failure arrives before
the first `When`, naming the row and the environment.

The default is the opposite — make it when absent. See
[when it is not there](../reference/arrange.md#when-it-is-not-there) for all three values, and
[Every failure names your sentence](../explanation/every-failure-names-your-sentence.md) for the rule
this is an instance of.

The trade-off: every test whose closure reaches `pro` fails, so one missing row turns a whole report
red at once. That is deliberate, because a result that is quiet stops being read.

## What `atf status` shows

`atf make` fills what it may and leaves the required row alone.

```console
$ atf status staging
resource   instance    state
Plan       pro         absent     required — the environment must supply it
Owner      primary     absent

$ atf make staging
Plan pro         left alone — required
Owner primary    created
```

There is no `atf status` step to add to a pipeline: an absent required resource fails the test that
needs it and `atf run` exits `1`. Reach for `atf status` when you want to know *before* you spend a
run, or when you are filling a new environment by hand.

## How it differs from `observe`

Both mean ATF will not create the thing. They differ in what absence means.

`require` is for something a test cannot proceed without: the plan, the region the account lives in,
the feature flag that has to be on. Its absence is a defect in the environment, so it fails the tests
that need it, naming the row.

`observe` is for something you look at rather than depend on. A screen is the clearest case: it is
not a record anyone provisions, and whether it is showing is what a test wants to claim.

```python
from atf import browser


@browser.page(when_absent="observe")
class Screen:
    path: str


checkout = Screen(path="/checkout")
```

An observed resource that is absent fails nothing on its own. The test runs, and `Then the words
"Payment received" are showing` is made against what is actually there. Use `require` when absence is
the environment's fault, and `observe` when absence is a legitimate answer to the question the test is
asking. The default, `make`, is neither: the resource will exist by the time the test runs.

## When it goes wrong

**The whole suite is red in a fresh environment.** Something is marked `require` that a test could
reasonably create. `require` is for what the environment owns, not for what is inconvenient to set up.
If you can write the row, drop `when_absent`.

**`Plan: a required resource may not have a factory`.** A factory builds a declaration so that ATF can
create the record. A resource ATF will never create has nothing to build. Remove one or the other.

**`atf status` says `unreachable`.** That is not absence. The system did not answer — wrong path,
wrong URL, no credentials — and ATF cannot tell whether the plan is there. Fix the connection first;
see [environment](../reference/the-ground.md#environment).

**Required locally, provisionable in CI.** The same declaration applies to every environment. If a
local database really should be seeded by the suite and staging really should not, seed the local one
outside ATF — a migration, a fixture script — and keep the declaration honest about who owns the row.

## Where to go next

- [Configure an environment](configure-an-environment.md) — where the credentials and paths that
  decide `absent` from `unreachable` are set.
- [Work out why it is red](work-out-why-it-is-red.md) — telling an assertion failure apart from a
  resource that could not be made.
- [Arrange](../reference/arrange.md#when-it-is-not-there) — the three values in full, and how each one
  behaves under `atf make`.
