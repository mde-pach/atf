# The concept budget

> Not required reading. This essay is for somebody who has already used ATF and wants to know why it
> is like that.

ATF has thirteen concepts, in four bands. The number is a budget, and the budget is the design.

| Band | Concepts |
| --- | --- |
| The ground | environment · owner |
| Arrange | thing · system · `needs` · known · lives |
| Act & Assert | a sentence · a kind · teaching a sentence |
| The record | run · outcome · history |

It used to be twenty-seven. What follows is the rule that took it to thirteen, and — more usefully —
the thing the count was hiding.

## The count was never the measure

The number that mattered was not twenty-seven. It was the number of paragraphs in the glossary that
began **"It is not X:"** — there were about twenty, and each one was a reader being told that two
things they could not tell apart were different.

A concept budget caps how many concepts there are. It does not cap how *confusable* they are, and
confusability is what a reader actually pays. Three of those paragraphs survive:

- a phrase and a word you write
- recognition and lineage
- a scenario and a Python test

A glossary with three of them does not need to be a glossary, which is why there is no longer one.

## The two rules

**To add something, name what it replaces.** Every concept has to earn its slot against a concept
already there. This is what makes the budget bind: an addition is a trade rather than an increment.

**To refuse something, name what covers it.** An unanswered question is where people invent their
own thing. `Examples:` tables and `Background:` are both refused, and both refusals print the phrase
that covers them, at the line that wrote them.

## What the cuts spent

Fourteen concepts went, and almost none of them went by deletion. They went because a distinction
stopped being real:

- **lineage vs factory vs asking for one** — three altitudes of *given a hole shaped like an
  `Owner`, how do I get one?* Answering it once, at the hole, answered all three. That is `needs()`.
- **variation vs factory** — "a factory invents a fresh instance, a variation bends a declared one"
  stopped meaning anything once resolution took arguments.
- **`when_absent` vs `may be changed`** — the same question asked at two altitudes: who is
  responsible for this existing? One word, two values, two places.
- **`scope`** — nobody picks one now; it is read off the suite. A concept you cannot type is not a
  concept you have to learn.
- **adapter vs system vs driver** — three names for one thing a team writes once.
- **`@then` vs `@claim`** — both take values and answer true-or-false with a message. They were
  split by the author's intent, not by the code.
- **outcome vs verdict**, **report vs history**, **a result slot vs a named one**, **quoted literal
  vs `#marker`**, **running vs acting vs using an interface**, **a test surface vs a peer surface**.

Four more stopped being concepts without being removed at all. Running something, clicking, an
interface claim and changing a field mid-test are all **a system's own words** — entries in that
system's reference, met the first time you use it. None of them has to be held in your head to
predict what a run will do. They have to be *looked up*, which is what a reference is for and what a
model is not.

## Levels stopped needing to be taught

There used to be five levels, and a rule that a page must not mention a concept a reader had not
reached. The rule existed because there were enough concepts that mentioning them out of order was a
real hazard.

With thirteen, and four of the hardest recast as per-system lookups, the refusals mostly stop
binding. Levels survive as a writer's discipline; they stopped being something the documentation
explains to a reader.

One part of it is still enforced, because it is the part that would rot silently: **a link from one
of the four required pages into an essay is a build failure.** If an argument has leaked out of the
page that owed it, that is the page to fix. `scripts/prose.py` gates it.

## What the budget costs

**A concept that would have been useful is refused.** `unique_by=` would have been convenient and
was cut, because uniqueness is structure the system already holds. A team whose system genuinely
cannot answer now writes it on the decorator instead — one more place to look, in exchange for one
fewer thing to know.

**Per-system words are harder to discover than a band in the model.** "What can I say?" used to be
answered by reading two pages. Now it is answered by [a generated
reference](../reference/sentences.md) and by `atf edit`, which is better when the tooling is in
front of you and worse in a code review, a terminal or a diff. `atf run` carries the load: an
unrecognised sentence says what it did not match, what is close, and which system would have to
bring the word.

**Thirteen is not a target.** It is what the trades came to. A fourteenth that pays for itself is
welcome; a fourteenth that is merely useful is not.

## Read next

- **[The model](../model.md)** — the thirteen, each named once and placed in a band.
- **[The surface and the library](the-surface-and-the-library.md)** — the one distinction that is
  counted rather than forbidden.
- **[What we borrowed](what-we-borrowed.md)** — where the surviving concepts came from.
