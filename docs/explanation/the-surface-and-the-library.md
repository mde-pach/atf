# The surface and the library

> Not required reading. This essay is for somebody who has already used ATF and wants to know why it
> is like that.

ATF used to call its two ways of writing a test peers: *pick per test and mix them in a suite*. That
sentence cost more than any other in the documentation, and this page is what replaced it.

## What was wrong was *peers*, not *Python*

If product and QA read the scenarios as the spec, then every test written in Python is a hole in the
spec, and a suite with holes in its spec is not delivering the thing the scenarios were for. Two
surfaces also means the answer to "where is that test" is permanently "the other one" — which the
old page conceded, and then asked the team to solve with a written-down convention. **A convention
that has to be written down is a design that did not close.**

So there is one surface now. But the distinction that page missed is the useful one:

- **A surface** is where the spec lives. It is what `atf edit` renders, what the editor lists, what
  product reads, what the suite is understood to be. Two of these is the problem.
- **A library** is ATF's concepts, importable. Things as fixtures, resolution, environments, the
  shipped systems. A developer who wants an opinionated test framework instead of building every one
  of these themselves gets one, and does not have to write a sentence to get it.

The library is not a concession. It is most of the value ATF has already built and used to hide.
Everything under a scenario is resolution and spans already; refusing to expose them would be
refusing to ship the thing that works.

```python
def test_two_lists_never_collide(groceries: TodoList, other: TodoList = needs()):
    ...
```

Same resolution, same lifetimes, same environment, same teardown. What it does not get is a second
assertion vocabulary, a second reporting path or a second way to arrange anything — it uses plain
`assert`, because those are *your* tests and ATF is not pretending to have written them.

A property test, a load test, a fuzz loop, a migration rehearsal: these are genuinely not
prose-shaped, and telling somebody to render one as Gherkin so it counts is how a framework earns
the reputation the scenarios were supposed to avoid.

## The boundary has to hold mechanically

If the library is good, teams drift back into writing tests with it, and two surfaces return by
accident. Convention will not hold that line.

**So do not forbid it. Count it.**

```console
$ atf plan

  147 scenarios
    8 python tests using atf resources        ← not in the spec
```

The hole in the spec is a number, in the output everyone already looks at, next to the thing it is a
hole in. A team that sees `8` and shrugs has made a decision. A team that sees it climb to `60` has
been told, by the tool, in time. That is stronger than a rule, because nobody has to remember it and
nobody has to enforce it.

The split is Playwright's: `@playwright/test` is the framework, `playwright` is the library, and
nobody confuses which one their suite is made of.

## What it costs

Visible is not prevented. A team under deadline will write the eighth, the ninth and the twentieth,
and the number will be the only thing that objected. That is the trade taken on purpose — a rule
that forbade it would be routed around by worse means — but it is the failure mode to watch, and the
number is the instrument for watching it.

## One resolver, not two

There is a second danger here, and it is quieter. **Pytest fixtures already are a dependency
injection system**, and it is the one that owns lifetime. If `needs()` became a second container
running beside it, ATF would have rebuilt exactly the failure this page exists to prevent: two
arrangement paths that agree today and disagree about teardown order next quarter, failing in a
different test, in a different file, on a run that did nothing wrong.

So the rule is not negotiable: **a fixture request delegates to the resolver, and never runs beside
it.** If a thing can be produced by a path pytest did not schedule, the whole guarantee is gone —
and the symptom would arrive a quarter later, in an unrelated test, as residue.

The test for whether the implementation held is a scenario ATF writes about itself: a thing created
for a scenario and the same thing created for a Python test must be the same object, in the same
span, torn down at the same moment. That scenario is load-bearing.
