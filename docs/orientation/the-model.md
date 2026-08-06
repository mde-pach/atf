# The model

The whole of ATF on one page. Five bands, 27 concepts, and how they fit together. Every concept name
links to its one-line definition in the [glossary](glossary.md), which is where the definitions live;
this page is the shape.

Three of the bands are the verbs a test performs — Arrange, Act, Assert. Two frame them: the ground
a test stands on, and the record it leaves behind.

- **[The ground](#the-ground)** — environment · may be changed
- **[Arrange](#arrange)** — resource · asking for one · factory · system · recognition · when it is
  not there · scope · variation · lineage · adapter
- **[Act](#act)** — action · running something · using an interface · phrase · a step you write ·
  naming a result
- **[Assert](#assert)** — claim · marker · interface claim · a claim you register
- **[The record](#the-record)** — run · outcome · verdict · history · report

**Arrange is not a peer of the other two.** It is where the thesis lives: preconditions declared as
typed data rather than executed as setup code, and the graph that buys. Act and Assert are generic
and largely table stakes.

## The ground

Where a test stands. Everything in this band is configuration, and all of it lives in `atf.yaml` —
five top-level keys, `resources:`, `specs:`, `extensions:`, `default_env:` and `environments:`, and
that is all of them.

An [environment](glossary.md#environment) is what the other four keys are pointed at: `local`,
`staging`, one configuration block per system in play. [may be changed](glossary.md#may-be-changed)
is the same environment seen from ATF's side — the `mutable` flag, false unless stated, deciding
what ATF is permitted to do once it gets there. Every band below happens inside one of these, and
which one is an argument.

## Arrange

What must exist before the test means anything. ATF ensures the declared state: it looks for the
thing, creates it when nothing is there, and updates it when what is there differs. A declaration is
a partial specification — the fields you named must hold, and the fields you did not name are left
alone.

A [resource](glossary.md#resource) is the centre of the band and the rest are angles on it. Its
decorator is its [system](glossary.md#system). One of its fields is its
[recognition](glossary.md#recognition). What it needs to exist first is
[lineage](glossary.md#lineage), written in `depends_on`, so the closure follows the declaration
rather than the shape. [when it is not there](glossary.md#when-it-is-not-there) settles what happens when
recognition finds nothing, and the default is to make it. [scope](glossary.md#scope) settles how long
what was made lives, `persistent` unless you say otherwise.

Three more are what a test does with all that. [asking for one](glossary.md#asking-for-one) names a
resource in a test signature or a scenario line — by name for a particular one, by type for any. A
[factory](glossary.md#factory) answers the second kind, and builds the dependencies it was not given
by calling their factories in turn. A [variation](glossary.md#variation) bends a declared resource
for one test, one field per sentence.

Underneath all of it, an [adapter](glossary.md#adapter) is what teaches ATF a system and ships that
system's decorator with it. ATF ships four systems — `@command`, `@browser`, `@filesystem` and
`@process` — so every other one a suite uses is an adapter somebody wrote. A suite uses one for a
long time before anybody writes one.

## Act

The one thing the test does. A scenario is sentences and nothing else — no pipe tables, no
DocStrings, no embedded YAML. Anything structured is written as several sentences, and when several
sentences repeat they become one phrase.

Three of these are ways of acting, and they differ only in what they touch:
[running something](glossary.md#running-something) invokes the system under test,
[using an interface](glossary.md#using-an-interface) drives a browser, and an
[action](glossary.md#action) is a domain verb a resource declares so a scenario can say it. Whatever
comes back lands in a slot called `result`, and [naming a result](glossary.md#naming-a-result) is
needed only when one test does two things.

The other two are how the vocabulary grows. A [phrase](glossary.md#phrase) is written in Gherkin and
is itself a scenario, so it needs no new syntax; it is the only compression the language has.
[a step you write](glossary.md#a-step-you-write) is the same growth in Python, for what sentences
cannot reach. Reach for the phrase first.

## Assert

What has to be true afterwards. Quotes mean a literal value and `#` means a kind, so
`field "slug" is "groceries"` compares a string and `field "id" is #int` requires an integer. There
is no whole-record claim and no whole-screen claim: assert the fields you care about, one sentence
each, and make a phrase when the set repeats.

A [claim](glossary.md#claim) is the unit — one `Then` line, one field. An
[interface claim](glossary.md#interface-claim) is that same unit aimed at a screen rather than a
record. The other two are where a claim stops being fixed: a [marker](glossary.md#marker) is what a
claim carries when a literal will not do, and markers are a registry, so a team adds `#iban`;
[a claim you register](glossary.md#a-claim-you-register) extends the sentence itself, so "is a valid
IBAN" becomes something a scenario can say.

## The record

What a run leaves behind, and what the next run reads.

A [run](glossary.md#run) is one execution against one environment, and it produces one
[outcome](glossary.md#outcome) per test. [history](glossary.md#history) is the outcomes ATF kept
from the runs before, which is what `atf run --failed` and `atf docs` read. A
[verdict](glossary.md#verdict) is a fold of that history rather than a vocabulary of its own. A
[report](glossary.md#report) is the same run written out for something else to read, and only `ctrf`
ships — JUnit, Allure and the rest are formats a team registers.

### There are exactly two vocabularies

What an environment holds is `present`, `absent` or `unreachable`. What a run did is `passed`,
`failed` or `skipped`. A verdict is a fold of the second, not a third. The first three are
information, and `atf status` reports them as information: it never gates, exiting `0` or `2` and
never `1`.

**There is no blocked state.** A resource that is missing gets created; one that cannot be created
fails the test. Blocked survives only as a prediction the editor makes before a run.

## The three faces

Every concept is met in three places, and its reference page says all three. **In CI** it is
non-interactive and binary: `atf run --report ctrf:out.json`, an exit code, a file for something else
to read. **In the editor** it is exploratory and local: `atf edit` draws the graph, inspects a
resource, re-runs one scenario. **To an agent** it is the same thing structured — `atf edit --mcp`
serves the graph and the record as tool calls rather than pixels.

One engine seen from three angles. A concept with nothing to say for a face says so.

## Where to go next

- **[Coming from another tool](coming-from-another-tool.md)** — the same map anchored to pytest fixtures,
  factory_boy, Cucumber, Terraform, dbt, Playwright and Django.
- **[Glossary](glossary.md)** — where every definition on this page comes from, alphabetically, for
  when you have a word and want its meaning rather than its place.
- **[Run a suite](../tutorial/1-run-a-suite.md)** — hands on the keyboard, against a suite that
  already exists, for when the map has been enough map.
