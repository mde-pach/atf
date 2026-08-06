# Extending ATF

Five things a suite can teach ATF: a system to talk to, a claim to make, a marker to match values
against, a format to write results in, and a rule its own specs must obey. What each thing *is* is
defined in the band that owns it; this page is how it gets registered.

## The idiom {#the-idiom}

Every registry works the same way: a decorator on a function or a class, taking a name or a
sentence.

```python
@adapter("sqlite")
class Sqlite: ...

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
extensions: [./adapters/sqlite.py, atf_payments]
```

Each entry is imported once, before anything else runs. `atf run`, `atf check`, `atf edit` and
`atf edit --mcp` load the same list, so a registration only some surfaces can see is not possible.

Two names registered into the same registry is an error at load, and the message names both
registrations and the modules they came from.

## Registering an adapter {#registering-an-adapter}

[Adapter](arrange.md#adapter) defines the thing itself: the four required methods, the two optional
ones, what `resource` carries, and why `find` raising `atf.Unreachable` produces the third
environment state. This section is the registration.

**`@sqlite` is an adapter, and it is the one you have been using.** ATF ships `@command`,
`@browser`, `@filesystem` and `@process` — the systems it needs to test itself — and nothing that
binds it to a database. Every `@sqlite(table=…, unique_by=…)` in this documentation comes from the suite's
own `adapters/sqlite.py`, named in `extensions:`. Here is that file, whole.

An adapter never compares. ATF finds the record, works out the difference from the declaration and
hands `update` a ready-made `changes` — see [reconciliation](arrange.md#reconciliation).

### A complete adapter

```python
# adapters/sqlite.py
import sqlite3
from typing import NotRequired, TypedDict

from atf import Unreachable, adapter


@adapter("sqlite")
class Sqlite:
    """Ships the @sqlite(...) decorator with it."""

    class Options(TypedDict):          # what @sqlite(...) accepts, per resource
        table: str                     # named on the decorator, never guessed

    class Settings(TypedDict):         # what atf.yaml supplies under `sqlite:`, per environment
        path: str

    def __init__(self, settings: Settings):
        self.path = settings["path"]
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row

    def table(self, resource):
        return resource.options.get("table", resource.kind)

    def columns(self, values):
        """A field typed as another resource arrives as that resource's record."""
        for field, value in values.items():
            yield (f"{field}_id", value["id"]) if isinstance(value, dict) else (field, value)

    def find(self, resource):
        where = dict(self.columns(resource.identity))
        clause = " AND ".join(f"{column} = ?" for column in where)
        try:
            row = self.db.execute(
                f"SELECT * FROM {self.table(resource)} WHERE {clause}", tuple(where.values())
            ).fetchone()
        except sqlite3.Error as failure:
            raise Unreachable(f"sqlite at {self.path}: {failure}") from failure
        return dict(row) if row else None

    def create(self, resource):
        row = dict(self.columns(resource.values))
        marks = ", ".join("?" * len(row))
        self.db.execute(f"INSERT INTO {self.table(resource)} ({', '.join(row)}) "
                        f"VALUES ({marks})", tuple(row.values()))
        self.db.commit()
        return self.find(resource)

    def update(self, resource, found, changes):
        row = dict(self.columns(changes))
        assignments = ", ".join(f"{column} = ?" for column in row)
        self.db.execute(f"UPDATE {self.table(resource)} SET {assignments} WHERE id = ?",
                        (*row.values(), found["id"]))
        self.db.commit()
        return {**found, **row}

    def delete(self, resource, found):
        self.db.execute(f"DELETE FROM {self.table(resource)} WHERE id = ?", (found["id"],))
        self.db.commit()
```

`update` applies a decision rather than making one. Aim for that in any adapter: a merge and a
write.

`Options` and `Settings` are the adapter's typed configuration.

- **Options are written on the decorator and vary per resource.** `TodoList` lives in the `lists`
  table wherever it is made, so `table` is a property of the resource.
- **Settings are written in the manifest and vary per environment.** The database file differs
  between your laptop and CI, and no resource has an opinion about it.

Both are checked before anything connects. A misspelt key in `atf.yaml` fails at load with the field
name, not at the first test with a `KeyError`.

The decorator is named after the string given to `@adapter` and exported from the module that
registers it, so a resource imports it from there. ATF's own four are re-exported from `atf` —
`from atf import command`.

```python
# resources.py
from adapters.sqlite import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str
```

```yaml
environments:
  local:
    sqlite: { path: ./todo.db }
```

An adapter that also implements `act` declares which verbs it accepts, and resources opt in through
`actions=`, exactly as `@sqlite(..., actions={"complete": Update(done=True)})` does.

- **In CI** — `atf status local` counts `TodoList` resources alongside every other type, and
  `atf make local` makes them.
- **In the editor** — `sqlite` appears in the [catalogue](the-editor.md#catalogue) as a type, with
  its instances, their state and their create bodies. Where `act` is implemented, the composer
  offers its verbs.
- **To an agent** — the same, through the `status` and `make` tools, with `sqlite` in the type list.

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

`run.environment`
:   The environment's name.

`run.started_at`, `run.finished_at`
:   Timestamps.

`run.outcomes`
:   One per test.

`outcome.test`
:   The scenario or function name.

`outcome.outcome`
:   `passed`, `failed` or `skipped`.

`outcome.duration`
:   Seconds, as a float.

`outcome.message`
:   The failure message, or `None`.

`outcome.tags`
:   The test's tags.

```python
import xml.etree.ElementTree as ET

from atf import report


@report("junit")
def _(run, path):
    failures = sum(o.outcome == "failed" for o in run.outcomes)
    suite = ET.Element("testsuite", name=run.environment,
                       tests=str(len(run.outcomes)), failures=str(failures))
    for o in run.outcomes:
        case = ET.SubElement(suite, "testcase", name=o.test, time=f"{o.duration:.3f}")
        if o.outcome == "failed":
            ET.SubElement(case, "failure", message=o.message)
        elif o.outcome == "skipped":
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

`@command`, `@browser`, `@filesystem` and `@process` are adapters registered with `@adapter`,
through the same decorator the `@sqlite` above uses. `#uuid` and `#datetime` are markers registered
with `@marker`. Every sentence in [Assert](assert.md) is a claim registered with `@claim`. The CTRF
report is a format registered with `@report`. The rules `atf check` applies to your specs are checks
registered with `@check`.

The cost lands on ATF. A registry interface five built-ins depend on cannot be widened for one of
them without widening it for everyone, and cannot be narrowed without breaking ATF first. Some
built-in behaviour is slower or more roundabout than a private door would have made it.

The consequence: nothing you register is second class. A marker you added is compared by the same
code as `#uuid`; an adapter you wrote is counted, catalogued and made by the same code as
`@command`.

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
