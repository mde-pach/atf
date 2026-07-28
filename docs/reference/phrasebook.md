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
[generic claim](specs-and-fixtures.md#read-and-compare-steps) would otherwise leak a field name, a
code or a flag into the spec text.

## Why it exists {#why}

The generic claims read fine while a scenario is only saying whether something is there:
`Then the owner "primary" exists` needs no translation. The moment a *value* is involved they stop.
`Then the result field "exit_code" is "2"` is a struct field access spelled in English, so making a
suite generic used to mean making its specs *less* readable exactly where it mattered.

A phrase is the layer between the two. The technical vocabulary lives in one file — which is also
the only place to edit when `mutable_envs` is renamed — and the spec says what a person means.

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

`{capture}` in the sentence is a value the spec writes, and it reaches every step that names it.
A step naming a capture the sentence does not take is refused when the file loads.

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
[a slot](specs-and-fixtures.md#slots) is offered only once a step above has produced one.

## Why it does not rewrite the feature {#not-a-rewrite}

Expanding before pytest-bdd parses would be less code, and the run report would then show four
primitive steps where the file shows one sentence — the reader reading one thing and the cockpit
reporting another. So a phrase is a real step definition that runs its steps inside itself. One
line in the file, one line in the report.
