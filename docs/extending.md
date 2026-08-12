# Extending

Write a system, teach a sentence. Read once per team, by one person.

There are exactly two things to extend, and they are the two places ATF refuses to guess your
domain. **A system** says what kinds of thing exist and how to reach them. **A sentence** says what
your domain can say. Everything else — resolution, spans, environments, teardown, the graph — you
get without writing anything.

## Teach a sentence in Gherkin

Most of what a team wants is a phrase, and a phrase needs no Python at all:

```gherkin
Phrase: the command refused, saying "{code}"
  Then its exit code is 2
  And it mentions "{code}"

Phrase: a busy account
  Given the owner "primary"
  And the list "groceries"
  And the list "work"

Phrase: rejecting the address "{address}"
  When I add the address "{address}"
  Then it failed
```

A `Phrase:` is vocabulary rather than a test, and it says so in the word itself — nobody scanning
the file has to notice a tag. A phrase may say another phrase; one that reaches itself is refused
with the way round.

Phrases span all three verbs, so this is also how you run one scenario over several inputs, and how
you name a situation:

```gherkin
Scenario: badly formed addresses are refused
  Given rejecting the address ""
  And rejecting the address "not-an-email"
  And rejecting the address "a@"
```

## Teach a sentence in Python

When a sentence has to *do* something Gherkin cannot say, there are two decorators.

```python
from atf import act, check


@act('I archive the list "{name}"')
def _(name, sql):
    """Whatever an act returns becomes `it`."""
    return sql.rows("UPDATE lists SET archived = true WHERE slug = ? RETURNING *", (name,))[0]


@check('the list "{name}" is archived')
def _(name, atf):
    """A check answers true-or-false, with a message."""
    found = atf.look_up("todo_list", name) or {}
    return bool(found.get("archived")), "it is not archived"
```

That is the whole of it. `@check` is one decorator because extending the sentence and extending the
domain are a distinction about your intent, not about the code — both take values and answer
true-or-false with a message. A check may also just raise; `atf.claims` holds the comparisons ATF's
own sentences are made of.

**What a step asks for by name** is answered the same way everything else is: a declared thing, a
kind, a system (`sql`, `shell`, `browser`), or `atf` for the scope itself.

A hole written between quotes in the pattern is text somebody wrote, so it reads its escapes. A hole
written bare is not touched.

### Say what it does to what it names

```python
@act('the list "{name}" is emptied', effect="writes")
def _(name, atf): ...
```

`effect` is `reads`, `writes`, or left out. Left out means *opaque*: an unstated effect is treated as
any effect at all, which is safe and costs you parallelism — a test with an opaque sentence runs
with nothing beside it. Declaring `reads` or `writes` is how you buy it back, and `atf run --explain`
shows what each test is waiting on.

## Register a kind

```python
from atf import kind


@kind("iban")
def _(value):
    return looks_like_an_iban(value), f"{value!r} is not an IBAN"
```

Now a scenario can say `Then its "account" is any iban`. **ATF ships no kind that knows a domain** —
`any uuid` is structure, `any iban` is your vocabulary, and the moment a framework learns one it is
asked for the next and spends its life maintaining a validation library nobody wanted from it.

## Write a system

A system is a class with four methods and a decorator. That is what a team writes once, and their
things then wear it.

```python
from atf import adapter, driver
from atf.spi import Record, Resource


@driver("redis")
class Redis:
    """What holds the connection. Built once per environment, from the block of its own name."""

    class Settings(TypedDict, total=False):
        url: str

    def __init__(self, settings: Settings) -> None:
        self.client = connect(settings["url"])


@adapter("key", driver="redis")
class Key:
    """One key. `@redis.key(...)` is now a decorator a suite can wear."""

    class Options(TypedDict, total=False):
        prefix: str

    #: What tells one of these apart. **The system answers this, never the author.**
    recognised_by = ("name",)

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def find(self, resource: Resource) -> Record | None:
        value = self.redis.client.get(resource.identity["name"])
        return {"name": resource.identity["name"], "value": value} if value is not None else None

    def create(self, resource: Resource) -> Record:
        self.redis.client.set(resource.values["name"], resource.values["value"])
        return dict(resource.values)

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        self.redis.client.set(resource.values["name"], changes["value"])
        return {**found, **changes}

    def delete(self, resource: Resource, found: Record) -> None:
        self.redis.client.delete(resource.values["name"])
```

Put it in `atf/` beside your things. Nothing registers it — a module in the suite directory is
imported, and importing it is what registers it.

### What a system sees

A `Resource` is your thing as the system sees it, and it never holds any of ATF's own objects:
`kind`, `name`, `options` (what the decorator took), `fields` (the annotations), `values` (the
declared scalars), `identity` (what recognises it), `parents` (lineage, already resolved to the keys
the parents were made as), `owner` and `lives`.

A system never looks a parent up. By the time `create` is called, every parent has been made and its
key is in `parents`.

### Recognition

Say `recognised_by` when there is only ever one answer — a file is its path. Implement
`recognises(resource)` when the system has to look, as `sql` does when it reads a table's unique
columns off the schema. Where there is genuinely nothing to ask, take it as an option on the
decorator: that is configuration of the system, not the author restating what the system knows.

### Everything else is optional

`browse` adds `When I list every …` and lets `atf plan` report undeclared things. `find_many`
answers about several at once, in one question. `begin`/`rollback` wrap a test in a transaction.
`capture` writes an artefact when a test goes red. Leaving `create`, `update` or `delete` out says
this kind of thing is never made, changed or removed, and asking refuses by name.

### Bring your words with your things

A system brings its things **and the words for them**. Register them in the same module:

```python
@act('I set "{key}" to "{value}"')
def _(key: str, value: str, redis: Redis) -> Record: ...
```

They appear in the generated reference under your system's heading, and `atf edit` offers them in
the composer — without ATF knowing anything about you.

## Hold it to the contract

Every system answers the same contract: create, read back, update, delete, delete again. It is not a
command — it ships with ATF as a feature file, written in the language ATF asks you to write in:

```console
$ atf run --contract
```

## Register a report format

```python
from atf import report


@report("tally")
def _(run, path):
    lines = [f"{one.outcome} {one.test}" for one in run.outcomes]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

`atf run --report tally:out.txt`.

## Check your work without running anything

```console
$ atf plan
```

Lint lives in `plan` so that an unknown sentence, an ambiguous phrase, or a scenario naming a thing
nothing declares is findable **with no database on your laptop**. A dead environment is a line in
the plan, not a reason to refuse to start.

`atf explain <your system>` lists the kinds it holds, the things declared in it, the words it brings
and the scenarios that use it.
