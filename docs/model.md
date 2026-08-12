# The model

Thirteen concepts, in four bands. One page, read once, when the shape stops being obvious.

| Band | Concepts |
| --- | --- |
| **The ground** | environment · owner |
| **Arrange** | thing · system · `needs` · known · lives |
| **Act & Assert** | a sentence · a kind · teaching a sentence |
| **The record** | run · outcome · history |

Nothing below is a distinction you have to hold in your head to predict what a run will do. Where
something has to be looked up rather than remembered — what the browser system can say, what your
own team registered — it is [in the generated reference](reference/sentences.md), which is where a
lookup belongs.

## The ground

**An environment** is somewhere a suite can be pointed. It is a name and a settings block per
system, and nothing else. The first one written is the default; `--env` overrides it.

**Owner** is one word with two values, asked at two levels: *who is responsible for this existing?*

```python
@sql.row(table="regions", owner="them")   # the environment supplies it; ATF only looks
class Region:
    code: str
```

```yaml
staging:
  owner: them                              # nothing here is ATF's to make
```

An environment owned by *them* makes every thing in it observed, whatever the thing said. There is
no third value: whether a missing thing *fails* a test belongs to the scenario that asked for it,
not to the declaration.

## Arrange

**A thing** is an ordinary class with one framework word in it, and one particular thing is a
module-level variable. Its name is the variable's name.

**A system** is where a kind of thing lives — `sql`, `filesystem`, `browser`, `shell`, or one your
team writes. A system brings its things **and the words for them**, which is why "running something"
is not a concept here: it is the shell system's word.

**`needs()`** is how you get a thing you need, and it is the only way.

```python
@sql.row(table="lists")
class TodoList:
    owner: Owner = needs()          # another kind: this is a lineage edge
    slug: str = needs(a_slug)       # any callable at all
```

Bare, it resolves whatever the annotation names. With an argument it names something else — another
kind, or any callable. **A resolver may itself take things**, and that is what makes a separate
factory concept unnecessary: derived fields, sequences and per-kind flavours all fall out of a
resolver that can ask for what it needs.

There is one resolver. A thing built for a scenario and the same thing built for a Python test are
the same object, in the same span, torn down at the same moment.

**Known** — recognition — is how ATF tells one thing from another, and it is **the system's answer,
never yours**. A file is known by its path. A row by whatever the table holds unique. A page by its
URL. You write nothing; where a system genuinely cannot tell, that is an argument on the decorator,
because it is configuration of the system rather than a property of the thing.

Recognition is why a re-run is cheap: the second run finds what the first made instead of making it
again.

**Lives** is how long a thing lasts, and **nobody picks it**. It is read off the suite, and each
rule gives the weakest lifetime that is still safe:

| The thing is | It lives | Because |
| --- | --- | --- |
| mutated by some scenario | **the test** | a change must not be visible to the next test |
| resolved rather than declared | **the run** | generated values are junk once the run ends |
| declared with fixed values | **forever** | it is the same thing every run; remaking it is waste |

They are a precedence, strictest first, and a thing can be all three at once. One consequence is
worth saying out loud: adding a single `When I change the list …` line shortens that thing's life
everywhere. That is correct, and it is the one case where editing one scenario changes another
scenario's cost.

Two more rules make it hold together. **Mutated means restored, not rebuilt** — a thing with a
declaration is put back to it, which keeps the cheap case cheap and the identity stable; a resolved
one has nothing to return to, so it is removed. And **nothing outlives what it depends on**: a
declared list whose owner was resolved cannot live forever, because its owner does not.

`lives=` survives only as an override for what ATF cannot see — the product mutating something
behind its back, through an effect nothing declared.

## Act & Assert

**A sentence** is one line of a scenario. `Given` arranges, `When` acts, `Then` checks; `And` and
`But` continue whichever came before them.

`it` is whatever last happened. There is no way to name a result, and none is needed: assert before
you act again. The rare scenario genuinely holding two at once says `the previous`, and a scenario
juggling three should have been two scenarios.

Quoting carries the type. `0` is the number, `"0"` is the text, `true` is the boolean, `nothing` is
not there at all.

**A kind** is what you say when the value is not the point: `any uuid`, `any date`, `set`, `missing`.
Your team registers `any iban` the same way ATF registers `any uuid` — and ATF ships none that know
a domain, because a framework that learns what an IBAN is spends the rest of its life maintaining a
validation library nobody wanted from it.

**Teaching a sentence** happens two ways, and there is nothing else.

A `Phrase:` block, in Gherkin, for a sentence that stands for other sentences:

```gherkin
Phrase: the command refused, saying "{code}"
  Then its exit code is 2
  And it mentions "{code}"
```

A phrase spans all three verbs, so a `Given` phrase is a **named situation** — which is what stands
where a `Background` would have:

```gherkin
Phrase: a busy account
  Given the owner "primary"
  And the list "groceries"
  And the list "work"

Scenario: the index shows every list
  Given a busy account
  When I run "todo index"
  Then it mentions "groceries"
```

Or `@act` and `@check`, in Python, when a sentence has to do something Gherkin cannot say. Both take
values; a check answers true-or-false with a message. See [Extending](extending.md).

### Two things this language does not have

**No `Examples:` tables.** A phrase runs one scenario over several inputs, and each case reads as a
sentence rather than a cell decoded against a header row three lines up.

**No `Background:`.** It degrades the graph — every scenario in the file drags a thing's whole
closure whether it wanted it or not — and every rendering of a scenario loses it: a failure message,
a diff in review, the editor. A named situation beats it on both, because it is requested rather
than inherited and it travels with the scenario.

To refuse something, name what covers it. Both refusals say all of this at the line that wrote them.

## The record

**A run** is one execution: what was selected, what happened, and when. **An outcome** is what one
test did — passed, failed, skipped. **History** is the runs, kept.

There is no fourth word for a verdict. *Failing since 4 runs ago, passed 61 times before that* is
history folded at the moment something prints it, which is `atf explain`.

A report is a flag on the command that produced the run — `--report ctrf:out.json` — not a concept
beside history.

## Still needing care

Three distinctions are real, and each is met at the moment it matters:

- **A phrase and a word you write.** A phrase stands for sentences; an `@act` does something no
  sentence could say.
- **Recognition and lineage.** One says *which* thing this is; the other says what must exist first.
- **A scenario and a Python test.** A scenario is the spec. A Python test uses the same resolver,
  spans, environment and teardown — and is a hole in the spec, which is why `atf plan` counts it.

That last one is a number rather than a rule on purpose. A rule that forbade Python tests would be
routed around by worse means; a number in the output everyone already looks at tells a team that it
is drifting, in time to decide.
