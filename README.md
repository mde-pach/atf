# ATF

**Preconditions declared as data, rather than executed as setup code.**

Every other test framework arranges by running code: a `setUp`, a fixture, a factory call. ATF
declares what must exist, as ordinary classes and variables, and works the rest out — the order
things are made in, how long each one lives, which tests can run beside which, and what breaks if
one of them changes.

Nothing else here is the differentiator. Everything else is kept small so that it does not compete
with this for your attention.

## A whole suite, on one screen

```
myapp/
  atf.yaml
  atf/
    things.py        the nouns
    words.py         the words ATF did not ship
    lists.feature    the tests
```

Four files. **No key in the manifest points at any of them** — ATF finds `atf/` the way pytest finds
`conftest.py`.

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

One key, and the first environment is the default. `from:` exists because the only repetition left
in a manifest is the second environment restating the first, and you should be able to see what
makes staging different by reading what staging says.

### `atf/things.py`

```python
from atf import needs, sql


@sql.row(table="owners")
class Owner:
    email: str = needs(fake.unique.email)


@sql.row(table="lists")
class TodoList:
    owner: Owner = needs()          # this is the edge
    slug: str


primary   = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

A domain class with one framework word in it. `needs()` says how to get one when nobody gave one —
which is what a default *is*, and why it earns the default slot. Nothing else in the class belongs
to ATF.

**ATF does not generate values.** Producing a valid email means knowing an email has an `@` in it,
and a framework that knows that ends up maintaining a validation library nobody wanted from it. So
`needs()` takes whatever you already use: faker, a function of your own, a fixture you had before
ATF arrived.

### `atf/lists.feature`

```gherkin
Feature: lists belong to their owner

Scenario: a list shows under its owner
  Given the list "groceries"
  When I run "todo show primary@example.com"
  Then it mentions "groceries"
```

## What that buys you

Because the arrangement is data rather than code, ATF can answer things a framework normally cannot:

- **It parallelises itself.** Two scenarios that share nothing permanent cannot interfere, and the
  graph knows it — so the suite runs concurrently, correctly, with no flag and no marker on a test.
- **It works out how long each thing lives.** Mutated by some scenario → the test. Resolved rather
  than declared → the run. Declared with fixed values → forever. Nobody types a scope, so nobody
  types the wrong one.
- **A failure prints why the thing under the assertion existed** — the whole chain — and ends with
  the command that puts you back inside it.
- **`atf plan` lints without a database**, because a dead environment is a line in the plan rather
  than a reason to refuse to start.

## Six commands

| Question | Command |
| --- | --- |
| Start me off | `atf init` |
| Is this suite sound, and what will happen? | `atf plan` |
| Run the tests | `atf run` |
| Put me inside this failure | `atf enter` |
| Tell me everything about this | `atf explain <thing>` |
| Let me look around | `atf edit` |

```console
$ atf plan

  147 scenarios
    8 python tests using atf resources        ← not in the spec

  local
    140 present · 6 absent · 1 drifted
      absent      groceries                will be made
      drifted     primary                  email
      undeclared  owners a-stray@example.com
```

## Getting going

```console
$ pip install atf
$ atf init
```

`atf init` looks around for what is already there — a compose file, an `.env`, a database URL, a
command on your path — declares what it finds, writes one scenario, runs it, and prints green. The
first five minutes are the entire adoption decision, so it does not spend them handing you an empty
file.

Then read [Start](docs/index.md), which is one path end to end. [The model](docs/model.md) is one
page, for when the shape stops being obvious.

## Documentation

- [Start](docs/index.md) — one path, end to end, ending green
- [The model](docs/model.md) — thirteen concepts, four bands, one page
- [Extending](docs/extending.md) — write a system, teach a sentence
- [Sentences](docs/reference/sentences.md) and [Commands](docs/reference/commands.md), both generated

## Licence

See [LICENSE](LICENSE).
