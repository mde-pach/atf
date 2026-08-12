# The dreamt ATF

The thesis is right and nothing about it is what makes ATF hard to use. **Preconditions declared as
data rather than executed as setup code** is a real differentiator, and it is currently competing for
the reader's attention with a dozen decisions that are not the differentiator.

This document is about the competition, not the thesis.

## One question, one answer

The complaint is that there are too many ways to build the same thing. Here is the complaint,
counted.

| The question a user has | Answers today | In the dream |
| --- | --- | --- |
| Where does the spec live? | 2 — a pytest function or a scenario | 1 — a scenario, with a library beside it |
| How do I get a thing I need? | 3 — `depends_on`, `factory`, asking | 1 — `needs()` |
| How do I teach it a word? | 5 — `@when`, `@then`, `@claim`, `@check`, `@phrase` | 2 — `Phrase:`, `@act`/`@check` |
| How do I say what must exist? | 3 knobs, 18 combinations — `when_absent` × `mutable` × `scope` | 2 — `owner`, `lives` |
| What is the extension point called? | 3 — adapter, system, driver | 1 — system |
| How do I refer to what came back? | 2 — the `result` slot, or `as "name"` | 1 — `it` |
| Which command answers "why"? | 4 — `impact`, `unused`, `why-red`, `history` | 1 — `explain` |
| How many commands are there? | 15 | 6 |
| How many files does the manifest register? | 3 keys of paths | 0 — discovery |
| How many pages must I read? | ~40, tiered by level | 4, then optional depth |

The count that matters is not twenty-seven. It is the number of paragraphs in the glossary that
begin **"It is not X:"** — there are about twenty, and each one is a reader being told that two
things they cannot tell apart are different. A concept budget caps how many concepts there are. It
does not cap how confusable they are, and confusability is what a reader actually pays.

The dream has three, which is few enough that the glossary stops being a glossary.

---

## A whole suite, on one screen

```
myapp/
  atf.yaml
  atf/
    things.py        the nouns
    words.py         the words ATF did not ship
    lists.feature    the tests
```

Four files. No key in the manifest points at any of them — ATF finds `atf/` the way pytest finds
`conftest.py`. `resources:`, `specs:` and `extensions:` are deleted.

### `atf.yaml`

```yaml
environments:
  local:
    owner: atf                      # ATF may make things here
    sql:   { path: ./local.db }
    shell: { prefix: todo }

  staging:
    from:  local                    # everything above, then the differences
    owner: them                     # ATF may only look
    sql:   { url: postgres://reader@staging/todo }
```

Two keys, and one of them is a name. `default_env` is gone — the first environment is the default,
and `--env` overrides it. `from:` exists because the only repetition left in a manifest is the
second environment restating the first, and a reader should be able to see what makes staging
different by reading what staging says.

### `things.py`

```python
from atf import needs, sql


@sql.row(table="owners")
class Owner:
    email: str


@sql.row(table="lists")
class TodoList:
    owner: Owner = needs()          # this is the edge
    slug: str


primary   = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

A domain class with one framework word in it. `needs()` earns the default slot because "how do I get
one if nobody gave me one" is what a default *is*. Nothing else in the class belongs to ATF.

`depends_on=[Owner]` is gone, and what replaces it is not inference. It is a dependency declared
where the dependency is used — the FastAPI/`fast-depends` shape, and the right one for ATF for a
reason that goes past tidiness. See [Resolution is one mechanism](#resolution-is-one-mechanism).

### `lists.feature`

```gherkin
Feature: lists belong to their owner

Scenario: a list shows under its owner
  Given the list "groceries"
  When I run "todo show primary@example.com"
  Then it mentions "groceries"
```

---

## What ATF is allowed to know

Two rules govern every cut below, and they are worth stating first because they make the next
refusal decidable before anybody argues about it.

### Structure, never domain

ATF knows about graphs, lifetimes, presence, and uniqueness as a *constraint*. **It never knows what
an email is.** The moment it does, it owns a domain vocabulary: it ships an `Email`, and then it is
asked for an IBAN, a phone format, a VAT number, a postcode, and it spends the rest of its life
maintaining a validation library nobody wanted from it.

That single sentence explains four seams ATF already has, rather than adding one:

| Seam | What plugs in |
| --- | --- |
| `needs()` | how to build a value |
| markers — `any iban` | what your domain counts as a kind |
| systems | what kinds of thing exist |
| phrases and words | what your domain can say |

Each is the same admission in a different currency: *here is where your domain plugs in, because we
refuse to guess it.* ATF's job at every one of them is to be good glue — to whatever a team already
uses, faker being the obvious one — and not to become a smaller, worse version of it.

The rule decides cases in advance. An `Email` type fails it. `any iban` shipped by ATF fails it;
`any iban` registered by a team passes. A `unique_by=` option fails it, because uniqueness is
structure the system already holds and ATF can ask.

### Derive the structural; never type it

Anything ATF can work out for itself, it works out. Applied to every field a declaration carries
today:

| Typed today | Who actually knows it | Result |
| --- | --- | --- |
| `unique_by="email"` | the system — the table holds it unique | derived |
| `scope="function"` | the suite — some scenario mutates it | derived |
| `depends_on=[Owner]` | the class — there is an `Owner` field | written once, at the field |
| `when_absent="require"` | **nobody but you** | stays |

The last row is the boundary, and it is what keeps this from being *guess everything*. Whether ATF
may create a region code is real knowledge about your world that no amount of introspection
recovers. Everything above it was a user restating something the system or the suite already
contained.

The two rules pull in opposite directions on purpose. The first stops ATF inventing domain
knowledge; the second stops it asking for structural knowledge it could have looked up. Between them
a declaration ends up carrying domain facts and nothing else, which is the whole objective — see
also the companion rule in [cut 10](#10--four-words-that-are-not-concepts) about which slots a
framework word may occupy at all.

## The ten cuts

### 1 · Resolution is one mechanism {#resolution-is-one-mechanism}

Three concepts today do one job between them, and the seam shows in every declaration anybody
writes.

- **lineage** — `depends_on=[Owner]`, saying what must exist first
- **factory** — a `factory` classmethod, saying how to build any of a kind
- **asking for one** — a scenario or a signature naming what it wants

They are the same question at three altitudes: *given a hole shaped like an `Owner`, how do I get
one?* Declaring the answer once, at the hole, answers all three.

```python
from atf import needs, sql


@sql.row(table="owners")
class Owner:
    email: str = needs(fake.unique.email)


@sql.row(table="lists")
class TodoList:
    owner: Owner = needs()
    slug: str = needs(a_slug)
```

`needs()` bare resolves whatever the annotation names — the field says `Owner`, so writing `Owner`
again is noise. `needs(x)` names something else: another declared kind, or any callable at all.

**A dependency may depend on things**, which is the whole power of the pattern and what makes the
factory concept unnecessary:

```python
def a_slug(owner: Owner) -> str:
    return f"{owner.email.split('@')[0]}-list"
```

A factory was never more than "the defaults, resolved". Derived fields, sequences and per-kind
flavours all fall out of a resolver that can call a function which itself takes resources.
`TodoList.factory` is deleted, and so is the recursion rule that said a factory calls the factories
of what it was not given — that is just resolution, once, described once.

#### `needs()` is glue, and holds no opinion

`fake.unique.email` above is the point, not an illustration. ATF does not generate values and must
not: producing a valid email means knowing an email has an `@` in it, and a framework that knows
that has started down a road ending in an `Email` type — see
[structure, never domain](#structure-never-domain). Uniqueness is the provider's job too, because
`fake.unique` already does it and a worse reimplementation helps nobody.

So `needs()` takes whatever a team already uses: faker, a function of their own, a fixture from a
library they had before ATF arrived.

This is also the concrete win over the tool people will compare against. factory_boy makes you write
a `Factory` class *alongside* the model, and the two drift — a field added to one is missing from the
other, and nothing says so. Here **the declaration and the factory are the same object**. There is
nothing to keep in step because there is only one thing.

Three ways of saying it become one:

```python
groceries = TodoList(owner=primary, slug="groceries")   # this owner
```
```gherkin
Given a list                                            # resolve everything
Given a list owned by "primary@example.com"             # resolve the rest
```

The same override in a declaration, in a scenario, and — for the library below — in a test
signature.

#### Why not inference, and why not `ref()`

An earlier draft of this document proposed reading the graph off type annotations, dbt-style: a
field annotated `Owner` *is* the edge, no keyword needed. That is wrong for ATF, for two reasons.

`ref()` resolves a **name**. It cannot say *build me one*, because dbt models are not built on
demand — they already exist. ATF's central act is building the thing that is not there, so its
resolution has to carry a strategy, not just a pointer. A bare annotation has nowhere to put the
strategy, which is why the factory had to exist as a separate concept alongside it.

And a graph read off annotations is a graph nobody wrote, so it is a graph nobody checks. It changes
when someone reorders a class or widens a type for a linter. `needs()` is written once, at the point
of use, and is visible in review as a dependency rather than as a type hint.

#### One resolver, not two

The danger is precise and worth naming. **Pytest fixtures already are a dependency injection
system**, and it is the one that owns lifetime. If `needs()` becomes a second container running
beside it, ATF has rebuilt exactly the failure that
[one engine, two surfaces](docs/explanation/one-engine-two-surfaces.md) exists to prevent: two
arrangement paths that agree today and disagree about teardown order next quarter, failing in a
different test, in a different file, on a run that did nothing wrong.

So the rule is not negotiable: **`needs()` compiles to a fixture request.** `fast-depends` is
welcome as the machinery that walks the graph and caches within a scope, but pytest resolution must
*delegate* to it, never run beside it. If a resource can be produced by a path that pytest did not
schedule, the whole guarantee is gone.

The test for whether the implementation held: a resource created for a scenario and the same
resource created for a Python test must be the same object, in the same scope, torn down at the same
moment. That is a scenario ATF can write about itself.

### 2 · One surface, and one library

**Delete the pytest surface as a place tests live.** Not the pytest engine — the engine stays, and
stays hidden. What goes is the idea that a test may be a Python function.

The current doctrine calls them peers: "pick per test and mix them in a suite." That is the sentence
that costs the most. If product and QA read the scenarios as the spec, then every test written in
Python is a hole in the spec, and a suite with holes in its spec is not delivering the thing the
scenarios were for. Two surfaces also means the answer to "where is that test" is permanently "the
other one" — which the current docs concede and then ask the team to solve with a written-down
convention. A convention that has to be written down is a design that did not close.

What is wrong is *peers*, not *Python*. The distinction the current doctrine misses:

- **A surface** is where the spec lives. It is what `atf docs` renders, what the editor lists, what
  product reads, what the suite is understood to be. Two of these is the problem.
- **A library** is ATF's concepts, importable. Resources as fixtures, resolution, environments, the
  shipped systems' fixtures. A developer who wants an opinionated test framework instead of building
  every one of these concepts themselves gets one, and does not have to write a sentence to get it.

The library is not a concession, it is most of the value ATF has already built and currently hides.
Everything under a scenario is already fixtures; refusing to expose them would be refusing to ship
the thing that works. A property test, a load test, a fuzz loop, a migration rehearsal — these are
tests that are genuinely not prose-shaped, and telling a developer to render one as Gherkin so it
counts is how a framework earns the reputation the scenarios were supposed to avoid.

```python
def test_two_lists_never_collide(groceries: TodoList, other: TodoList = needs()):
    ...
```

Same resolution, same lifetimes, same environment, same teardown. What it does not get is a second
assertion vocabulary, a second reporting path or a second way to arrange anything — it uses plain
`assert`, because those are *your* tests and ATF is not pretending to have written them.

#### The boundary has to hold mechanically

If the library is good, teams will drift back into writing tests with it, and two surfaces will
return by accident. Convention will not hold that line — the current docs already ask a team to
"decide it once and write it down", which is the tell.

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

`one-engine-two-surfaces.md` becomes `the-surface-and-the-library.md`.

### 3 · `it`, and no slots

This is the sentence that will lose you product readers:

```gherkin
When I run "make local standup" as "first"
And I run "make local standup" as "second"
Then the first field "output" contains "created"
And the second field "output" contains "unchanged"
```

`the after field`, `the repair field` — these are not English. They are a variable assignment wearing
prose, and `field "output"` is an implementation noun that a product reader has no use for.

The dream deletes naming a result outright, by letting `Then` follow `When` more than once:

```gherkin
Scenario: making twice recognises rather than duplicates
  When I make the standup note
  Then it created the note
  When I make the standup note again
  Then it left the note unchanged
```

`it` is whatever last happened. Assert before you act again and you never need a slot. The rare
scenario that genuinely holds two results at once says `the previous`, and that is the whole of it.

Purist Gherkin says Then-When-Then is bad form. That is dogma, and it is costing readability to
serve it. People describe sequences by interleaving.

### 4 · Prose instead of sigils, and literals that mean what they look like

```gherkin
Then the result field "exit_code" is "0"      # today
Then its exit code is 0                        # dreamt

Then the result field "id" is #uuid            # today
Then its "id" is any uuid                      # dreamt
```

Two changes.

**Quoting stops carrying semantics.** `0` is the number, `"0"` is the text, `true` is the boolean —
the rule every language already uses, and the one a QA author already knows. Today `is "0"` compares
an integer exit code against a quoted string and works anyway, which means the type system is a
lie the reader has to keep.

**`#` dies.** Markers become adjectives: `any uuid`, `any date`, `set`, `missing`. A registry that
lets a team add `#iban` becomes a registry that lets them add `any iban`. Sigils exist because they
are easy to parse. That is the framework's problem and it has been charged to the reader.

### 5 · Two decorators, not five

| Today | Dreamt |
| --- | --- |
| `@phrase` on a tagged `Scenario:` | a `Phrase:` block |
| `@when` | `@act` |
| `@then` | `@check` |
| `@claim` | `@check` — same signature, always was |
| `@check` (suite conventions) | a scenario over the suite |

A phrase becomes a first-class block rather than a tag, because a reader scanning a file should not
have to notice a tag to know that this `Scenario:` is not a test:

```gherkin
Phrase: the command succeeded
  Then its exit code is 0

Phrase: the command refused, saying "{code}"
  Then its exit code is 2
  And it mentions "{code}"
```

`@then` and `@claim` were never two things. Both take values and answer true-or-false with a message.
They were split because one was framed as extending the sentence and the other as extending the
domain, and that is a distinction about the author's intent, not about the code.

Suite conventions (`@check`, `atf check`) stop being a Python registry and become what they are: a
scenario asserting something about the suite. `Given this suite / Then every scenario names a
subcommand`. That is one fewer decorator, one fewer command, and it means the rule that a suite holds
itself to is readable by the same people who read everything else.

### 6 · `owner`, at two levels

Three knobs today, and the glossary spends three "it is not" paragraphs keeping them apart:

- `when_absent` — `make` · `require` · `observe`
- `mutable` — on the environment
- `scope` — `persistent` · `session` · `function`

The first two are the same question asked at two altitudes: **who is responsible for this existing?**

```python
@sql.row(table="regions", owner="them")   # the environment supplies it; ATF only looks
class Region:
    code: str
```

```yaml
staging:
  owner: them                              # nothing here is ATF's to make
```

One word, two values, two places. An environment owned by *them* makes every resource in it observed,
whatever the resource said. `observe` and `require` were never two behaviours — `require` fails a
test when the thing is missing and `observe` does not, and that difference belongs to the scenario
asking for it, not to the declaration.

`scope` stops speaking pytest, and then stops being typed at all.

The three spans keep their meanings and lose their names: **`forever`** (never torn down),
**`the run`**, **`the test`**. `persistent`/`session`/`function` was three words from three
vocabularies, one of them a library the reader was promised they would not have to know — and
`function` is the worst of them, because a scenario author does not have a function.

**Nobody picks one.** The span is read off the suite, and each rule gives the *weakest lifetime that
is still safe*:

| The thing is | It lives | Because |
| --- | --- | --- |
| mutated by some scenario | **the test** | a change must not be visible to the next test |
| factorised — resolved rather than declared | **the run** | generated values are junk once the run ends |
| static — declared with fixed values | **forever** | it is the same thing every run; remaking it is waste |

Three notes, because the rules interact.

**They are a precedence, strictest first.** A resource can be all three at once, and mutated beats
factorised beats static. One consequence is worth saying out loud: adding a single
`When I change the list …` line shortens that resource's life everywhere. That is correct, and it is
the one case where editing one scenario changes another scenario's cost.

**Mutated means restored, not rebuilt.** A resource with a declaration is put back to it, which is
reconciliation — the thing `make` already does — and keeps the cheap case cheap and the identity
stable. A factorised one has nothing to return to, so it is removed. Same guarantee, whichever route
exists.

**Nothing outlives what it depends on.** A declared list whose owner was factorised cannot be
`forever`, because its owner is not. That floor is read off the graph, and without it you get the
bug where a permanent thing points at something that was cleaned up.

The middle rule is the one that earns the whole scheme. It answers the question `forever`-by-default
otherwise invites — *why does the database not fill with faker rows?* Because a generated thing never
claimed to be permanent.

`lives=` survives only as an override for what ATF cannot see, such as the product mutating something
behind its back. Deriving it does not make the classic mistake — a mutated resource declared
persistent — rarer. It makes it unavailable, which matters because that mistake fails one run later,
in a different test, for somebody who did not cause it.

### 7 · One word for the extension point

Adapter, system and driver are three names for one thing the user writes once. A team writes a class,
gets a decorator, and their resources wear it. **That is a system.** Adapter and driver are internal
structure and belong in the source, not the glossary.

And its contract stops being a command. `atf verify-adapter` becomes a `.feature` file that ships with
ATF and that any system must pass — create, read back, update, delete, delete again — run by
`atf run` like everything else. A framework whose own contract is expressed in its own language is
the argument, made once, for free.

### 8 · Six commands

Fifteen commands is fifteen things to know exist. The dream maps them to the questions a person
actually has.

| Question | Command | Absorbs |
| --- | --- | --- |
| Start me off | `atf init` | `adopt` |
| Is this suite sound, and what will happen? | `atf plan` | `status`, `drift`, `adopt`, `check` |
| Run the tests | `atf run` | `import-run`, `verify-adapter` |
| Put me inside this failure | `atf enter [scenario]` | |
| Tell me everything about this | `atf explain <thing>` | `impact`, `unused`, `why-red`, `history` |
| Let me look around | `atf edit` | `docs` |

**`make` is gone as a command.** `atf run` makes what it needs and `atf plan` shows what is missing,
so the only person typing `make` wanted the state without the tests — which is `atf plan --apply`,
and which is rare enough not to hold a name that a newcomer has to learn is not the important one.
The seat it vacated goes to `enter`, and that trade is the right way round: arranging is automatic
and debugging is where a person is stuck.

`plan` is Terraform's lesson and ATF has the graph to do it better: present, absent, drifted, and
*undeclared* — the things in the environment that nothing in the suite knows about, which is what
`adopt` was for and is far more useful as a line in the plan than as a command nobody runs twice.

**`plan` is also where lint lives, and that placement is load-bearing.** An unknown sentence, an
ambiguous phrase, a scenario naming a resource nothing declares — these are the errors the audience
this design is for will hit most, and they must be findable by somebody with no database on their
laptop. Plan is the only command that can promise it: `unreachable` is already in its vocabulary, so
plan against a dead environment reports every suite problem and then says the environment is
unreachable, rather than failing to start. Folding lint into `run` would have made a working
environment the price of a spellcheck.

Lint is also where the *structure, never domain* line is held. ATF does not need to know what an
email looks like to know that a field the system holds unique, resolving to a constant, collides the
second time anything asks for one:

```
  Owner.email is unique in owners and resolves to a constant.
  The second scenario asking for an owner will collide.

    email: str = needs(...)        ← give it something that varies
```

It names the problem and refuses to name the solution. Generating the value would have been the
friendlier answer and the wrong one.

**`--select` reads the sentences rather than tags.** ATF's own suite tags every scenario with the
subcommand it exercises and registers a check to enforce it — a label somebody must remember to add,
plus a mechanism to catch them forgetting, both paying for a fact the scenario already states.
`When I run "atf make local standup"` has said it.

So selection takes what `explain` takes: a resource, a system, a phrase, a file. *Everything that
touches `groceries`. Everything that uses the browser. Everything using the phrase "the command
refused".* That is most of what tags get used for, answered from facts instead of from labels, and a
convention stops needing enforcement. Tags survive for what is genuinely not derivable — `@slow`,
`@flaky` — which is intent rather than taxonomy.

**`run` parallelises itself, and that is an interface decision rather than an optimisation.** Two
scenarios that share no persistent resource cannot interfere, and the graph knows it — so the suite
runs concurrently, correctly, with no flag, no annotation and no marker on a test. Every other
framework makes isolation the user's problem because it has to guess; ATF is the only one holding
the fact. The best version of `keep-a-large-suite-fast.md` is a page that no longer needs to exist.

`explain` is the one that pays. Four commands today ask four questions about one object. Point at a
thing, get its file:

```console
$ atf explain groceries

  groceries · a list · sql · known by slug
  declared in atf/things.py:14

  needs      primary (an owner)
  needed by  4 scenarios, 1 resource
  standing   present in local (made 3 runs ago) · absent in staging

  if it changes
    ✗ a list shows under its owner          lists.feature:6
    ✗ archiving hides it from the index     archive.feature:12
    ...
```

```console
$ atf explain "a list shows under its owner"

  failing since 4 runs ago · passed 61 times before that
  turned between a41f2c and 8c31de

  it needs   groceries → primary → the database
  all three present, none changed since it passed
```

---

### 9 · A system brings its own words

This is the largest cut in the document and it is one sentence:

> **A system brings its things, and the words for them.**

Four concepts in the model are not concepts once that rule exists. They are entries in a system's
own reference, met when you first use that system and not before.

| Concept today | What it actually is |
| --- | --- |
| running something — `When I run "…"` | the `shell` system's word |
| using an interface — `When I click the button "…"` | the `browser` system's word |
| interface claim — `Then the button "…" is disabled` | the `browser` system's word |
| action — changing a declared field mid-test | every system's word, because every system has `update` |

None of these needs to be held in your head to predict what a run will do. They need to be *looked
up*, once, by somebody doing browser work — which is what a reference is for and what a model is
not.

The rule pays three ways beyond the count. It **explains what writing a system gets you**: a
decorator, and sentences, and the editor rendering both — which is already true and is currently
described as a surprising bonus rather than as the definition. It **organises the reference the way
people search it** — "how do I do browser things" is one page, not a scan across Act and Assert. And
it makes the sentence reference **generatable**, which is the subject of
[what the documentation becomes](#what-the-documentation-becomes).

The Act and Assert bands, six concepts and four, come out at three between them: a sentence, a kind
(`any uuid`), and teaching a sentence.

### 10 · Four words that are not concepts

**Variation is resolution with an argument.** Once `needs()` exists, every one of these is the same
operation:

```python
groceries = TodoList(owner=primary, slug="groceries")
```
```gherkin
Given a list owned by "primary@example.com"
Given the list "groceries" with slug "produce"
```

Give the resolver arguments; it resolves the rest. The glossary currently keeps *variation* apart
from *factory* — "a factory invents a fresh instance, a variation bends a declared one" — and after
cut 1 there is nothing left to keep apart. `"null"` to remove a field goes with it: `without a slug`.

**Verdict is a rendering.** `passing` · `failing` · `never run` is history, folded, at the moment
something prints it. It is not a fourth vocabulary a reader must learn beside outcomes; it is what
`atf explain` says. Delete the word, keep the sentence: *failing since 4 runs ago.*

**Report is a flag.** `--report ctrf:out.json`. A run written out is not a concept beside history, it
is an option on the command that produced it.

**Recognition is the system's business, not the resource's.** `unique_by="email"` asks the author to
teach ATF something the system already knows. A file is recognised by its path. A row is recognised
by whatever the table holds unique. A page by its URL. A process by its command line. Cut 9 says a
system brings its things and the words for them; this is the same rule reaching one step further —
**and knows how to recognise them.**

So the author writes nothing:

```python
@sql.row(table="owners")
class Owner:
    email: str
```

Recognition stays a concept — it is the reason a re-run is cheap, and the drift trade-off is real
and worth a page — but it stops being something anybody types. Where a system genuinely cannot
tell, that is an argument on the decorator, because it is configuration of the system rather than a
property of the thing.

The rule this is an instance of: **a framework word may only appear in a domain class when the slot
it occupies already means what the word means.** `needs()` in a default passes. A lookup strategy in
a type annotation does not — an owner's email is a `str`, and dressing the type to carry ATF's
bookkeeping puts the framework in the one place the domain was supposed to own.

### Two Gherkin features refused, and the one concept that pays for both

Tables and DocStrings are already refused. Two more should be, and the refusals need writing down —
an unanswered question is where people invent their own thing.

**`Examples:` tables.** The first question anybody arriving from Cucumber asks is how to run one
scenario over five inputs. A phrase answers it, and reads better than the table did:

```gherkin
Phrase: rejecting the address "{address}"
  When I add the address "{address}"
  Then it failed

Scenario: badly formed addresses are refused
  Given rejecting the address ""
  And rejecting the address "not-an-email"
  And rejecting the address "a@"
```

Each case is a sentence rather than a cell decoded against a header row three lines up.

**`Background:`.** The generic complaint — you read a scenario and cannot tell what set it up — is
true and is not the argument. Three things are.

**It degrades the graph.** In ATF a `Given` is a resource request, so a Background line makes every
scenario in the file drag that resource's whole dependency closure whether it wanted it or not. This
is the one framework that knows exactly which test needs which thing; `atf impact`, `--select` and
`atf unused` are all made of that association, and Background exists to make it coarser. `atf unused`
starts calling things used that one scenario wanted. The precision does not fail loudly. It degrades
as files grow.

**Every rendering of a scenario loses it.** A failure message, a diff in review, `atf docs`, the
editor — in all four the Background is off-screen or absent. The artifact everyone looks at becomes
a partial truth, in a project whose argument is that the record is readable.

**The reason it exists is gone.** Background is a workaround for procedural setup: classic Cucumber
needs it because arranging costs five lines, and five lines times twenty scenarios is intolerable.
ATF's arrange step is `Given the list "groceries"` — one line, because the arranging is data and
lives in `things.py`. The workaround has nothing left to work around.

What covers it is a phrase over `Given` — a **named situation**:

```gherkin
Phrase: a busy account
  Given the owner "primary"
  And the list "groceries"
  And the list "work"

Scenario: the index shows every list
  Given a busy account
  When I run "todo index"
  Then it mentions "groceries"
  And it mentions "work"
```

This beats Background on every axis Background loses on, including the one that mattered most. It is
**named**, so it says what the setup means rather than what steps ran. It is **requested rather than
inherited**, so the phrase expands where it is used and the graph stays exact — `atf impact` still
knows precisely which scenarios need `work`. And it **travels with the scenario** into the failure,
the diff and the docs, because it is a line of the scenario rather than a block above it.

The prize is larger than the refusal. A phrase now spans all three verbs, so **the suite has exactly
one way to grow its language and uses it everywhere**, and its `Given` vocabulary becomes a readable
list of the situations the suite knows — an artefact product can read, and a set of named regions
the editor can draw on the graph.

Two features refused, one concept covering both — which is the budget rule already in force: to
refuse something, name what covers it.

### One sigil worth keeping

`Given a list` builds any; `Given the list "groceries"` means that one. Indefinite versus definite
article, carrying exactly the distinction it carries in English, understood for free by every reader
including the ones who have never seen a test framework.

That is the standard the rest of the syntax is held to, and it is why `#uuid` and `is "0"` lose. A
sigil everybody already knows costs nothing. A sigil invented for the parser is charged to the
reader forever.

## The three things to add

Cutting is most of the work. Three additions are worth the concepts they cost.

### `atf run --accept`

The single biggest ergonomic in modern testing, and ATF does not have it. You write the act and stop:

```gherkin
Scenario: show lists what the owner has
  Given the list "groceries"
  When I run "todo show primary@example.com"
```

No marker is needed and none should be invented. A scenario with no `Then` promises nothing, so it
is already an unambiguous request for ATF to propose one. `atf run --accept` runs it and writes the
claims back into the file, as sentences, for you to read and cut down:

```gherkin
  Then its exit code is 0
  And it mentions "groceries"
  And it mentions "primary@example.com"
```

You delete the two you do not care about. This matters most for exactly the author this design is
for — a QA or product writer who knows what the feature should do and does not know the shape of the
output. It inverts the work from *invent the expectation* to *approve the expectation*, and it is
what makes an assisting agent useful rather than noisy: the agent's job becomes trimming a real
draft, not guessing.

**`atf init` is the same move on the noun side, and it must end green against the real system.** CI
already enforces that the scaffold runs green, so the standard exists — it is applied to a toy. The
version worth having looks around for what is already there (a compose file, a `.env`, a database
URL, a command on the path), declares what it finds, writes one scenario, runs it, and prints green.

The first five minutes are the entire adoption decision, and handing somebody an empty `resources.py`
spends them asking the newcomer to do the hard part first, alone, before anything has ever worked.

Accept, adopt-inside-plan and init are then not three features. They are one posture, stated once:
**ATF writes the draft and you delete what does not matter.**

### Failures that print the graph

Every framework prints the assertion. Only ATF can print why the thing under the assertion existed.

```
✗ a list shows under its owner                      atf/lists.feature:6

  Then it mentions "groceries"
       it mentioned nothing — the output was empty

  groceries    made for this test
  └ primary    present, made 3 runs ago
    └ owners   present

  Nothing upstream changed. `todo show` returned an empty list.

  → atf enter "a list shows under its owner"
```

The last line is not decoration. **Every failure ends with the command that investigates it**, which
is how `enter` gets discovered without documentation and what turns red output from a report into a
next step.

The last line is the one that ends the debugging session, and no other test framework has the
information to write it. `every-failure-names-your-sentence.md` is the right instinct and it stops
one level too early: naming the sentence is table stakes, naming the chain that put the resource
there is the differentiator.

---

### `atf enter`

A red test is where a person is most stuck and least helped. Every framework prints a message and
leaves them to reconstruct the state by hand — because in every other framework the arrangement was
scattered through setup code that has already returned. ATF *declared* it, so it can put you back
inside it.

```console
$ atf enter                          # no argument: the thing that just broke

  a list shows under its owner · arranged, replayed to the failing line

    ✓ Given the list "groceries"
    ✓ When I run "todo show primary@example.com"
    ✗ Then it mentions "groceries"

  >>> it
      exit_code 0 · output ""

  >>> groceries
      slug "groceries" · owner primary · present, made just now

  >>> When I run "todo show --all"
      exit_code 0 · output "groceries"
```

**It is not a debugger.** No frames, no locals, no `pdb`. The prompt's language is the suite's
language — the one the generated reference documents and the editor autocompletes — so there is
nothing to learn in order to use it. Four things it allows:

- **`next`** advances one sentence and shows what `it` became. Stepping is meaningful here in a way
  it never is in code, because a scenario is already a list of sentences.
- **Any sentence the suite knows** runs for real, including ones this scenario never had. That is
  how you explore rather than merely inspect.
- **Naming a resource** re-reads it from the environment now, rather than printing a cached object.
  Presence is asked, never remembered, and the prompt keeps that promise.
- **`keep as "…"`** writes what you typed out as a scenario. Exploration ends in a test rather than
  in a shrug, and it is the same approve-a-draft motion as `--accept` rather than a second mechanism.

Bare `atf enter` meaning *the last failure* is most of the ergonomic. It is the difference between a
tool somebody remembers exists and one they reach for.

## What the model looks like afterwards

Thirteen.

| Band | Concepts | Was |
| --- | --- | --- |
| **The ground** | environment · owner | 2 |
| **Arrange** | thing · system · `needs` · `known` · `lives` | 10 |
| **Act & Assert** | a sentence · a kind · teaching a sentence | 10 |
| **The record** | run · outcome · history | 5 |
| | **13** | **27** |

The count is not the point and it never was. This is:

**Gone as distinctions** — lineage vs factory vs asking for one · variation vs factory · a test
surface vs a peer surface · adapter vs system vs driver · `when_absent` vs `mutable` · `@then` vs
`@claim` · outcome vs verdict · report vs history · `result` vs a named slot · quoted-literal vs
`#marker` · running vs acting vs using an interface · `impact` vs `unused` vs `why-red`.

**Still needing care** — a phrase vs a word you write · recognition vs lineage · a scenario vs a
python test. Three. The first two are genuine differences met at the moment they matter; the third
is now a number in `atf plan` rather than a paragraph in a doctrine page.

The glossary goes from about twenty *"It is not X:"* paragraphs to three, and a glossary with three
of them does not need to be a glossary.

## What the documentation becomes {#what-the-documentation-becomes}

Forty-odd pages today. The target is that the whole system fits in a handful, and everything past
them is optional depth rather than the rest of the instructions.

That is only reachable because of what the cuts did to the *shape* of the material, not its volume.
Two changes matter more than the concept count.

**Most of the reference stops being written.** A system registers its sentences, so the sentence
reference is generated from the registrations — the way the command reference already is. It cannot
go stale, it covers a team's own words the day they write them, and nobody maintains it. `atf edit`
serves it for the suite in front of you, so the reference a team reads is *their* vocabulary, not
ATF's plus a note about extending.

**Levels stop needing to be taught.** The level rule exists because a page had to refuse to mention
concepts a reader had not reached. With thirteen concepts and four of the hardest recast as
per-system lookups, the refusals mostly stop binding. Levels survive as a writer's discipline; they
stop being a thing the documentation explains to a reader.

What is left to hand-write:

| Page | Job | Read |
| --- | --- | --- |
| **README** | the thesis, a whole suite on one screen, the six commands | once, before deciding |
| **Start** | one path end to end against something real, ending green | once, on day one |
| **The model** | thirteen concepts, the four bands, one page | once, when the shape stops being obvious |
| **Extending** | write a system, teach a sentence | once per team, by one person |

Four. Plus generated references — sentences, commands, and `atf docs` for the suite's own spec —
and the essays.

**The essays are the tier you asked for.** *Declared, not executed* · *why there is no state file* ·
*what we borrowed* · *the concept budget* · *why the editor is plain* · *every failure names your
sentence*. They exist to be read by somebody who has already used ATF and wants to know why it is
like that. Nothing in the four pages above may depend on one of them, and each should say at the top
that it is not required. That constraint is worth enforcing the way `--strict` is enforced: a link
from a required page into an essay is a build failure, because it means an argument leaked out of
the page that owed it.

The one page that has to die rather than shrink is *one engine, two surfaces*. Its whole subject was
a distinction cut 2 removes, and a rewrite would preserve the framing that caused the problem.

## What it costs

**The library can eat the surface.** Counting python tests in `atf plan` makes the drift visible, and
visible is not the same as prevented. A team under deadline will write the eighth, the ninth and the
twentieth, and the number will be the only thing that objected. That is the trade taken on purpose —
a rule that forbade it would be routed around by worse means — but it is the failure mode to watch,
and the number is the instrument for watching it.

**Two resolvers is a silent failure and the design invites one.** `needs()` is only safe while it
compiles to a fixture request. The day somebody adds a fast path that builds a resource without
pytest scheduling it, ATF has two arrangement paths and no way to notice — the symptom arrives a
quarter later, in an unrelated test, as residue. This needs a scenario asserting that both paths
produce one object with one lifetime, and that scenario is load-bearing.

**`it` costs the multi-result scenario.** Interleaving `Then` and `When` covers almost everything,
and `the previous` covers the rest, but a scenario juggling three results at once is now awkward on
purpose. That is a scenario that should have been two scenarios.

**Typed literals let a writer be subtly wrong.** `is "0"` against an integer stops silently working.
The failure message has to earn that back: *you compared the number 0 with the text "0" — drop the
quotes*.

**Per-system words are harder to discover than a band in the model.** "What can I say?" used to be
answered by reading Act and Assert. Now it is answered by a generated reference and by the editor,
which is better when the tooling is in front of you and worse in a code review, a terminal or a
diff. `atf run` has to carry the load: an unrecognised sentence must say what it did not match, what
is close, and which system would have to bring the word — the way a good compiler handles an unknown
method.

**`needs()` moves work into resolution, where it is harder to read.** A chain of callables that each
take resources is powerful enough to hide real logic — `a_slug` calling `an_unused_address` calling
a sequence — and a reader looking at `TodoList` sees three words and no idea what they cost.
`atf explain` has to unfold the resolution, not just the graph: what will be called, in what order,
to produce one of these.
