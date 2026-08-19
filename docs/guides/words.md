# Saying it in your own words

*The scenario reads like plumbing, and your team already has a word for what it does.*

Four decorators and one Gherkin block, all registered by being in `atf/`. ATF imports every module
there, so a file called `atf/words.py` is the whole of the wiring.

## A verb your domain already has

`Phrase:` is written in the feature file, in the same language as the scenarios, with no Python:

```gherkin
  Phrase: I complete the task "{name}"
    When the task "{name}" done becomes true

  Phrase: I reopen the task "{name}"
    When the task "{name}" done becomes false

  Scenario: a domain verb is a phrase over a field change, and its effect lasts
    Given the task "laundry"
    When I complete the task "laundry"
    Then the task "laundry" done is true
    When I reopen the task "laundry"
    Then the task "laundry" done is false
```

`{name}` is a hole. A phrase may stand over several sentences, which is how a shared situation gets
a name and is said where it is used. Phrases nest, and the wording is one namespace across the
suite; when two could answer the same sentence, the one with more wording in it wins.

## A verb that has to do something

```python
@act('I ask for the lists of "{name}"')
def _(name, http, atf):
    """Whatever an act returns becomes `it`, and the sentence after reads it."""
    owner = atf.look_up("owner", name)
    return http.client.get(f"/owners/{owner['id']}/lists").json()
```

The parameters are how it asks for things: a `{hole}` from the pattern arrives as the text the
scenario wrote there; a driver's name — `http`, `sql`, `shell`, `browser`, `filesystem` — arrives as
that system configured for this environment; a name annotated with a declared kind arrives as
whichever one the scenario arranged; and `atf` is the run's own handle, with `atf.it()`,
`atf.look_up(kind, name)`, `atf.suite` and `atf.ground`.

An act with nothing said about what it touches is opaque, and every scenario saying it runs alone.
`@act("…", effect="reads")` and `effect="writes"` are how a word of yours rejoins a concurrent set.

## A claim your domain has a word for

```python
@check('the answer names "{slug}"')
def _(atf, slug: str):
    """A claim in the domain's words, failing through the library the shipped ones use."""
    named = [one.get("slug") for one in atf.it().get("items", [])]
    claims.held((slug in named, f"it named {', '.join(named) or 'nothing'}"), subject="the answer")
```

A check may answer `True`/`False`, answer `(held, message)`, or go through `atf.claims` — the same
library every shipped sentence fails through, holding `field_is`, `field_contains`, `mentions`,
`exists`, `is_gone`, `counted`, `held` and `fail`.

## A shape, where the value is not the point

```python
@kind("slug")
def _(value):
    """Lower case, digits and hyphens. A shape, where the value is not the point."""
    text = str(value)
    return bool(text) and all(one.isdigit() or one.islower() or one == "-" for one in text), (
        f"{value!r} is not a slug"
    )
```

```gherkin
    And the todo_list "groceries" slug is any slug
```

ATF ships kinds about structure — `any uuid`, `any whole number`, `any text like <pattern>`, `set`,
`missing` — and none that know a domain.

## A format for your pipeline

```python
@report("tally")
def _(run, path):
    """A line per test, which is the shortest thing a format can be."""
    lines = [f"{one.outcome} {one.test}" for one in run.outcomes]
    path.write_text(f"{run.environment}\n" + "\n".join(lines) + "\n", encoding="utf-8")
```

```console
$ atf run --report tally:tally.txt
0 failed, 11 passed, 0 skipped   (r-1f9ae3)
wrote tally.txt

$ head -2 tally.txt
local
passed atf/lists.feature::a list shows under its owner
```

`run` carries the environment, the identities and every outcome with where it failed. `ctrf` ships
both ways, so a run written anywhere can be read back with `atf run --import`.

## Where they show up

Everything above appears in `atf explain`, in the editor's sentence list, and in
[the sentence reference](../reference/sentences.md), which is generated from what is registered. The
first line of each function's docstring is its description, so that is where a sentence gets
explained.
