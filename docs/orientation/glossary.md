# Glossary

Every concept in the model, alphabetically: what it is, what it gets confused with, and where it is
defined in full. This page is the fast lookup; [the model](the-model.md) says where each concept sits
and what it sits next to.

Two terms are used throughout and are not concepts: a **surface** is one of the two ways a test is
written, a pytest function or a Gherkin scenario; a **suite** is all the tests and resources one
`atf.yaml` describes.

## A claim you register {#a-claim-you-register}

A domain rule bound to a sentence with `@claim`, so something like "is a valid IBAN" becomes a `Then`
line. It exists because only your team knows what your domain counts as correct. It is not
[a step you write](#a-step-you-write): a step performs work and may return anything, while a
registered claim answers true or false and carries its own failure message.
[Assert](../reference/assert.md#a-claim-you-register) has the decorator's signature and the rules on
what it must return.

## A step you write {#a-step-you-write}

A Python function bound to a sentence with `@when` or `@then`, for what the built-in vocabulary
cannot say. It is reached for when no combination of existing sentences will do. That is what
separates it from a [phrase](#phrase): a phrase composes sentences that already exist and is written
in Gherkin; a step you write is Python and adds a sentence that did not exist.
[Act](../reference/act.md#a-step-you-write) shows how a step takes resources as arguments and how it
fails as cleanly as a built-in.

## Action {#action}

Changing a declared resource's field in the middle of a test:
`When the task "laundry" field "done" becomes "1"`. Nothing declares it; it reaches the adapter's
`update`, which every adapter has. A [phrase](#phrase) over it is what puts the domain's own word in
the scenario — `When I complete the task "laundry"` — instead of the change the word stands for.

It is not [running something](#running-something): an action changes a declared resource through its
system, while running something invokes the product and keeps what came back.
[Act](../reference/act.md#action) has the sentence and the phrase that names it.

## Adapter {#adapter}

The class that teaches ATF a system, shipping `find`, `create`, `update` and `delete`, and its
decorator with it. One instance is built per system per environment, so it holds its own connection.
It is not the [system](#system): the system is the decorator a resource wears, the adapter is the
class behind that decorator. `@sql.row` throughout this documentation is the worked example of an
adapter, and `@sql.row` over the `sql` driver is the one ATF ships for it.
[Arrange](../reference/arrange.md#adapter) has the full method set, the `Options` and
`Settings` split, and what raising `atf.Unreachable` means.

## Asking for one {#asking-for-one}

Naming a resource in a test signature or a scenario line, where the name resolves and the annotation
types. `primary: Owner` means that owner; `owner: Owner` means any owner. The second form is where
the [factory](#factory) comes in — asking is the request, the factory is what satisfies a request for
any of a kind. [Arrange](../reference/arrange.md#asking-for-one) explains resolution inside a
scenario versus in a plain test, and why two of a kind in scope is an error.

## Claim {#claim}

One checked statement about a resource, a result or the environment. It is the assertion, written as
a sentence. Do not confuse it with a [marker](#marker): the claim is the whole sentence, the marker is
the kind of value the sentence compares against.
[Assert](../reference/assert.md#claim) lists every built-in claim and the shapes they take.

## Environment {#environment}

A named place ATF can be pointed at, carrying one configuration block per system in play. It is what
lets one suite run against a laptop and against CI without a line of the tests changing. Whether ATF
may build anything there is a separate declaration — see [may be changed](#may-be-changed).
[The ground](../reference/the-ground.md#environment) has the manifest keys and the three states an
environment can report.

## Factory {#factory}

A `factory` classmethod that builds an instance when a test asks for any of a kind rather than a
named one. A dependency it is not given is built by that resource's own factory, recursively. It is
not a [variation](#variation): a factory invents a fresh instance, a variation bends a declared one
for a single test. [Arrange](../reference/arrange.md#factory) has the signature and how the recursion
terminates.

## History {#history}

The outcomes ATF has kept from earlier runs, which is what `atf run --failed` and `atf docs` read.
It is not a [report](#report): a report is one run written out for another tool to consume, history is
many runs kept for ATF's own commands.
[The record](../reference/the-record.md#history) says what is stored, where, and what reads it.

## Interface claim {#interface-claim}

A claim about what an interface shows, addressed by role and accessible name — `Then the button
"Pay now" is disabled`. It is the assert half of browser work; [using an interface](#using-an-interface)
is the act half. [Assert](../reference/assert.md#interface-claim) lists the roles and the claims each
one accepts.

## Lineage {#lineage}

What one resource needs to exist before it, declared with `depends_on`. Declaring it once is what
gives ATF the graph behind `atf impact`. It is not [recognition](#recognition): recognition asks
whether this thing is already there, lineage says what has to be there first.

An entry is a kind or a particular resource, and which one it is says what is meant: a kind means
any of them, a resource means that one. Where the shape has room for the parent, passing it as a
value says which — so the dependency is still written once.
[Arrange](../reference/arrange.md#lineage) shows how the closure follows it, including the case
where a resource has nowhere to put its parent and needs one anyway.

## Marker {#marker}

A kind of value where a claim would otherwise carry a literal — `#uuid`, `#datetime`, `#date`,
`#absent`, `#present`, `#int`, `#str`, `#bool`. It is for the fields a test cannot predict. Quoting
is the distinction that matters: `is "uuid"` compares with the string `uuid`, `is #uuid` requires a
UUID. Markers are a registry, so a team adds `#iban` —
[Assert](../reference/assert.md#marker) has the registration and every built-in.

## May be changed {#may-be-changed}

The `mutable` flag on an environment, false unless stated, which decides whether ATF may make
anything there. It is what keeps a suite honest against production. It is not
[when it is not there](#when-it-is-not-there) set to `require`: `mutable` is one environment's answer
about everything in it, `when_absent="require"` is one resource declaring that ATF must never build
it anywhere. [The ground](../reference/the-ground.md#may-be-changed) says what an immutable
environment still runs and what it refuses.

## Naming a result {#naming-a-result}

`as "first"` on an acting line, which puts what came back into a named slot. It is needed only when
one test does two things; otherwise the slot is `result` and nothing has to be said.
[Act](../reference/act.md#naming-a-result) shows how a later claim addresses a named slot.

## Outcome {#outcome}

What one test did in one run: `passed`, `failed` or `skipped`. It is not a [verdict](#verdict): an
outcome is one test in one run, a verdict folds many outcomes over history into a standing answer.
[The record](../reference/the-record.md#outcome) fixes the vocabulary and says why there is no
fourth word.

## Phrase {#phrase}

A tagged scenario that is vocabulary rather than a test, spanning all three verbs and allowed to
nest. It is the only compression the language has: several sentences that repeat become one sentence.
It is not [a step you write](#a-step-you-write) — a phrase is Gherkin composing sentences that
already exist, and needs no Python. [Act](../reference/act.md#phrase) has the `@phrase` tag,
placeholders, and the one flat namespace phrases share.

## Recognition {#recognition}

The field that tells ATF whether the thing is already there, `unique_by="email"`, re-read from the
environment every run. It is what makes a re-run cheap and a persistent resource worth keeping. It is
not [lineage](#lineage): lineage is what must exist first, recognition is how ATF knows this one
already does. [Arrange](../reference/arrange.md#recognition) covers identity versus lookup and the
drift trade-off you take on.

## Report {#report}

A run written out for something else to read, `atf run --report ctrf:out.json`. Only `ctrf` ships;
any other format — JUnit, Allure — is one a team registers. It is not [history](#history), which ATF
keeps for itself. [The record](../reference/the-record.md#report) has the flag, the format registry
and what a CTRF file contains.

## Resource {#resource}

A class with typed fields and a system behind it, describing one thing that must exist. Declaring it
rather than building it is what gives ATF the graph it holds. The class is not the resource: `Owner`
is the shape, `primary = Owner(email="primary@example.com")` is the resource, and constructing it
declares — it touches nothing. [Arrange](../reference/arrange.md#resource) has the declaration, the
options a system adds, and how a resource gets its name.

## Run {#run}

One execution of a suite against one environment. It is the unit an [outcome](#outcome) belongs to
and the unit a [report](#report) describes.
[The record](../reference/the-record.md#a-run) says what a run records and what it exits with.

## Running something {#running-something}

Invoking the system under test and keeping what came back — a command, a request, a click. It is not
an [action](#action): running something drives the product from outside, an action changes a declared
resource through its own system. [Act](../reference/act.md#running-something) has the sentences and
the fields the result carries.

## Scope {#scope}

How long a made resource lives: `persistent` by default and never torn down by ATF, `session` for one
run, `function` to build it per test and remove it after. It is not
[when it is not there](#when-it-is-not-there): `when_absent` decides whether ATF makes the thing at
all, scope decides how long it lasts once made.
[Arrange](../reference/arrange.md#scope) has the three lifetimes, their teardown, and why
`persistent` is the default.

## Shell {#shell}

The fixture the `command` system provides, which runs a command line through the current
environment's `prefix` and hands back `exit_code`, `output` and `ok`. It is the built-in for testing
a command line from Python, and it is what ATF uses to test its own. It is part of the `command`
system rather than a concept of its own. It is not [a step you write](#a-step-you-write): a step is
a sentence you add to the vocabulary, `shell` is what such a step calls.
[Act](../reference/act.md#shell) has the fields it returns and how `prefix` decides what the line
means.

## System {#system}

The decorator on a resource class — `@sql.row`, `@filesystem.file`, `@filesystem.directory`, `@browser.page`, `@shell.process` —
carrying that system's own typed options. It is the resource's type: the class is the shape, the
decorator says what kind of thing it is and who builds it. **A system is named after the thing, not
the technology**: `file`, `directory` and `tree` are three systems over one filesystem. Behind every
system is an [adapter](#adapter), and behind that a [driver](../reference/arrange.md#driver) holding
the machinery. A system ATF does not ship for is an adapter somebody writes.
[Arrange](../reference/arrange.md#system) lists the systems ATF ships and the options each takes.

## Using an interface {#using-an-interface}

Driving a browser by role and accessible name — `When I click the button "Pay now"`. Addressing by
role is what keeps a scenario readable and independent of markup. It is the act half of browser work;
[interface claim](#interface-claim) is the assert half.
[Act](../reference/act.md#using-an-interface) lists the sentences and the roles they accept.

## Variation {#variation}

A per-test change to a declared resource, one field per sentence, where `"null"` removes the field
from the body. It is how one test differs from the shared declaration without a second declaration
existing. It is not a [factory](#factory), which invents an instance from nothing.
[Arrange](../reference/arrange.md#variation) has the sentence form and what a variation may and may
not change.

## Verdict {#verdict}

A fold of outcomes over history — `passing`, `failing`, `skipped`, `never run` — and not a vocabulary
of its own. It answers what a test's standing is, rather than what it did once, which is an
[outcome](#outcome). [The record](../reference/the-record.md#verdict) says how the fold is computed
and where verdicts are shown.

## When it is not there {#when-it-is-not-there}

`when_absent`, which decides whether ATF makes the thing — `make`, the default — requires the
environment to supply it, or only observes it. It is how a resource that nobody can create still
takes part in the graph. Two neighbours get mistaken for it:
[may be changed](#may-be-changed) is an environment-wide flag rather than a per-resource declaration,
and [scope](#scope) governs lifetime rather than creation.
[Arrange](../reference/arrange.md#when-it-is-not-there) has the three values and what `atf status`
reports for each.

## Words that are not concepts

Two vocabularies are used exactly, and nowhere else. What an environment holds is `present`, `absent`
or `unreachable`. What a run did is `passed`, `failed` or `skipped`.

**Blocked** is in neither, and there is no blocked state. A resource that is missing gets created;
one that cannot be created fails the test. Blocked survives only as a prediction the editor makes
before a run, about a test that has not run yet.

## Where to go next

- **[The model](the-model.md)** — the same terms arranged by band, which is where you see what each
  one sits next to and why.
- **[Coming from another tool](coming-from-another-tool.md)** — each term anchored to its equivalent in
  pytest, factory_boy, Cucumber, Terraform, dbt, Playwright or Django.
