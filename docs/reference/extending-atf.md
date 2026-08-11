# Extending ATF

Six things a suite can teach ATF: a driver to work through, a system to talk to, a claim to make, a
marker to match values against, a format to write results in, and a rule its own specs must obey. What each thing *is* is
defined in the band that owns it; this page is how it gets registered.

## The idiom {#the-idiom}

Every registry works the same way: a decorator on a function or a class, taking a name or a
sentence.

```python
@driver("todo")
class App: ...

@adapter("owner", driver="todo")     # registers todo.owner, and hangs @todo.owner off App
class Owners: ...

@claim('the {type} "{name}" field "{field}" is a valid IBAN')
def _(record, field): ...

@marker("iban")
def _(value): ...

@report("junit")
def _(run, path): ...

@check("every scenario names an owning team")
def _(suite): ...
```

Registration happens on import. No register call, no entry-point table, no ordering between
registries.

## Where extensions are loaded from {#loading}

`extensions:` is a [manifest key](the-ground.md#environment-keys) like any other: a list of paths and
installed packages. A path is a file; a bare name is a package on the import path.

```yaml
extensions: [./adapters/todo.py, atf_payments]
```

Each entry is imported once, before anything else runs. `atf run`, `atf check`, `atf edit` and
`atf edit --mcp` load the same list, so a registration only some surfaces can see is not possible.

Two names registered into the same registry is an error at load, and the message names both
registrations and the modules they came from.

## Registering an adapter {#registering-an-adapter}

[Adapter](arrange.md#adapter) defines the thing itself: `find` and the optional writes, what
`resource` carries, and why `find` raising `atf.Unreachable` produces the third environment state.
[Driver](arrange.md#driver) defines the machinery an adapter works through. This section is the
registration of both.

**`@todo.owner` is an adapter, and it is one of the ones you have been using.** ATF ships
`@filesystem.file`, `@filesystem.directory`, `@filesystem.tree`, `@browser.page`, `@shell.process`,
`@http.record` and `@sql.row` — one per kind of thing, never one per technology. Every `@todo.owner()`
and `@todo.list(...)` in this documentation comes from the suite's own `adapters/todo.py`, named in
`extensions:`, and it goes through the application's own API rather than its database. Here is that
file, whole.

An adapter never compares. ATF finds the record, works out the difference from the declaration and
hands `update` a ready-made `changes` — see [reconciliation](arrange.md#reconciliation).

### A complete driver and its adapters

```python
# adapters/todo.py
from typing import TypedDict

from todo import Todo                       # the product under test

from atf import adapter, driver


@driver("todo")
class App:
    """The machinery: the application, opened once per environment."""

    class Settings(TypedDict):              # what atf.yaml supplies under `todo:`, per environment
        path: str

    def __init__(self, settings: Settings):
        self.app = Todo(settings["path"])


@adapter("owner", driver="todo")
class Owners:
    """One kind of thing. Registered `todo.owner`, and hung off the driver as `@todo.owner`."""

    recognised_by = ("email",)              # an owner is its email; a declaration says nothing

    def __init__(self, todo: App):          # the driver, asked for by name
        self.app = todo.app

    def find(self, resource):
        return self.app.find_owner(resource.identity["email"])

    def create(self, resource):
        return self.app.create_owner(resource.values["email"])

    def delete(self, resource, found):
        self.app.delete_owner(found["email"])


@adapter("list", driver="todo")
class Lists:
    """A list carries nothing but its identity, so there is no `update` to write."""

    recognised_by = ("slug",)

    def __init__(self, todo: App):
        self.app = todo.app

    def find(self, resource):
        return self.app.find_list(resource.identity["slug"])

    def create(self, resource):
        owner = resource.parents.get("owner")
        return self.app.create_list(owner.key if owner else None, resource.values["slug"])

    def delete(self, resource, found):
        self.app.delete_list(found["slug"])

    def browse(self, resource):
        return self.app.every_list()
```

`update` applies a decision rather than making one. Aim for that in any adapter: a merge and a
write. Neither of these has one, because neither resource carries a field beyond its identity —
`find` is the only method every adapter answers, and the rest are written where they mean something.

`Options` and `Settings` are typed configuration, and they belong to different objects.

- **Options are the adapter's, written on the decorator, and vary per resource.** `TodoList` lives
  in the `lists` table wherever it is made, so `table` is a property of the resource.
- **Settings are the driver's, written in the manifest, and vary per environment.** The database
  file differs between your laptop and CI, and no resource has an opinion about it.

An adapter asks for its drivers by parameter name; several drivers is several parameters. A driver
an adapter asks for that the environment does not configure fails at load, naming both.

Both are checked before anything connects. A misspelt key in `atf.yaml` fails at load with the field
name, not at the first test with a `KeyError`.

The decorator is named after the string given to `@adapter` and exported from the module that
registers it, so a resource imports it from there. ATF's own four are re-exported from `atf` —
`from atf import command`.

```python
# resources.py
from adapters.todo import todo


@todo.owner()
class Owner:
    email: str


@todo.list(depends_on=[Owner])
class TodoList:
    slug: str
```

```yaml
environments:
  local:
    sql: { path: ./todo.db }
```

No adapter implements a method for domain verbs. `update` is required, and
[`When the task "laundry" field "done" becomes "1"`](act.md#action) reaches it — so the moment an
adapter exists, every resource of that system can be moved mid-test, and a
[phrase](act.md#domain-verb) is what gives that move the domain's own word.

- **In CI** — `atf status local` counts `TodoList` resources alongside every other type, and
  `atf make local` makes them.
- **In the editor** — `todo.owner` appears in the [catalogue](the-editor.md#catalogue) as a type, with
  its instances, their state and their create bodies, and the composer offers a `becomes` sentence
  for each of their fields.
- **To an agent** — the same, through the `status` and `make` tools, with `todo.owner` in the type list.

The cost is real: an adapter owns its own correctness. `find` returning a stale record, `update`
writing a field it was not given, or `delete` leaving residue produces failures in the next run and
in a different place. Write the adapter, then run a suite twice against it.

## Registering a claim {#registering-a-claim}

[Claim](assert.md#claim) defines the thing itself, and lists every sentence ATF ships. This section
is the registration: a sentence of your own, and a function that answers it with a verdict and a
message.

```python
from atf import claim

from .iban import iban_ok


@claim('the {type} "{name}" field "{field}" is a valid IBAN')
def _(record, field):
    value = record[field]
    return iban_ok(str(value)), f'{field} is "{value}", which is not a valid IBAN'
```

```gherkin
Then the account "primary" field "iban" is a valid IBAN
```

Placeholders in the sentence become parameters by name. Three parameter names are resolved rather
than matched: `record` is the resource named by `{type}` and `{name}`, `result` is the named result
slot, and `env` is the environment. Take the ones you need and leave the rest out of the signature.

The message is used only when the verdict is false; quote the value it rejected.

- **In CI** — the sentence parses and fails like any built-in, with your message.
- **In the editor** — the composer offers it wherever its subject exists, and its failures render
  like any other.
- **To an agent** — it appears in the legal steps at that position, used without being told it
  exists.

## Registering a marker {#registering-a-marker}

[Marker](assert.md#marker) defines the thing itself, and lists the eight ATF ships — `#uuid`,
`#datetime`, `#date`, `#absent`, `#present`, `#int`, `#str` and `#bool`. This section is how a team
adds its own.

```python
from atf import marker

from .iban import iban_ok


@marker("iban")
def _(value):
    return iban_ok(str(value)), "not a valid IBAN"
```

**The name is registered without the sigil.** `#` is how a marker is said in a scenario, the way `@`
is how a tag is written — syntax, not part of the name.

A marker returns a verdict and a message, exactly as a claim does, and the failure reads as the
field, the value found and your message. A marker is a *value*: it stands anywhere a value stands,
in any field claim, in a phrase, in a claim someone else registered. A claim is a *sentence*: it
owns its subject and its wording.

The IBAN above is the same rule as [the claim](#registering-a-claim), written both ways. The marker
is usually the better trade — one registration, working in every sentence that compares a value.
Reach for a claim when the rule is about a record rather than a field, or when the sentence itself
is what you want the scenario to say.

- **In CI** — usable anywhere a value is compared.
- **In the editor** — it appears in the marker picker, and in the value hints wherever a claim takes
  a value.
- **To an agent** — it appears in the marker list the agent reads before writing a claim.

## Registering a report format {#report-format}

A report format turns a run into a file. `atf run --report <format>:<path>` selects one by name.
[`ctrf` is the only format ATF ships](the-record.md#report); JUnit XML, Allure, or a line per test
for a chat message are registered here, and the name becomes one `--report` and `atf import-run`
both accept. The function receives the run record and the destination path.

The function receives a [run](the-record.md#a-run) and a `Path`. The run's shape is owned by that
page and not restated here: `run.environment`, `run.started`, `run.finished`, and `run.outcomes` —
one [outcome](the-record.md#outcome) per test, each with `test`, `outcome`, `duration_ms` and
`failed_at`. `failed_at` is `None` on anything that did not fail, and carries the file, the line,
the step and the message on anything that did.

```python
import xml.etree.ElementTree as ET

from atf import Outcome, report


@report("junit")
def _(run, path):
    failures = sum(one.outcome is Outcome.FAILED for one in run.outcomes)
    suite = ET.Element("testsuite", name=run.environment,
                       tests=str(len(run.outcomes)), failures=str(failures))
    for one in run.outcomes:
        case = ET.SubElement(suite, "testcase", name=one.test,
                             time=f"{one.duration_ms / 1000:.3f}")
        if one.failed_at is not None:
            ET.SubElement(case, "failure", message=one.failed_at.message)
        elif one.outcome is Outcome.SKIPPED:
            ET.SubElement(case, "skipped")
    ET.ElementTree(suite).write(path, encoding="utf-8")
```

```sh
atf run --report junit:out.xml
```

The record is read-only. A format that raises fails the command after the tests have already been
reported, so a broken report never turns a passing run red.

- **In CI** — available to `--report` and to `atf import-run`, which reads the same names back.
- **In the editor** — it appears in the export options on a completed run in
  [activity](the-editor.md#activity).
- **To an agent** — the `run` tool accepts the format name in the same argument, so an agent can
  produce a file for a pipeline it does not otherwise control.

## Registering a check {#registering-a-check}

[`atf check`](the-command.md#check) asks whether the suite is well formed. Its rules are a registry,
so a team's own conventions are checked by the same command, at the same moment, as ATF's.

A check receives the suite and yields findings. A finding is a subject and a sentence; ATF turns the
subject into a file and a line.

```python
from atf import check

TEAMS = {"billing", "identity", "payments"}


@check("every scenario names an owning team")
def _(suite):
    for scenario in suite.scenarios:
        if not TEAMS & set(scenario.tags):
            yield scenario, f"no team tag; expected one of {', '.join(sorted(TEAMS))}"
```

```console
$ atf check
specs/checkout.feature:31  paying with a saved card
  no team tag; expected one of billing, identity, payments

1 problem
```

The suite is the parsed model, not the source text: `suite.scenarios`, `suite.phrases`,
`suite.resources` and `suite.tests`, each element carrying its name, its tags and where it was
written. A resource carries `needs`, the lineage it declares.

A check yields findings and does not raise. A rule that yields nothing passes.

- **In CI** — `atf check` exits `1` on any finding, so a team rule blocks a merge exactly as a
  malformed step does.
- **In the editor** — the overview's "suite" line counts your findings with the rest, each linking
  to the scenario it names.
- **To an agent** — the `check` tool returns the findings structured, so an agent reads the rule it
  broke.

## The built-ins are the first client {#first-client}

One rule governs all five registries: **ATF's own built-ins are registered through them.**

`@filesystem.file`, `@filesystem.directory`, `@filesystem.tree`, `@browser.page`, `@shell.process`, `@http.record` and `@sql.row` are adapters registered with `@adapter`,
through the same decorator the `@sql.row` above uses. `#uuid` and `#datetime` are markers registered
with `@marker`. Every sentence in [Assert](assert.md) is a claim registered with `@claim`. The CTRF
report is a format registered with `@report`. The rules `atf check` applies to your specs are checks
registered with `@check`.

The cost lands on ATF. A registry interface six built-ins depend on cannot be widened for one of
them without widening it for everyone, and cannot be narrowed without breaking ATF first. Some
built-in behaviour is slower or more roundabout than a private door would have made it.

The consequence: nothing you register is second class. A marker you added is compared by the same
code as `#uuid`; an adapter you wrote is counted, catalogued and made by the same code as `@filesystem.file`,
and a driver you wrote is built and handed over by the same code as `filesystem`.

## Sharing a vocabulary {#sharing}

Everything above is a Python import, so a team packages its markers, claims, adapters, steps and
phrases as an ordinary Python package, publishes it to whatever index it already uses, and names it
in the manifest.

```sh
atf-payments/
  pyproject.toml
  atf_payments/
    __init__.py
    iban.py            # the checksum
    markers.py         # @marker("iban")
    claims.py          # @claim('… is a valid IBAN')
    ledger.py          # @adapter("ledger")
    specs/
      payments.feature # @phrase scenarios
```

```python
# atf_payments/__init__.py
from . import claims, ledger, markers  # noqa: F401  — importing registers
```

```yaml
extensions: [atf_payments]
```

Phrases ship with it. A package may carry a `specs/` directory, and its phrases join the suite's own
flat namespace, under the same collision rule: two phrases with one sentence is an error naming
both.

The trade-off: a shared vocabulary is a shared dependency, and a sentence that changes meaning
changes it for everyone. Version the package and treat a phrase's wording as its public
interface.

## What is not extensible {#limits}

Each of these is closed because something else depends on it being a known, finite set.

- **The bands and the concepts.** No sixth band, and no kind of thing between a resource and a test.
  A suite-specific concept would be invisible to the editor and to an agent.
- **The two vocabularies.** `present` · `absent` · `unreachable` and `passed` · `failed` · `skipped`
  are fixed. There is no fourth outcome and no custom verdict, because a fold over an open set has
  no definition.
- **`when_absent` and `scope`.** `make`, `require` and `observe`; `function`, `session` and
  `persistent`. An adapter cannot add a lifecycle. The provisioning order is computed from these
  values across the whole graph, and one unknown value makes the order unknowable.
- **The Gherkin grammar.** `Given` · `When` · `Then`, the `but` variation, `as "name"`, the marker
  sigil. You extend the *vocabulary* with phrases and steps; you cannot add a keyword or an
  operator, and you cannot add a form — a scenario is sentences, and anything structured is several
  of them.
- **Resolution.** The name resolves and the annotation types. This is pytest's own rule, and it is
  not pluggable.
- **The editor's views.** Registries add content to the views that exist. They do not add views, and
  there is no plugin surface — see [no privileged path](the-editor.md#no-privileged-path).
- **Where history lives.** Not a plug point.

If a system genuinely needs a lifecycle ATF does not have, model it as a resource declared
`when_absent="require"` whose existence the environment owns. The cost is plain: the thing is made
outside ATF, and the suite only checks that it is there.

## Where to go next

- [The editor](the-editor.md) — what registering into each of these five changes on screen, and why
  a concept that needs a special case to be rendered is not finished.
- [Teach ATF a new system](../how-to/teach-atf-a-new-system.md) — the same work as a task, against a
  system ATF has never heard of, from an empty file to a passing test.
- [The concept budget](../explanation/the-concept-budget.md) — why the closed sets above are closed,
  and what was left out to keep them small.
