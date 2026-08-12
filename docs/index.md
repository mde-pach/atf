# Start

One path, end to end, against something real, ending green. Read once, on day one.

Everything here is the whole of what you need to run a suite. [The model](model.md) is the page for
when the shape stops being obvious, and [Extending](extending.md) is the one person on your team who
writes a system.

## Install it, and let it look around

```console
$ pip install atf
$ atf init
```

`atf init` does not hand you an empty file. It looks for what is already here — a compose file, an
`.env`, a database URL, a command on your path — declares what it finds, writes one scenario, runs
it, and prints green:

```console
found a compose file (docker-compose.yml)
found a database url (postgres://todo:***@localhost/todo)
found todo on the path
wrote atf.yaml
wrote atf/things.py
wrote atf/hello.feature

0 failed, 1 passed, 0 skipped   (r-2b09ca)

green. Write the next scenario in atf/hello.feature.
```

Two files and one directory. Nothing points at the directory — ATF finds `atf/` beside the manifest
the way pytest finds a `conftest.py`.

## Declare a thing

Open `atf/things.py`. A thing is an ordinary class with one framework word in it:

```python
from atf import needs, sql


@sql.row(table="owners")
class Owner:
    email: str


primary = Owner(email="primary@example.com")
```

The decorator says which system this lives in. The annotations are the shape. The module-level
variable is one particular owner, and its **name is the variable's name** — that is what a scenario
says.

Nothing has been created. Declaring is not doing; `atf plan` is what tells you where you stand:

```console
$ atf plan

  1 scenarios

  local
    0 present · 1 absent · 0 drifted
      absent      primary                  will be made
```

## Say what one needs

A thing that hangs off another says so at the field that holds it:

```python
@sql.row(table="lists")
class TodoList:
    owner: Owner = needs()          # this is the edge
    slug: str


groceries = TodoList(owner=primary, slug="groceries")
```

`needs()` on its own resolves whatever the annotation names — the field says `Owner`, so writing
`Owner` again would be saying it twice. That one word is the whole of lineage: ATF now knows to make
`primary` before `groceries`, to tear them down the other way round, and which tests break if either
moves.

## Let it fill in what you do not care about

Give `needs()` an argument and it names something else — another kind, or **any callable at all**:

```python
def a_slug(owner: Owner) -> str:
    return f"{owner.email.split('@')[0]}-list"


@sql.row(table="owners")
class Owner:
    email: str = needs(fake.unique.email)


@sql.row(table="lists")
class TodoList:
    owner: Owner = needs()
    slug: str = needs(a_slug)
```

**A resolver may itself take things**, which is what makes a separate "factory" concept unnecessary.
`a_slug` asks for an `Owner` and gets *this list's* owner.

ATF never produces a value itself. Uniqueness is the provider's job too, because `fake.unique`
already does it and a worse reimplementation helps nobody.

## Write a scenario

```gherkin
Feature: lists belong to their owner

Scenario: a list shows under its owner
  Given the list "groceries"
  When I run "todo show primary@example.com"
  Then it mentions "groceries"
```

Three sentences, and each is one of three verbs:

- **`Given`** arranges. `the list "groceries"` is that one; `a list` is any one, resolved. Every
  `Given` comes first.
- **`When`** acts. Whatever it produced becomes **`it`**.
- **`Then`** checks, about `it` or about a declared thing.

`Then` may come before another `When`. Assert before you act again and you never need to name a
result:

```gherkin
Scenario: making twice recognises rather than duplicates
  When I make the standup note
  Then it created the note
  When I make the standup note again
  Then it left the note unchanged
```

## Quoting carries the type

```gherkin
Then its exit code is 0        # the number
Then its slug is "0"           # the text
Then its archived is false     # the boolean
Then its "id" is any uuid      # a kind, where the value is not the point
```

The rule every language already uses. If you compare a number with quoted text, the failure says so
and names the fix.

Text between quotes reads its escapes — `\n`, `\t`, `\\`, `\"`. The full list of sentences and kinds
is [generated from the registrations](reference/sentences.md), and `atf edit` serves it for the
suite in front of you.

## Run it

```console
$ atf run

0 failed, 12 passed, 0 skipped   (r-4c1e77)
```

**It parallelises itself**, with no flag: two scenarios that share nothing permanent cannot
interfere, and the graph knows which those are.

You never make anything by hand. `atf run` makes what it needs, and `atf plan` shows what is
missing. If you want the state without the tests, that is `atf plan --apply`.

## Read a failure

```
✗ a list shows under its owner                      atf/lists.feature:6

  Then it mentions "groceries"
       it mentioned nothing — the output was empty

  groceries    made for this test
  └ primary    present, made 3 runs ago
    └ owners   present

  → atf enter "a list shows under its owner"
```

Every framework prints the assertion. ATF prints why the thing under it existed, because it declared
it. And the last line is not decoration: it is where you go next.

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

It is not a debugger — no frames, no locals, no `pdb`. The prompt speaks your suite's language, so
there is nothing to learn in order to use it. `next` steps one sentence; naming a thing re-reads it
from the environment now; any sentence your suite knows runs for real; and `keep as "…"` writes what
you typed out as a scenario.

## Let ATF draft the claims

Write the act and stop. A scenario with no `Then` promises nothing, so it is already a request:

```gherkin
Scenario: show lists what the owner has
  Given the list "groceries"
  When I run "todo show primary@example.com"
```

```console
$ atf run --accept
```

```gherkin
  Then its exit code is 0
  And it mentions "groceries"
  And it mentions "primary@example.com"
```

Delete the ones you do not care about. It is easier to approve an expectation than to invent one,
especially before you know the shape of the output.

## Point it at somewhere else

```yaml
environments:
  local:
    owner: atf
    sql: { path: ./local.db }

  staging:
    from:  local
    owner: them
    sql:   { url_env: STAGING_DATABASE_URL }
```

`owner: them` means ATF may only look. Every thing in that environment becomes observed, whatever
any single declaration said — so the same suite runs against staging and creates nothing.

```console
$ atf run --env staging
```

## Where to go next

- [The model](model.md), when the shape stops being obvious — one page.
- [Extending](extending.md), when your domain needs a word ATF does not ship.
- `atf explain <anything>` — a thing, a kind, a system, a scenario, a phrase, a file.
- `atf edit` — the suite, its graph, its spec and its own vocabulary, in a browser.
