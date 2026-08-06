# The concept budget

ATF has twenty-seven concepts, arranged in five bands and five levels. The number is a budget.
Nothing is added to it without something else leaving.

## Why a budget

The real cost of a framework is not the size of its API. It is the number of things you have to hold
in your head at once to predict what will happen when you press run.

That number only grows, one reasonable addition at a time. Every feature is justified locally:
somebody needed it, it is small, it does not break anything. The argument is correct each time and
the total is a framework nobody can hold. Nothing in a normal development process makes the global
argument, because the global argument has no owner and no ticket.

A budget gives it one. To add a concept, name the concept it replaces. That converts a local question
into a comparison, and comparisons can be lost.

## The bands

Five. Three are the verbs a test performs; two frame them.

The ground holds two: environment and may be changed. Arrange holds ten — resource, asking for one,
factory, system, recognition, when it is not there, scope, variation, lineage and adapter. Act holds
six: action, running something, using an interface, phrase, a step you write and naming a result.
Assert holds four — claim, marker, interface claim and a claim you register. The record holds the
last five: run, outcome, verdict, history and report.

Ten of the twenty-seven sit in Arrange alone, and that asymmetry is the design rather than an
accident of counting. Act and Assert are generic and well-trodden; ATF does them well and they are
not the argument. Arrange is where the bet lives, so it is where the spending is allowed.

## Levels are boundaries, not audiences

A level is the point at which a concept first becomes necessary. It is not a kind of person.

The same person is at level 1 on Monday, running a suite somebody handed them, and at level 5 on
Thursday, teaching ATF about Redis. An agent working through `atf edit --mcp` operates at whatever
level the task requires and does not climb in order at all.

What a level is for is to let a page refuse to say something. A level-2 page may not mention an
adapter. That is a constraint on the writer, and it is enforceable, which "keep it simple" is not. It
also works as a detector: where a page genuinely cannot be written inside its level, the model is
wrong, and the fix is to the model rather than to the sentence.

That detector has fired five times, and every time the model moved. Each move was found the same way:
somebody sat down to write a page, discovered that the honest version of a paragraph needed a word
their level did not have, and said so. Not one was found by inspecting the model. A rule that only
fires when somebody audits the table is a rule nobody is running.

## What each level costs

**Level 1 · Run** — environment, may be changed, resource, lineage, claim, run, outcome, verdict,
history. Nine, and the largest level.

What you must accept in order to read a red line and know whether to worry. Three of these look
premature and are not. `resource` is here because the commands a level-1 reader runs are about
resources rather than about tests: `atf status` lists them. `may be changed` is here because the same
command prints it — `mutable` is false unless stated, so every working manifest carries the word —
and a reader without it cannot tell a suite that will provision from one that will only look.
`lineage` is here because the first surprising thing about a run is that a test got an owner nobody
mentioned.

Nine is a lot to hand somebody on their first afternoon. The defence is that they are handed by the
output rather than by a page: every one is a column, a word in a message, or a line in a report the
reader is already looking at.

**Level 2 · Write** — asking for one, running something, phrase, naming a result, marker. Five.

Everything needed to write a test against resources that already exist, and none of the machinery
that puts them there. You can write a test that asks for `groceries` without knowing how `groceries`
is declared, which system it belongs to, or that a factory could have built one. That omission is
what makes the boundary between levels 2 and 3 real rather than a chapter break.

**Level 3 · Declare** — factory, action, variation, system, recognition, using an interface,
interface claim. Seven concepts.

The level that matters most, and the level that grew. Levels 4 and 5 are climbed once per team,
usually by one person. Level 3 is climbed by everyone, repeatedly, for as long as the project exists
— every feature that introduces a new kind of thing is a trip up this rung.

A framework that makes level 3 expensive is a framework people bounce off, and they do not bounce off
loudly. They hard-code a row. They write a setup function. They copy a resource that is nearly right
and edit two fields. Each is a rational local decision and each removes a piece of the graph, and a
graph that is quietly incomplete is worse than none, because `atf impact` will still answer
confidently.

It was defended at four for a long time and it is seven now. Nothing was added: the total is still
twenty-seven, and the three that arrived came from neighbouring levels, pulled by writers who could
not describe a declaration without them. `system` and `recognition` came down from level 4, where
they sat with configuration, because `@sqlite(table="owners", unique_by="email")` is on the first line of every
declaration anybody writes. `using an interface` and `interface claim` came up from level 2, because
both need `@browser` on a class and the level-2 pages had to show a decorator they were forbidden to
name.

Four was never a measurement of what declaring costs. It was a measurement of what four pages had
managed to avoid saying. The number that would show the rule failing is the total: a level that grows
while the total holds is a map being redrawn over the same ground, and a level that grows because the
total grew is the thing the budget exists to catch. What did die is a claim ATF used to make — that
declaring a resource costs four ideas. It costs seven, four of them visible on the class you type.

Every candidate for a genuinely new concept here collapsed into one that already existed. A
dependency is a typed field, so it is `lineage`, already spent at level 1. A default value is the
factory. Configuration sits on the system's decorator, or in the manifest at level 4.

**Level 4 · Connect** — when it is not there, scope, report. Three.

Pointing ATF at real systems. This is where expense is allowed to sit, because it is paid by the
fewest people the fewest times. It got smaller when `may be changed` and `recognition` went down, and
what it kept of both is the harder half: what an immutable environment still runs, and why choosing a
key to be recognised by is not the same as looking a thing up. `when it is not there` stays here
whole, because it is the idea that most changes what a newcomer expects.

**Level 5 · Extend** — adapter, a step you write, a claim you register. Three.

Three doors, and the fact that there are exactly three is itself a budget decision. Each one is an
admission: the model could not express something, so here is the way out. Three obvious doors are
better than a dozen configuration options that quietly do the same job while pretending not to be
escape hatches.

## What "something leaving" looks like

When something new is proposed, one of three things happens.

It **collapses** into an existing concept — a new option on `@sqlite` is not a new concept, because
configuration belongs to the system. Most good proposals end here.

It **replaces** one, and the replaced concept is then removed from every page it appears on rather
than deprecated and left. A deprecated concept still costs a reader the whole price, because they
have to work out whether it applies to them.

Or it is **refused**. This is the common case and it should be.

## Three that left

The count came down from thirty. None of the three was cut for being unloved. Each turned out to be
already covered, which is the only kind of removal a user does not pay for.

**Your own client.** ATF used to carry a concept for the client a suite uses to drive its product,
with a `clients:` key in the manifest. It went because that client is a fixture the suite writes, in
Python, against its own library. The manifest configures systems ATF talks to, and the thing you
built to talk to your product is none of its business.

**The whole-record claim.** A claim about the shape of an entire record, written as a block under a
`Then`. The evidence against it was blunt: ATF's own suite of 211 scenarios used it exactly zero
times. What people write is a handful of field claims, one per line, and when the same handful
repeats they wrap it in a [phrase](../reference/act.md#phrase) — already in the budget, needing no
new syntax. `#uuid` and the other markers survive untouched, because they were never part of the
block.

**The interface claim over a whole screen.** The same idea for a page rather than a record: a
snapshot of a region, pasted in as a block. Removed for the same reason and replaced by the same
thing.

The last two left together, and they took something larger with them: every structured block inside a
scenario. That rule now stands on its own, and the argument for it is in
[what we borrowed](what-we-borrowed.md).

## What the budget costs

ATF will refuse things you want, and some of those refusals will be wrong. The asymmetry is
structural: the marginal feature is always worth more to the person asking for it than the marginal
concept is worth to everybody else, and the person asking is the only one in the room. A budget
overcorrects on purpose.

The escape hatches keep a refusal from being a dead end. What ATF will not add to the model, you can
add to your suite — at the cost of that part of your suite being invisible to the graph. That is the
same trade named in [declared, not executed](declared-not-executed.md), charged in a different
currency.

The level rule costs the writer too. A level-2 page explaining why a test received an owner it did
not ask for has to do it with `lineage` and without a factory or a system, and the sentence comes out
longer than it would with the whole vocabulary available. Harder to write, cheaper to read; a page is
written once.

## What else was on the table

**No budget.** The usual arrangement: the framework grows, the documentation grows to match, and the
concept count is discovered years later by counting the glossary. Declined for the reason at the top
of this page — there is no point in the normal process at which anybody is responsible for the total.

**Levels as audiences** — "ATF for QA", "ATF for developers", a beginner mode and an advanced mode.
Declined because it splits by job title an artifact that is not split that way: a suite is one thing,
and the same file is read by all of them. Tiered documentation also teaches people that half of it is
not for them, which is exactly the half they need on the Thursday they end up at level 5.

## Where to go next

- **[The model](../orientation/the-model.md)** — the twenty-seven, each named once and placed beside
  the ones it sits with. The page this budget is a budget for.
- **[What we borrowed](what-we-borrowed.md)** — how the budget is afforded, and what a borrowed
  concept spares the reader.
- **[Declared, not executed](declared-not-executed.md)** — what level 3 buys for its seven concepts,
  and what the ceiling costs on the day you reach it.
