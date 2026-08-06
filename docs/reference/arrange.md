# Arrange

Arrange is where a test says what must exist before it acts. The examples on this page all come from
one module.

```python
from typing import Self

from faker import Faker

from adapters.sqlite import sqlite

faker = Faker()


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str

    @classmethod
    def factory(cls) -> Self:
        return cls(email=faker.email())


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner          # the dependency, and the foreign key
    slug: str


primary   = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

`sqlite` is not part of ATF. It is the worked example of an adapter, written once and living in the
suite's own `adapters/sqlite.py`, registered through the manifest's `extensions:` key. A decorator
imported from your own suite is the normal case; the systems ATF ships are listed under
[system](#system).

## Resource {#resource}

A resource is a thing that exists in an environment: a row, a file, a page, a process. It is
declared as a class, as `Owner` is above. The class is the shape, its annotated fields are the
resource's typed fields, and the decorator is the [system](#system) it belongs to. An instance —
`primary` — is one particular resource.

**Construction declares. It does not touch anything.** The statement is evaluated at import time;
whether it is true yet is asked of the environment when a test needs the resource, or when you run
`atf status`.

An instance's name is its variable's name, read by importing the modules listed under `resources`
in `atf.yaml`, as pytest names a fixture after its function. Renaming the variable renames the
resource, so `Given the todo_list "groceries"` breaks when `groceries` becomes `grocery_list`. A
resource built inside a function is not declared, because nothing binds it at module level.

**In CI** — `atf status <env>` reports every declared resource as `present`, `absent` or
`unreachable`. A run makes what its tests ask for; `atf make <env>` makes everything.

**In the editor** — resources are listed with their state, re-asked on each refresh, each linking
to the module line that declares it.

**To an agent** — `atf edit --mcp` serves resources as records: name, type, system, fields, lineage,
state. An agent names a resource without reading the module that declares it.

## Lineage {#lineage}

A resource depends on another by having a field typed as it — `TodoList.owner` above. This is dbt's
`ref()`, written as a field, and **nobody writes a dependency twice**. The closure follows the
field: asking for `groceries` arranges `primary` first, then `groceries`; asking for a `Task`
arranges its list and that list's owner.

ATF reads the graph off the annotations, and can answer questions the suite never stated.
`atf impact groceries` says what breaks if that resource changes, `atf run --select +groceries` runs
what touches it, and `atf unused` lists what nothing asks for.

The cost is that the dependency must be expressible as a typed field. A resource that needs another
one only sometimes, or needs one of three types, has nowhere to say so.

**In CI** — the graph decides the order things are made in, and `--select` uses it to run a slice of
the suite for a change that touched one resource.

**In the editor** — the graph is drawn. Selecting a resource highlights what it needs and what needs
it.

**To an agent** — the edges are served as data, so an agent asks what depends on what instead of
parsing annotations.

## Asking for one {#asking-for-one}

**A resource is a pytest fixture.** A test asks for one by putting it in its signature.

```python
def test_a(primary: Owner):        # that owner
    assert primary.email == "primary@example.com"


def test_b(owner: Owner):          # any owner — the factory builds one
    assert "@" in owner.email


def test_c(groceries: TodoList):   # that list, and primary comes with it
    assert groceries.owner.email == "primary@example.com"
```

The name resolves and the annotation types — pytest's own rule. The annotation is what your editor
and type checker read.

A parameter named after an instance gets that instance and everything its [lineage](#lineage) needs.
A parameter named after a type gets the one resource of that type in scope, or, when nothing is in
scope, one built by the [factory](#factory). A parameter named after neither gets pytest's own
error: there is no such fixture.

"In scope" means arranged by the surrounding scenario. Inside a scenario that said
`Given the todo_list "groceries"`, a step taking `todo_list: TodoList` is handed `groceries`. In a
plain test nothing arranged anything, so the factory runs.

Two of a kind in scope is an error. A scenario that arranged two owners leaves `owner: Owner`
ambiguous; ATF names both and asks which, picking neither the first nor the most recent. Answer it
by asking for the one you mean by name.

**In CI** — an unresolvable or ambiguous parameter is a collection error. The run fails before a
single test body executes, and the message names the file, the test and the candidates.

**In the editor** — each parameter shows what it will resolve to for the scenario it sits in.
Ambiguity is flagged where it is written, not when it runs.

**To an agent** — the resolution of every parameter is exposed, so an agent can check that a test it
wrote asks for what it meant.

## Factory {#factory}

A factory says how to build a resource nobody named. It is a classmethod on the resource, and
`TodoList` gains one by adding:

```python
    @classmethod
    def factory(cls, owner: Owner) -> Self:
        return cls(owner=owner, slug=faker.slug())
```

This is factory_boy's `SubFactory`, typed. The parameters are dependencies, and one the caller does
not supply is built by that resource's own factory, recursively: `list: TodoList` with nothing in
scope calls `TodoList.factory`, which calls `Owner.factory`, stopping at the first resource that
needs nothing.

A resource without a factory can only be asked for by name; asking for it by type, with nothing in
scope, is an error saying the type has no factory.

A factory-built arrangement uses different values on every run. The trade-off is that a failure
depending on a generated value may not reappear on the next run. Where a test is about one
particular value, declare an instance and ask for it by name.

**In CI** — two runs of the same test arrange different values, and a failure report carries the
values that run used.

**In the editor** — building one shows the values it generated, and running the same test again
generates different ones.

**To an agent** — factories are listed with the dependencies they take, so an agent knows which
types can be asked for without naming an instance.

## System {#system}

A system is a kind of place resources live. Every resource belongs to exactly one, and the decorator
is how it says which. Each system ships with its [adapter](#adapter) — the code that finds, creates,
updates and deletes there — and declares its own typed configuration. **Options** are written on the
decorator and vary per resource; **settings** are written in `atf.yaml` and vary per environment.

ATF ships four systems — the ones it needs to test itself.

`@command`
:   Arranges a command-line invocation. Its setting is `prefix`; it takes no options of its own.

`@browser(…)`
:   Arranges a page, opened and looked at. Its settings are `base_url` and `headless`; its option is
    `url`.

`@filesystem(…)`
:   Arranges files and directories. Its setting is `root`; its option is `path`.

`@process(…)`
:   Arranges a running process. Its setting is `cwd`; its option is `command`.

`rest` ships later, in the same shape: a decorator carrying its own options, a `rest:` block in each
environment, an adapter behind it. Everything else is an adapter somebody wrote, and nothing binds
ATF to one database. `@sqlite`, used throughout this documentation, is the worked example: it
arranges rows in a table, takes `path` as a setting and `table` as an option, and lives in the
suite's own `adapters/sqlite.py`. Its `table` defaults to the class name, so `TodoList` reads and
writes `todolist`; write the option only to override that.

Every decorator also takes the options that belong to ATF rather than to the system:

`unique_by`
:   The field that says which resource this is. No default. See [recognition](#recognition).

`when_absent`
:   What happens when the resource is not there. `"make"` unless stated. See
    [when it is not there](#when-it-is-not-there).

`scope`
:   How long the resource lives. `"persistent"` unless stated. See [scope](#scope).

`actions`
:   Domain verbs the resource answers to. No default. Defined in [act](act.md#action).

**In CI** — a resource whose system has no settings in the chosen environment stops the run at
start-up, naming the system and the environment rather than failing inside the first test.

**In the editor** — resources are grouped by system, and each system shows the settings in force for
the environment you are on, beside the options each resource carries.

**To an agent** — systems are listed with their resources, their settings and their option types, so
an agent can tell which sentences are available before writing one.

## Recognition {#recognition}

`unique_by` names the field that says which resource this is. `Owner` is recognised by `email`, so
two owners with the same email are the same owner. That is all `unique_by` asserts.

Where one field does not tell two resources apart, write several. A tenant recognised by its code
*within a region* says so, and two regions may then each have an `acme`.

```python
@sqlite(table="tenants", unique_by=("region", "code"))
class Tenant:
    region: str
    code: str
```

Every field named must be one the resource carries. A parent is not one of them: a dependency goes
in [depends_on](#lineage), and what a parent is called in a record is the adapter's business rather
than ATF's. A `unique_by` naming a field the resource does not declare is refused when the module
loads, because an empty identity matches whatever comes first.

**Uniqueness and lookup are two different questions.** A user may be unique by email and fetchable
only by a numeric id nobody writing a test knows. `unique_by` answers the first; the adapter's
`find` answers the second, and may search, filter, page or query however the system requires, so
long as it returns the resource with that email.

ATF never writes down what it created. It asks the environment, keyed on the recognised field, at
the moment the question is asked, so a row deleted by hand or a database reset overnight gives the
right answer immediately. [Why there is no state file](../explanation/why-there-is-no-state-file.md)
sets out what that design rules out, if you are deciding whether to fight it.

The cost is one query per resource per question, against the real environment. On a suite with
hundreds of resources that is hundreds of queries, and they are not free.

**In CI** — `atf status` and every run ask the environment directly. Nothing carries over between
runs, and there is no file to be stale, to be gitignored or to be repaired.

**In the editor** — refreshing re-asks. What you see is what the environment said a moment ago.

**To an agent** — presence is always a live answer. An agent that reads a resource as `absent` and
then makes it sees `present` on the next question.

## Reconciliation {#reconciliation}

Recognition asks whether the thing is there. Reconciliation is what ATF does with the answer.

```text
find  →  nothing        → create(resource)
      →  same           → done
      →  differs        → update(resource, found, changes)
```

A resource that exists but no longer matches its declaration is brought back to it: the run finds
the record, sees the difference and writes the declared value back, rather than dropping and
recreating it.

**ATF computes the diff, never the adapter.** `changes` reaches the adapter already worked out and
the adapter's job is to apply it, so the editor can show what pressing the button *would* alter,
field by field, before anything is pressed.

**A declaration is a partial specification.** The fields you named must hold; fields you did not
name are left alone, so a `created_at` the system set and a `colour` somebody picked in the product
survive untouched. The cost is the other side of that: an undeclared field can drift to anything and
ATF will neither correct it nor mention it. If a test depends on a value, declare it.

An environment with `mutable: false` reconciles nothing; a resource that differs there fails the
test that asked for it. [May be changed](the-ground.md#may-be-changed) sets out everything else an
immutable environment refuses, which you want before pointing a suite at one.

**In CI** — reconciliation is silent when nothing differs. Each update is recorded in the report
with the fields it changed, so a suite that quietly repairs the same field every night is visible as
a pattern rather than a mystery.

**In the editor** — a resource whose record differs is shown with the fields that would change and
the values on both sides.

**To an agent** — the diff is served as data before it is applied, so an agent can decide whether an
environment is in a state it wants to change.

## When it is not there {#when-it-is-not-there}

`when_absent` says what ATF does with a resource the environment does not have.

`"make"`
:   Makes it, then continues. Use it for anything ATF can make. This is the default; you rarely
    write it.

`"require"`
:   Fails the test, naming the resource and the environment. Use it for things the environment owns.

`"observe"`
:   Does nothing. The resource is read, never made. Use it for things you can only look at.

```python
@sqlite(table="plans", unique_by="code", when_absent="require")   # the environment's job
@browser(when_absent="observe")                    # something to look at
```

The default is named after `atf make`, which does the same thing from outside a run. It is not
called `create`: `create` is the adapter method underneath, and an `observe` resource still has a
working `create` it is never asked to use.

`require` is for a resource somebody else provisions — a todo_list seeded by a migration, an owner
set up by an ops runbook. The declaration still buys lineage, recognition and a place in the graph;
it gives up only the making. There is no blocked state and nothing is skipped.

`observe` is for a resource with no meaningful create at all. A checkout screen is not created; it
is opened and looked at. An absent `observe` resource is a fact about the environment rather than an
error, and whether it fails is decided by what the test claims about it. An absent resource ATF can
make is no blocker at all: `atf status` reports it as `absent` and says it can be made.

Two things override the default. `mutable: false` makes nothing, whatever `when_absent` says, and a
test needing an absent resource there fails — [may be changed](the-ground.md#may-be-changed) lists
the rest of what that setting stops. An `unreachable` system is the second, and is never read as
absence: ATF does not try to create a row in a database it could not connect to.

**In CI** — `require` failing names the resource and the environment, and the test fails without
acting. This is the check that catches a staging deploy that lost its seed data.

**In the editor** — absent-and-creatable is shown as information. `require` and `observe` resources
are marked, so it is clear why a button to make one is not there.

**To an agent** — when a resource cannot be made, the reason is returned as data: immutable
environment, `require`, `observe`, or an unreachable system. An agent gets a cause, not a stack
trace.

## Scope {#scope}

Scope is how long a resource lives once it has been made.

```python
@sqlite(table="guests", unique_by="nickname", scope="function")
```

`scope="persistent"`
:   Made once, the first time anything needs it, and never removed by ATF. This is the default.

`scope="session"`
:   Made once, the first time a test in the run needs it, and removed when the run ends.

`scope="function"`
:   Made before each test that asks for it, and removed after that test.

Two of the three words are pytest's, meaning what they mean in pytest. `persistent` is not, because
pytest has no lifetime that outlives the process: a persistent resource is still there tomorrow, and
the next run [recognises](#recognition) it instead of making it again.

Persistent is the default. Most resources are background — an owner, that owner's todo_list — and
every test in the suite is happy to share them. Session scope is for something a run should not
leave behind but every test in it may share: a tenant, a workspace, a seeded dataset that would
confuse the next person to look at the environment. Function scope is for a resource a test changes:
a guest a test renames is no longer the guest the next test expected, so `visitor` is made fresh and
removed after.

Teardown runs at the end of the scope — after the test, after the run — and always in reverse
lineage order, so a list is deleted before its owner. It runs after a failure too.

Each choice costs something. Function scope pays a create and a delete per test against the real
system, which is the bulk of the runtime in a suite that overuses it. Persistent scope leaves
resources behind by design, and `atf status` is the only thing that will tell you what is there.

A run that dies mid-test may leave a function-scoped resource behind. Because presence is asked, not
remembered, the next run reuses it rather than failing on a duplicate — absorbed rather than fatal,
but a test that assumed freshness may behave differently until it is cleared.

**In CI** — teardown runs between tests and at the end of the run, including after a failure. A
killed process is the one case that leaves scoped resources behind.

**In the editor** — persistent resources are there before you start and stay after you stop. Session
and function ones appear and disappear around a run.

**To an agent** — every resource reports its scope, so an agent can tell whether something it sees
in the environment will still be there after the next test.

## Variation {#variation}

A scenario changes one resource for the length of that scenario, one field per sentence.

```gherkin
Given the todo_list "groceries" but "slug" is "weekly"
And "owner" is "null"
```

The first sentence names the resource and the first field; each `And` names one more. `"groceries"`
is arranged with `slug` set to `weekly` and no owner at all. Fields nobody mentions keep the values
the declaration gave them.

`"null"` is not a value; it removes the field. What that means is the system's business: a
`NOT NULL` column rejects it, and the test fails with the system's own message. Removing a field
that carries [lineage](#lineage) drops that edge for this scenario, so the parent is not arranged
either — which is how you write a test about a list with no owner.

The patch is applied before [recognition](#recognition), so patching a recognised field names a
different resource: `groceries` with `slug` set to `weekly` is a second row, not the `groceries` row
renamed. Patching any other field changes the resource ATF makes, or
[reconciles](#reconciliation), under the recognised value it already has. A varied resource is
arranged for the scenario that varied it; nothing else sees the patch.

**In CI** — variation is part of the scenario, so a varied arrangement is as reproducible as an
unvaried one.

**In the editor** — the patch is shown beside the declaration it patches.

**To an agent** — the patch is served as data, separate from the base declaration.

## Adapter {#adapter}

An adapter teaches ATF a system. It is the only place where ATF touches anything.

**One adapter instance is built per system, per environment**, constructed with that environment's
settings and holding its own connection on `self`. There is no context object and no `connect` step;
if the adapter exists, it is already pointed somewhere.

```python
@adapter("sqlite")
class Sqlite:
    class Options(TypedDict):       # what the decorator takes, per resource
        table: str                  # named on the decorator, never guessed

    class Settings(TypedDict):      # what an environment configures
        path: str

    def __init__(self, settings: Settings):
        self.db = sqlite3.connect(settings["path"])

    def find(self, resource) -> Record | None: ...
    def create(self, resource) -> Record: ...
    def update(self, resource, found, changes) -> Record: ...
    def delete(self, resource, found) -> None: ...

    def act(self, resource, found, action) -> Any: ...   # optional
    def browse(self, resource) -> list[Record]: ...      # optional
```

Declaring an adapter ships a decorator with it: `@adapter("redis")` gives the suite `@redis(...)`.
Its `Options` type is what that decorator accepts, its `Settings` type is what a `redis:` block in
`atf.yaml` accepts, and both are checked before a run rather than inside one.

Every method takes the same first argument. `resource` is the declared resource, resolved. It
carries `.name`, the instance's name — `groceries`; `.kind`, the class's name — `TodoList`;
`.options`, this resource's options, typed by the adapter's own `Options`; `.identity`, the
recognised fields and their values, which is what `find` looks up on; and `.values`, every declared
field, with [lineage](#lineage) already resolved to what the parents were made as.

Four methods are required.

`find(resource)`
:   Returns the record, or `None` when it is absent, and raises `atf.Unreachable` when the system
    cannot be reached. Called whenever presence is asked: a run, `atf status`, an editor refresh.

`create(resource)`
:   Returns the record it made. Called when the resource is absent and `when_absent` is `"make"`.

`update(resource, found, changes)`
:   Returns the record after the change. Called when `find` returned something that differs from the
    declaration.

`delete(resource, found)`
:   Returns nothing. Called at teardown, at the end of a `function`- or `session`-scoped resource's
    life.

An adapter applies `changes` and reports what it wrote; [reconciliation](#reconciliation) shows
where that diff comes from. The four returns cover the whole of what an
[environment](the-ground.md#environment) can say: a record is `present`, `None` is `absent`,
`atf.Unreachable` is `unreachable`. Let a connection error out — an adapter that swallows it and
returns `None` turns an unreachable database into a suite that tries to create everything in it.

Two methods are optional. `act` unlocks `When I complete the task "laundry"` and the `actions=`
option on the decorator. `browse` unlocks `When I list every todo_list` and
`Then the environment has 2 todo_list`.

A system without `act` can still be arranged and claimed about; it has no verbs of its own. One
without `browse` can answer questions about a resource you named and none about the set of them.

**In CI** — an adapter that raises `atf.Unreachable` makes the resource `unreachable`, and the tests
needing it fail rather than passing quietly on nothing.

**In the editor** — `find` is what the editor calls on refresh, once per resource. An adapter with a
slow `find` is felt here first.

**To an agent** — which optional methods an adapter implements decides which sentences exist, and
that list is served, so an agent writes what the suite can actually run.

## Where to go next

- [Act](act.md) defines what a test does once its resources exist, including the actions declared
  with `actions=` above.
- [The ground](the-ground.md) defines the environments these resources live in, and the `atf.yaml`
  settings each system reads.
- [Extending ATF](extending-atf.md) writes an adapter out in full, alongside the steps and claims
  you can register.
