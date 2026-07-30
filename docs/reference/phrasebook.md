# Phrasebook reference

`specs/phrasebook.yaml` maps a sentence a spec says to the steps it stands for. It is data: no
Python, no expressions, no control flow.

```yaml
'it is refused because "{reason}"':
  - the result field "exit_code" is "2"
  - the result field "output" contains "{reason}"
```

```gherkin
Then it is refused because "not in mutable_envs"
```

The file is optional. A suite without one is perfectly idiomatic — reach for a phrase where a
[generic claim](assertions.md#read-and-compare-steps) would otherwise leak a field name, a
code or a flag into the spec text.

## Why it exists {#why}

A phrase is the layer between a generic claim and a value that would otherwise leak a field name, a
code or a flag into spec text — the technical vocabulary lives in one file, and the spec says what a
person means. See [About the phrasebook](../explanation/why-the-phrasebook.md#why) for the reasoning.

## The file {#file}

One mapping. Each key is the sentence; each value is the steps it stands for, in order.

```yaml
# A list, in the order they run.
'the developer seeds "{env}" twice':
  - I run "atf seed {env}"
  - I run "atf seed {env}"

# One step needs no list.
'the command succeeds': the result field "exit_code" is "0"
```

`{capture}` in the sentence is a value the spec writes, and it reaches every step that names it —
in a step's line and in a table's cells alike. A step naming a capture the sentence does not take is
refused when the file loads.

### A step that takes a table {#tables}

A step ending with a colon takes [a table](assertions.md#tables) under it. So does a YAML
mapping key, which is what lets a phrase carry one with no second format to learn:

```yaml
'the account is set up the way a new customer should be':
  - the account "primary" is:
      plan: free
      seats: 1
      trial_ends_at: "#datetime"
```

```gherkin
Then the account is set up the way a new customer should be
```

**Quote a marker.** `#` starts a comment in YAML, so `plan: #str` is a key with a comment after it
and a claim that would pass for the wrong reason. Writing it unquoted is refused when the file
loads, by name.

This is also how a table is told from [the colon trap](#file): a table step's value is another
*mapping*, and a sentence YAML found structure in has a scalar.

**A step is read as the line you wrote.** YAML would rather it were something else — a colon and a
space start a mapping, so `contains "registered: env, now"` would load as one, and `"flag: true"`
would come back holding a boolean. ATF reads steps from the document tree instead of from loaded
values, so neither happens and no line needs quoting it did not ask for. Quoting still works where
you want it.

[`${...}` placeholders](providers.md) work inside a phrase exactly as they do in a step a scenario
wrote itself.

## Three rules {#rules}

**A phrase stands for steps, never for another phrase.** Flat, one level, no recursion — checked
when the file loads and refused by name. This is the guard against a phrasebook becoming a badly
designed programming language, which is the documented way layered-keyword frameworks fail at
scale. A phrase that wants another's meaning writes out the same lines; two lines of YAML are
cheaper than a language with a call stack, no types and no debugger.

**A phrase runs its steps as the kind of step it was said as.** `When the developer seeds "local"`
stands for actions; the same sentence under `Then` would stand for claims. One phrase mixing them
would hide a `When` inside a `Then`, which is the readability the phrase was supposed to buy,
spent. Write two phrases.

**A phrase is not a step.** It performs nothing. Everything it stands for is a step that already
existed — ATF's or the suite's — so a phrasebook adds wording, never capability, and there is never
a question of where the behaviour lives.

## What a failure says {#failures}

The phrase *and* the step inside it, so someone who wrote a sentence is never handed a stack trace
about a field:

```
'it is refused because "{reason}"' says 'the result field "exit_code" is "9"', and that did not hold:
result's 'exit_code' is 2 (a number), not "9"
```

A phrase standing for something no step is worded as says that when it runs, naming both.

## In the cockpit {#cockpit}

A phrase registers as a real step definition, so everything that offers steps offers phrases without
being told: the composer lists them under *this suite's wording*, between the claims that need no
code and the steps the suite had to write. What a phrase stands for is its description, and what it
*needs* is the union of what its steps need — so a phrase standing for a claim about
[a slot](assertions.md#slots) is offered only once a step above has produced one.

## Why it does not rewrite the feature {#not-a-rewrite}

A phrase is a real step definition that runs its steps inside itself, rather than expanding into
them before pytest-bdd parses. See
[About the phrasebook](../explanation/why-the-phrasebook.md#not-a-rewrite) for why.

## Where to go next

- [About the phrasebook](../explanation/why-the-phrasebook.md) — why the file exists, and why it
  stays a flat mapping.
- [Assertions reference](assertions.md#read-and-compare-steps) — the generic claims a phrase stands
  in front of.
- [CLI reference](cli.md#lint-vocabulary-rules) — the syntactic half of the same rule, checked by
  `atf lint`.
