# Phase 0 — what the two prototypes found

MIGRATION.md §6 says to prototype §1.1 and §1.2 against real pytest before writing anything else,
because they are the two places the design could fail to be implementable. Both are implementable.
One is harder than the document says; the other is easier, and for a different reason than expected.

Measured on Python 3.11.9, pytest 9.1.1, pytest-bdd 8.1.0.

```bash
cd prototypes/phase0 && uv run python -m lineage.run   # §1.1 — 8 cases x 5 strategies
./fixtures/run.sh                                      # §1.2 — real pytest, two runs
```

---

## §1.1 — decided: lineage stops depending on annotations

**A dependency is declared outright, with `depends_on`. No annotation carries one.**

This is the third option §1.1 itself offers, and it is the only one that survives the objection that
killed the other two: **a dependency need not be expressible in the resource's shape.** A report is
written per owner and stores only its slug and a rendered blob. There is nowhere to put an `owner`
field, so under typed-field lineage there was no edge — not a silent one, none at all. No amount of
care about *when* annotations are resolved fixes a dependency that has no field to live in.

A typed field was doing two jobs. They are now separate:

- **`depends_on`** says what must exist first. It is the graph, and it is all the graph is.
- **the fields** say what gets written. A field may hold a parent, or the shape may have no room for
  one, and neither changes the graph.

`@resource` is the base decorator and owns everything belonging to ATF rather than to a system —
`unique_by`, `when_absent`, `scope`, `actions`, `depends_on`. `@adapter("sqlite")` mints `@sqlite`,
which is `@resource` with a system and that system's own options bound. A suite writes `@sqlite`;
ATF only ever reads `@resource`.

**`depends_on` takes kinds and instances, and which one it is says what is meant.** A kind means any
of them, answered by anything already supplied of that kind and otherwise by the factory. An
instance means that one.

```python
@sqlite(table="lists",   unique_by="slug", depends_on=[Owner])   # any owner
class TodoList: ...

@sqlite(table="reports", unique_by="slug", depends_on=[Owner])   # any owner, and no field can hold it
class Report: ...

groceries = TodoList(owner=primary, slug="groceries")            # names which one
scratch   = TodoList(slug="scratch")                             # names none — the factory builds one
quarterly = Report(slug="quarterly", depends_on=[primary])       # names which one, with no field to do it
```

Construction is ordinary, as `DESIGN.md` writes it: the decorator installs the `__init__`, so the
class a suite writes stays the class a suite writes and construction still touches nothing. Where
the shape does hold the parent, passing it as a value declares the edge and there is no second place
to repeat it, so "nobody writes a dependency twice" survives.

`lineage/run_explicit.py` shows the graph still answers everything it is sold on: provisioning order
from one name, teardown in reverse, `atf impact`, `atf unused`, an incomplete declaration named
before a run, and a cycle refused. **The whole of §1.1's risk goes with the annotations** — there is
nothing left to resolve, so there is nothing left to resolve wrongly, and risk 1 in MIGRATION.md's
ranking is closed rather than mitigated.

Two consequences worth carrying forward. The adapter is handed its parents already resolved, so a
foreign key is read from there rather than from a field that had to exist to carry it. And a
factory learns what it needs from the kind's `depends_on` rather than from its own signature.

### Still true, and still worth doing

Suites should not write `from __future__ import annotations`, and ATF should refuse a resource
module that does. It no longer protects lineage, but it keeps the shape readable and costs five
lines. `lineage/run_no_future.py` measures what that import changes:

| Shape | With the future import | Without it |
|---|---|---|
| parent above child | resolves | resolves — the annotation **is** the class |
| forward reference | silent unless ATF resolves late | `NameError` at import, from Python, by line |
| `TYPE_CHECKING` import | unresolvable; needs the registry | `NameError` at import, from Python, by line |

Without it a forward reference and a `TYPE_CHECKING` import are `NameError`s from Python, at import,
by file and line — rather than something ATF has to notice.

### Superseded — the two analyses that kept annotations

Everything from here to the §1.2 heading treated lineage as something read off annotations. It is
kept as the evidence for not doing that: it is what the problem looks like when the mechanism is
wrong, and it measures a failure mode — an edge lost in silence — that `depends_on` cannot have.

The strategy it arrived at, for the record:

**Resolve eagerly, once every `resources:` module has been imported, field by field, falling back to
the registry of declared kinds, and hard-error only where a kind name is claimed twice.**

Eight cases, five strategies. Only one combination lost an edge with no error raised.

| Case | What it is | Answer |
|---|---|---|
| c1 | parent above child | resolves |
| c2 | forward reference — parent *below* child | resolves, but **not at decoration time** |
| c3 | parent imported under `TYPE_CHECKING` | resolves **only** via the registry |
| c4 | parent imported normally | resolves |
| c5 | factory typed `-> Self` | resolves, including the factory's parameters |
| c6 | `Owner \| None` and `Optional[Owner]` | resolves |
| c7 | aliased parent + a non-lineage field that will not evaluate | resolves the edge, ignores the field |
| c8 | two kinds both called `Owner` | **refused, by name** |

### The four things that decided it

**Resolution cannot happen in the decorator.** The decorator runs while the module is still
executing, so a forward reference is a `NameError` (c2). PEP 563 is precisely what makes forward
references legal to write, so suite authors will write them. ATF imports the `resources:` modules
itself, so it owns the moment after: import them all, then resolve them all.

**`typing.get_type_hints(cls)` is the worst available option.** It is all-or-nothing. In c7 a single
field ATF has no interest in — `balance: Decimal`, imported under `TYPE_CHECKING` — raises, and
every edge on the class is lost with it, including the correct `owner` one. Evaluating field by
field keeps the edge and reports only the field that failed.

**The registry is what rescues a `TYPE_CHECKING` import.** In c3 nothing evaluates the annotation,
and no amount of care with namespaces will. ATF knows every declared kind, so an annotation reading
`Owner` that will not evaluate can be matched against the kinds themselves. This is the one branch
carrying real risk, and it is the one that makes the common case work.

**Failing on anything unresolvable is wrong.** It rejects c7, which is a correct module. The
discriminator is the registry: a name no declared kind answers to *cannot* be a lineage edge, so
passing over it is safe rather than optimistic.

### The procedure

```
annotation evaluates            -> that class, whatever it was aliased to
does not, names no kind         -> not lineage; leave it alone
does not, names exactly one     -> that kind
does not, names two             -> refuse, naming both
```

The fourth line is the only place an edge could go silently wrong, so it is the only place this
raises. `registry, guessing` in the prototype is the same procedure with that line taking the first
match instead, and it is the only strategy in the whole matrix that produced a wrong graph in
silence — c8 binds to `parents.Owner` when the author meant `c8_other_owner.Owner`, and nothing says
so. That is risk §7 and risk §1 meeting, and one branch keeps them apart.

### What this leaves open

- **The candidate is extracted from the annotation string crudely** — good enough for `Owner`,
  `Owner | None` and `Optional[Owner]`. A real implementation should parse the annotation and
  collect its `Name` nodes. The design has no one-to-many lineage, so `list[Owner]` is out of scope
  by construction, but it should be *ignored* deliberately rather than by accident.
- **c8 refuses without offering a way out.** The design has no syntax for saying which `Owner` is
  meant. The practical answer is that the import must be a real one rather than a `TYPE_CHECKING`
  one when two kinds share a name — then it evaluates and the question never arises. Worth saying in
  the message.
- **PEP 649 (Python 3.14)** changes how annotations are stored. `typing.get_type_hints` survives;
  the field-by-field `eval` path would need `annotationlib`. `requires-python` is `>=3.11`, so this
  is a later problem, not a design one.
- `-> Self` is a non-issue. It resolves on 3.11 as long as `Self` is imported at run time.

---

## §1.2 Two of a kind in scope — decided

**Collection-time error, via an ATF-owned pass. It is a lookup, not a static analysis — on one
condition.**

All six resolutions `arrange.md#asking-for-one` promises pass as plain pytest functions, and both
scenario cases resolve to what the scenario arranged. All four failure cases stop the run with no
test body executed.

### The obstacle is not the one MIGRATION.md names

§1.2 predicted closure inspection. Closure inspection finds nothing. For a scenario, the whole of
`item.fixturenames` is:

```
['_pytest_bdd_example', '_session_faker', 'request']
```

A step's parameters never enter the fixture closure, because pytest-bdd asks for them with
`request.getfixturevalue` while the step runs. There is no closure to inspect and no
`pytest_generate_tests` pass that would help.

What *is* available at collection is the parsed scenario, on `item.function.__scenario__`, with
every step's keyword and sentence. So the arranged half — which instances a `Given` names — is free.
The missing half is which parameters those steps take.

### The condition: ATF owns the step registry

Keep the pattern and the function together when a step is registered, and "what does this sentence
ask for" becomes a lookup ATF performs on its own data: match the sentence, read the signature,
subtract the placeholders. ATF already registers every step it ships, every step a suite writes with
`atf.when` / `atf.then`, and everything a `@phrase` expands to, so this costs a dataclass and a list.

The whole pass is about 60 lines. It also catches "asks for a kind with no factory and nothing in
scope", which `arrange.md#factory` calls an error and `arrange.md#asking-for-one` calls a collection
error.

### The architecture that falls out

**The collection pass decides; the fixture obeys.** Resolution is worked out once per test, keyed by
`(nodeid, parameter)`, and the kind fixture reads the answer rather than working it out again. That
is the same table `arrange.md#asking-for-one` promises the editor — "each parameter shows what it
will resolve to for the scenario it sits in" — so the editor view is a read of it, not a second
implementation.

### Verified against the declaration layer, not beside it

`fixtures/resources.py` declares through `lineage/explicit.py` rather than keeping a copy, so the
two halves of Phase 0 are checked wired together. Two things only hold because of that:

- A kind fixture builds its factory's dependencies from **the kind's `depends_on`**, not from the
  factory's own signature. That is the only source left once annotations carry nothing.
- `Report`, whose shape has no field for an owner, resolves as a fixture and arrives with its owner.
  A test asserts that it has no `owner` attribute and one parent — the shape a typed field could not
  state, working end to end.

### What it costs in private API

Two things, and neither is one of the five private imports risk §4 names.

- `item.function.__scenario__` — undocumented, but it is how pytest-bdd's own `scenarios()` finds
  already-bound scenarios, so it is load-bearing upstream too.
- `stacklevel=2` when wrapping `@given` / `@when` / `@then`. pytest-bdd injects its step fixture into
  the **caller's** module namespace by walking the stack, so wrapping its decorator without saying
  so registers every step a suite writes into ATF's own module and no scenario finds any of them.
  The prototype hit this and every scenario failed with `StepDefinitionNotFoundError`. `stacklevel`
  is a documented parameter, which is what makes owning the registry cheap.

### Behaviour at the boundary

`pytest.UsageError` raised from `pytest_collection_modifyitems` reports **every** problem in one go,
runs no test body, and exits `4` — pytest's `USAGE_ERROR`. That is ATF's exit `2`, "the run never
started", with `suite_invalid` as the `--json` code.

```
ambiguous/test_ambiguous.py::test_two_owners_are_arranged_and_a_step_asks_for_the_owner
    'owner' is ambiguous: 2 of kind Owner are in scope — primary, secondary.
    Ask for the one you mean by name.
```

### What this leaves open

- **Phrases are not tested.** A phrase expands to more steps, so the pass composes only if expansion
  happens at collection. If it does, `_requested` walks the expanded list and nothing else changes.
  If expansion is deferred to run time, collection-time detection is lost for any scenario using a
  phrase — which makes phrase expansion a collection-time requirement, not a choice.
- **Scenario Outlines are not tested.** Each `Examples` row is its own item, so per-item decisions
  should hold, but the prototype does not show it.
- **Name collisions between a kind and an instance.** An instance called `owner` would shadow the
  `Owner` kind fixture. The prototype refuses at configure time; the specification does not say.
  Same question for two kinds whose snake_case names collide.

---

## Noted, not in scope

A typed field cannot express a dependency that carries no value — one resource needing several of
another to exist, with nothing linking them. `arrange.md#lineage` already admits two near misses;
this is a third. Neither the current code nor `docs-next` can express it, so it changes nothing
about Phase 0 and is recorded here only so it is not rediscovered as a surprise.

`lineage/cases/n4_collection.py` shows ATF can read `list[Player]` — origin `list`, argument
`Player`, a declared kind. Whatever the eventual answer is, detection is not the hard part.

## Consequences for the phases after this one

- Phase 1's module scan must be **two passes** — import every `resources:` module, then resolve
  every annotation. Resolving as each module lands reintroduces c2 and makes the registry
  incomplete for c3.
- Phase 1 owes an error message for a kind name declared twice. It is the only hard failure in the
  lineage path, and it is the one that protects risk §1.
- Phase 3's step registry is **not just a convenience** — §1.2's collection-time promise depends on
  it. It should be built before, or with, the Gherkin compiler rather than after.
- Phase 3 must expand phrases at collection.
- `atf edit` gets the parameter-resolution table for free, because the collection pass already
  builds it.
