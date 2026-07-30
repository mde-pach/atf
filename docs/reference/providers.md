# Providers reference

A **provider** is a named source of values that a catalog body or a step can interpolate. It is the
extension point behind every `${...}` that is not a
[node reference](catalog.md#placeholders):

```yaml
body:
  due_at: ${now+1d 09:00}
  token: ${uuid}
  callback: ${env:CALLBACK_URL}
  nickname: ${fake:first_name}
```

```gherkin
When I rename it to "${fake:company}"
Then the todo_list "groceries" field "title" is "${fake:company}"
```

## The two forms of `${...}` {#the-two-forms}

| Form | What it is |
|---|---|
| `${<collection>.<name>.id}` | A **node reference** — another resource's identity. Checked when the catalog loads, and becomes an edge in the dependency graph. |
| anything else | A **provider call**. |

A node reference always wins, so no registered name can shadow a collection.

## Writing a call {#calls}

```
${<name>}                 the provider, with no argument
${<name>:<argument>}      with one
${<name>:<argument>#tag}  with a discriminator
```

Everything after `#` distinguishes two calls that must not share a value. It never reaches the
provider — see [one evaluation per scenario](#one-evaluation).

`${now+1d 09:00}` is the same shape: `now` is the name and `+1d 09:00` the argument, since anything
that is not separated by `:` is passed through whole.

## One evaluation per scenario {#one-evaluation}

An expression is evaluated **once per scenario** and the answer is reused for every identical
expression in it.

Without that rule a provider would be useless where it is most wanted: a `When` that generates a
name and a `Then` that checks it would compare two different names, and the assertion could never
pass. With it, both lines write `${fake:company}` and both see the same company — no variable to
declare, nothing to carry.

When you genuinely want two, tell them apart:

```gherkin
When I rename it to "${fake:company}"
Then the todo_list "groceries" field "title" is not "${fake:company#previous}"
```

The next scenario generates afresh. Values stand still *within* a scenario and must not across
them, or an ephemeral resource meant to be new every time would not be.

## Where a generated value may go {#where}

Fresh values are the point of a provider. There is exactly one place they are incoherent, and the
catalog refuses it when it loads:

| Where | Fresh each run |
|---|---|
| Any field of an [ephemeral](../explanation/lifecycles.md) resource | **Yes** — one is never looked up, so nothing can accumulate |
| A field outside the natural key | **Yes** — see [decided once](#decided-once) |
| A step's parameter | **Yes** — nothing is persisted and nothing is looked up |
| The natural key of a persistent or reference resource | **Refused at load**, when the provider says its values are fresh |

```
accounts.primary: email is part of the natural key and is generated (${fake:email}).
A value that changes every run never matches what is already there, so every run would
create another one. Write it out, or make the type ephemeral.
```

[`find`](adapter-spi.md#find) resolves the natural key and asks the backend for a match. A value
that is new on every pass never matches, so every run creates another record and a shared
environment fills up — quietly, because nothing fails. Seeding around it was considered and
rejected: a generated value that never changes is an elaborate way of writing a literal.

Which providers are fresh is theirs to declare, through `keyable` — see [writing one](#writing).
`now` and `env` say yes: `${now+1d 09:00}` in a key gives one record per day, which is exactly what
someone writing it there is asking for. `uuid` and `fake` say no.

### Outside the key, decided once {#decided-once}

A generated value in a *non-key* field is only evaluated when the resource is actually created.
Every later run finds the existing record and the stored value wins. So it is decided once, at
first creation, and then stays — which is what get-or-create means, and worth knowing before it
surprises you.

## The providers ATF ships {#built-in}

| Call | Value |
|---|---|
| `${now+Nd HH:MM}`, `${now-Nd HH:MM}` | A moment relative to this one, ISO-8601 with `Z`. |
| `${uuid}`, `${uuid:hex}` | A fresh identifier, with or without dashes. |
| `${env:NAME}` | An environment variable. A missing one is an error, never an empty string. |
| `${fake:<method>}` | Any [Faker](https://faker.readthedocs.io/) method, when Faker is installed. |

`fake` is registered whether or not Faker is installed — so the catalog can still tell that a value
from it has no business in a natural key — but it only resolves once Faker is there:

```sh
uv sync --group fake
```

ATF itself depends on nothing that generates data, because a framework should not decide what a
project's test data looks like.

## Configuring one {#configuring}

Per environment, beside `adapters` and `clients`:

```yaml
environments:
  dev:
    providers:
      fake:
        locale: en_GB
        seed: 1234          # makes a whole run reproducible
```

A provider is built once per process and kept, so it may hold a connection, a seeded generator or a
counter without any of them resetting between values.

## Writing one {#writing}

One method, registered the way an adapter is:

```python
# model/providers.py, listed under `adapters:` in the manifest — the same import hook loads both
from atf.model.providers import register


class Sequence:
    """`${seq:invoice}` -> invoice-1, invoice-2, …"""

    # Values are fresh, so the catalog refuses one of these in a natural key. Say `True` only if
    # the same call gives the same answer on a later run — a clock or an environment variable can.
    keyable = False

    def __init__(self, settings):
        self.start = int(settings.get("start", 1))
        self.counts: dict[str, int] = {}

    def value(self, argument: str):
        self.counts[argument] = self.counts.get(argument, self.start - 1) + 1
        return f"{argument}-{self.counts[argument]}"


register("seq", Sequence)
```

`value` may return any type. A string that is *exactly* one placeholder keeps that type, so
`${seq:n}` returning an `int` reaches the backend as an `int`; interpolate it into surrounding text
and it becomes text.

Raising is how a provider refuses — the message reaches whoever wrote the expression.

## Where to go next

- [Catalog reference](catalog.md#placeholders) — where placeholders may appear in a body.
- [Manifest reference](manifest.md#env-providers) — the `providers` block.
- [Specs and fixtures reference](assertions.md#read-and-compare-steps) — the steps that
  compare a generated value with what a backend returned.
