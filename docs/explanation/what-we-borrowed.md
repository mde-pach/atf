# What we borrowed

Most of ATF is other people's work. The Given/When/Then, the fixture rule, the way a button is named,
the report format, the semantics of `null` in a patch — none of it is ours. A reader who already
holds a concept does not have to be taught it, and that is how a design capped at twenty-seven
concepts affords a scenario language, an engine, an interface vocabulary and a report format at once.

## The rule

Every borrowed concept is honoured strictly. Not adapted, not extended, not improved.

The reason is about the reader rather than about purity. If ATF's `scope="session"` meant something
slightly different from pytest's session scope, a reader arriving from pytest would not be ignorant
of ATF — they would be *wrong* about it, and confidently. Ignorance is cheap to fix, because the
person looks it up. Being wrong is expensive, because the person does not. So bending a borrowed
concept costs more than inventing one.

## What was taken

**Gherkin**, for the scenario language. Given, When, Then, tags, `Scenario Outline` and its
`Examples`, in a `.feature` file that any Gherkin parser will read. ATF adds no keyword. Where it
needed something Gherkin does not have — a reusable sentence — it built it from parts Gherkin already
has: a [phrase](../reference/act.md#phrase) is a scenario with a tag.

**pytest**, for the engine. A resource is a pytest fixture — not "fixture-like", not "inspired by".
Asking for one is pytest's own rule, that the parameter name resolves and the annotation types. That
is what makes `scope="function"` and `scope="session"` mean what you think, and why every pytest tool
works on an ATF suite unported.

**ARIA roles and accessible names**, for the interface vocabulary.

```gherkin
When I click the button "Pay now"
Then the heading "Order summary" is showing
```

A role and an accessible name, which is what WAI-ARIA defines and what a screen reader announces.
Nothing addresses an element by CSS class, XPath or test id, so a test written this way is also an
accessibility claim: if ATF can find the button by its name, so can somebody using a screen reader,
and if it cannot, that is a finding rather than a flaky selector.

**OpenLineage**, for the vocabulary of what depends on what. ATF's
[lineage](../reference/arrange.md#lineage) is `depends_on` — dbt's `ref()`,
written as an annotation — and the graph it produces is described in the terms data tooling already
uses, so a team with a catalogue does not have to learn a private format.

**CTRF**, for the run report: `atf run --report ctrf:out.json`. The incumbent is JUnit XML, which has
nowhere to put a screenshot, no notion of a step, and a schema shaped like a Java test suite from
2003. CTRF is JSON, with tests, steps and attachments — what a scenario produces. The file ATF writes
is a CTRF file, so any CTRF reader renders it and `atf import-run` reads one back. It is also the
only format that ships: JUnit XML is registered the way an adapter is, and it is the worked example
in [extending ATF](../reference/extending-atf.md).

**JSON Merge Patch**, RFC 7386, for the semantics of `null` when a test varies a resource:

```gherkin
Given the todo_list "groceries" but "slug" is "weekly"
And "owner" is "null"
```

`null` removes the field rather than setting it to null. That is merge patch's rule, unaltered. It
surprises people once, and the surprise has an answer that is not ATF's opinion: the same rule holds
in every API the reader has ever patched.

## The one thing on offer that ATF declined

**A scenario is sentences. Nothing else.**

No pipe tables. No `"""` DocStrings. No YAML or JSON embedded in a step. Gherkin offers all of them,
every tool in the family supports them, and ATF takes none. The single exception is `Examples` under a
`Scenario Outline`, which stays because it is genuinely rows of one shape.

Strictness is about not *redefining* what you take; it is not a duty to take everything. A reader who
knows Gherkin and finds no data table has lost nothing; a reader who finds one that behaves
differently from Cucumber's has been misled.

Structured blocks inside a scenario are hard to write, hard to read and hard to maintain. A table has
a column order, an alignment and a quoting rule, and it acquires a diff nobody can review the moment
it grows past four rows. A DocString has an indentation rule and a format inside it that the Gherkin
parser knows nothing about, so the scenario is two languages with the error messages of one. Both
stop being sentences, which is the property the whole surface is built on.

Anything structured is written as several sentences instead, and when several sentences repeat they
become one [phrase](../reference/act.md#phrase) — no new syntax, because a phrase is itself a
scenario. That is why there is no whole-record claim and no whole-screen claim.

The cost is admitted. A record with fifteen fields worth asserting is fifteen lines, and a team that
wanted to paste a fixture in cannot.

## Where ATF invented

**Recognition and `unique_by`.** Declined: Terraform's state file. Identity in ATF is a question asked
of the environment on every run, not a record of what was made. The argument, at length and including
what it costs, is in [why there is no state file](why-there-is-no-state-file.md).

**`scope="persistent"`.** Two of the three scope words are pytest's. The third is not borrowed,
because there was nothing to borrow: pytest has no lifetime that outlives the process. A persistent
resource is created once and left standing, which makes re-runs cheap and recognition worth having.
The word is new so that nobody reads it as a pytest scope they half-remember.

**Markers** — `#uuid`, `#datetime`, `#absent`, `#present`, `#int`, `#str`, and a registry so a team
adds `#iban`. Declined: JSON Schema, which expresses all of this and more. A marker is not a
document; it is a value inside an ordinary sentence.

```gherkin
Then the todo_list "groceries" field "id" is #uuid
```

`#uuid` fits there and `{"type": "string", "format": "uuid"}` does not — and putting the second one in
would have required exactly the structured block the previous section refuses. The cost is admitted:
markers are much less expressive than JSON Schema, and no tool outside ATF knows what one means.
`#iban` means whatever your registry says.

**Playwright's ARIA snapshot format** is the near miss. ATF takes Playwright's vocabulary for
addressing an element and not its format for describing a subtree, because that format is a
DocString. It is a good format, and it is somebody else's file rather than a sentence.

**`when_absent`.** No standard was declined, because none exists. The nearest neighbour is Terraform's
split between a `data` block and a `resource` block — the same distinction between something you read
and something you own, spelled as one option on a decorator rather than as two kinds of block.

**System decorators** — `@sqlite(table=…, unique_by=…)`, `@browser`, `@command`. Declined: a configuration-file
mapping in the manner of Django's `DATABASES`, and a plugin entry-point registry as the surface a user
sees. Both went so that the system and its typed options sit on the class whose shape they describe,
where an editor can check them together and a reader finds them without opening a second file. What
varies per environment stays in the manifest, and the registry sits a level down: the `extensions:`
key lists the modules a suite loads —
[an adapter](../reference/extending-atf.md#registering-an-adapter), a claim, a marker, a report
format.

**`atf impact` and `atf unused`.** Nothing was declined. There is no standard for asking a test suite
what a change would break, because no test suite has held the graph needed to answer.

## The rule this leaves behind

**Any new syntax must name the standard it declined, in the document that introduces it.**

A reader who knows the declined standard can then stop looking for it. Where none exists, the page
says so: "there is no standard for this" ends the search rather than leaving the reader to assume
they have missed something. A reference page that introduces syntax without one of those two
sentences is incomplete.

## Where to go next

- **[The concept budget](the-concept-budget.md)** — borrowing is how the budget is afforded, and what
  the budget is spent on when nothing can be borrowed.
- **[Coming from another tool](../orientation/coming-from-another-tool.md)** — one short route in for each
  thing you might arrive knowing.
- **[Extending ATF](../reference/extending-atf.md)** — the three doors, and what each one obliges you
  to implement.
