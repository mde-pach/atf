# Point it at your own system

`todo.py` has done its work. Delete it, delete `todo.db`, and delete `specs/showing-a-list.feature`
and `specs/test_ownership.py`. Keep `resources.py`, `adapters/sqlite.py`,
`specs/declarations.feature`, `specs/ownership.feature` and `specs/phrases.feature`.

Six things stand between that suite and your own system — the decorator, recognition, what ATF does
with what it finds, what to do when something is not there, how long it lives, and whether the
environment may be changed — then the manifest that ties them to a place.

## The decorator is the system

```python
@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
```

The decorator says which system holds the class and carries that system's own configuration — for
sqlite, which field identifies a row. This is a Django model's `Meta`, except it also names the
system. What it does not carry is *where*: no path, no host, no credentials. Those live in the
environment, so one class runs against your laptop and against staging without an `if` anywhere.

Four systems ship with ATF. `@command` holds a command-line invocation, which is how chapter 1 ran
`todo show` and read its output. `@browser` holds a page and what is on it, for acting on a web
interface. `@filesystem` holds files and directories — fixtures, uploads, generated artefacts.
`@process` holds a running process, for a server the tests need up. Each takes configuration of its
own, listed in full under [system](../reference/arrange.md#system) when you come to write the
environment block below.

`@sqlite` is not among them. It came from `adapters/sqlite.py` in the suite you were handed, and that
is where every other system comes from: somebody writes the adapter once and `extensions:` loads it.
If your database is Postgres, or the thing your tests arrange is a queue,
[Teach ATF a new system](../how-to/teach-atf-a-new-system.md) walks through the file you have been
using since chapter 1.

`@rest` ships later. Until then, an HTTP API is reached with a client of your own: an ordinary
pytest fixture taking its base URL and token from the process environment. A client acts and reads;
the arrange still comes from a declaration, because a client that creates records is setup code
again and the graph loses sight of what exists.

Most suites use two systems, one that **arranges** and one that **acts** — for you, probably a
database and either a CLI or a browser.

## Recognition

Chapter 3 put a `unique_by` on every declaration. The question it answers, exactly:

> Given two records, are they the same record?

That is not "how do I fetch it". A user is unique by email — no two may share one — but the API
fetches by an id the server assigns. `unique_by` names the field that makes a record itself; getting
from it to the record is the system's problem.

The trade-off is unforgiving. A `unique_by` that is not actually unique gives you a suite that
passes once and then drifts: the second run duplicates instead of recognising, and the first claim
that counts anything fails weeks later. Choose the field with the constraint on it, not the field
that reads best.

## What ATF does with what it finds

Recognition finds the record. What happens next is the whole of provisioning, and it is three cases:

```text
find  →  nothing   →  create it
      →  the same  →  nothing to do
      →  different →  update it
```

The third case matters most: ATF does not only make what is missing, it **ensures the state you
declared**. Yesterday's run completed `laundry`; today's run recognises the same task, sees `done`
where the declaration says `0`, and sets it back.

A declaration is a partial specification. The fields you named must hold; the fields you did not
name are left alone. Your suite says an owner's email and says nothing about their plan, so the plan
somebody set by hand last month survives untouched.

So you need neither a clean database nor to have been the last person in it. ATF computes the
difference itself, never the system underneath, so it can show you that difference before it writes:

```sh
atf make staging --dry-run
```

## When it is not there

By default, absent means make it. That is right for the records your tests own, and wrong for the
records the environment owns:

```python
@sqlite(table="plans", unique_by="code", when_absent="require")
class Plan:
    code: str


free = Plan(code="free")
```

`when_absent="require"` says: look for it, never make it. Use it for anything a migration, a seed
script or another team owns — pricing plans, feature rows, reference data, the tenant your suite
lives in. Without it, a missing plan becomes a row ATF invents and twelve claims that fail for
reasons that make no sense. With it, `atf status staging` reports the plan **absent** before
anything runs, and a test that needs it fails naming the plan.

Some things cannot be made at all, in any environment:

```python
@browser(when_absent="observe")
class Checkout:
    path: str


checkout = Checkout(path="/checkout")
```

A page is something to look at. There is nothing to create and nothing to clean up, and `observe`
says so.

## How long it lives

By default a resource outlives the run that made it. That is `scope="persistent"`, and it is why the
owner from chapter 1 was still in `todo.db` afterwards. ATF never tears a persistent resource down.

There are two other values, and both are pytest's words meaning what they mean there.
`scope="session"` lives for one run and goes when the run ends. `scope="function"` lives for one
test and goes when that test ends. `persistent` is not pytest's, because pytest has no lifetime that
outlives the process. It is the default because it makes the second run cheap: what the last run
made is still there, and recognition finds it. Some things must be fresh instead:

```python
@sqlite(table="guests", unique_by="nickname", scope="function")
class Guest:
    nickname: str


visitor = Guest(nickname="visitor")
```

`scope="function"` builds it before each test that asks for it and removes it after. Use it where a
test mutates the resource in a way the next test would notice.
[Make something fresh for each test](../how-to/make-something-fresh-for-each-test.md) sets the three
lifetimes against each other, and says what teardown does when a test fails or a process is killed.

One check proves all of this works, and it is not a green run:

```sh
atf run
atf run
```

**Run the suite twice in a row, against the same environment, without cleaning up in between.**
Everything persistent must be recognised rather than duplicated, and everything function-scoped must
be gone. A suite that passes once and fails the second time has a `unique_by` that does not
recognise, or a teardown that did not happen — and the residue never fails where it was left. It
fails in a count, in an ordering, in a test that looks innocent.

Each scope costs something. Function scope costs a create and a delete per test; on a slow system
that is the whole run time. Session scope costs isolation. Persistent costs you whatever the last
run left behind. Choose per resource: guests are fresh, plans are not.

## The environment may not be changed

Creating, updating and deleting is a permission, not a capability. Chapter 1's `local` said
`mutable: true`; the `staging` block below says nothing, so ATF creates, updates and deletes nothing
there. It still looks — `atf status staging` reports every resource **present**, **absent** or
**unreachable** — and every test whose arrange is already satisfied runs normally, so a read-only
environment runs a subset of your suite. A test that would have to change something **fails** there,
naming the resource it could not provision. There is no state between passing and failing.

## The manifest

One file names the resources, the specs, and every place they can exist:

```yaml
resources: [./resources.py]
specs: ./specs
extensions: [./adapters/sqlite.py]
default_env: local

environments:
  local:
    mutable: true
    sqlite:  { path: ./app.db }
    command: { prefix: "python -m myapp" }

  staging:
    sqlite:  { path: /srv/app/app.db }
    browser: { headless: true }
```

An environment is a set of system configurations under a name — the settings that change per place.
The commands that take an environment take its name:

```sh
atf status staging          what is present, absent or unreachable
atf make staging            make what is missing, where that is allowed
atf make staging --dry-run  what it would create and change, without doing it
```

## What actually changed

Nothing in `resources.py`, and nothing in the scenarios. A declaration names a shape, a system and a
recognition field, and all three were already yours; what changed is the environment block.
[Chapter 3's scenarios](3-declare-what-it-needs.md#run-everything) are unedited, and none of them
names a database, a path or a command.

A scenario names the domain; a declaration names the system; the environment names the place. The
limit is that the domain has to be yours: if your system calls it an `account`, rename the class and
rename it in the scenarios — once, for the domain, and never again for the system.

## Look before you run

`atf status` first, always. Does ATF find what you told it about?

```console
$ atf status local
```

```text
local — mutable

  present   owner      "primary"        primary@example.com
  absent    todo_list  "groceries"      slug=groceries, owner="primary"
  present   plan       "free"           code=free
```

An owner your database already had, a list it did not, and a plan somebody's migration put there.
`absent` is a resource the next test that asks for it will make, and `atf status` exits `0` for it.
The line to read carefully is the plan — it is `when_absent="require"`, so had it said `absent` you
would have known before running anything.

Now run:

```console
$ atf run
```

```text
specs/declarations.feature

  Scenario: a new owner has no lists
    ...

  Scenario: a list shows up under its owner
    passed   Given the todo_list "groceries"
    passed   When I run "todo show primary@example.com"
    passed   Then the result field "output" contains "groceries"
    passed   And the owner "primary" exists

  Scenario: completing a task
    ...

  Scenario: a list with no owner belongs to nobody
    ...

specs/ownership.feature
  ...

5 tests, 5 passing
```

Green against your own database, running your own command, from scenarios you wrote in chapter 3
and have not edited since.

## Run only what a change touched

`atf run --select +primary` runs the tests that depend on `primary` and nothing else — the same
traversal `atf impact` prints, used to choose. Two of its answers look alike and are not.
`--select +primry` names nothing that exists, so the run never starts and the exit code is `2`.
`--select +visitor` names a real resource that no test asks for, so there is nothing to run and the
exit code is `0`. A typo must not go green. A correct selection with no work in it must not go red.

## Look at what you have

```sh
atf edit
```

The editor draws the graph: every resource, every edge between them, every test that asks for
one, and the verdict each carried out of the last run. Two commands read the same graph from the
terminal — `atf impact <name>` for what breaks if that resource does, and `atf unused` for what
nothing asks for.

## Where to go next

- [Configure an environment](../how-to/configure-an-environment.md) — every key each system takes in
  `atf.yaml`, for when `atf status` cannot reach yours.
- [Run ATF in CI](../how-to/run-atf-in-ci.md) — exit codes, `--report ctrf:out.json`, and bringing the
  results back with `atf import-run`.
- [The ground](../reference/the-ground.md) — environments, mutability and what makes one
  unreachable, in full, including the failure modes this chapter only named.
- [Declared, not executed](../explanation/declared-not-executed.md) — why the ordering is derived
  rather than written, and what that costs when it goes wrong.
