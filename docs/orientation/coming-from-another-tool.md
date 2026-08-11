# Coming from another tool

Nearly everything in ATF is something you have used elsewhere, moved one step: a fixture declared as
data, a `SubFactory` with types, a `ref()` that is a field, an accessible-name locator said in
Gherkin. Read the section for the tool you know best. Each says what the ATF equivalent is, where it
differs, and where ATF is the narrower of the two.

## pytest fixtures

**A resource is a fixture.** Not "like" one — asking for a resource is pytest's own rule, and there
is no injection scheme underneath.

```python
def test_a(primary: Owner):        # that owner
def test_b(owner: Owner):          # any owner — the factory builds one
def test_c(groceries: TodoList):   # that list, and primary comes with it
```

The name resolves and the annotation types. A resource takes the name of its variable, the same way
a fixture takes the name of its function; `resources.py` is read by importing it, the way
`conftest.py` is. A fixture body is code, so learning that `groceries` needs an owner means
executing it. A resource's dependency is declared data, so `atf status`, `atf impact groceries` and
`atf unused` answer without running a test.

**Where it differs**

- **Nothing runs at construction.** `TodoList(owner=primary, slug="groceries")` declares; it touches
  no database. Provisioning happens when a test asks.
- **The default scope is `persistent`, which pytest has no word for.** It outlives the process and
  ATF never tears it down. `scope="session"` lasts one run; `scope="function"` is pytest's habit.
- **Ambiguity is an error.** Two owners in scope and a test asking for `owner: Owner` fails, asking
  you to say which. pytest resolves by name alone and would never complain.
- **A resource cannot do everything a fixture can.** No `yield`, no arbitrary computation, no
  `autouse`, no parametrisation — it can be found, created, updated and deleted, and that is all.
  Setup that is genuinely a computation stays a fixture, beside resources in the same signature.

## factory_boy

**A resource's `factory` classmethod is factory_boy's factory, with the dependency declared once on
the resource rather than as a `SubFactory` attribute.**

```python
@todo.list(depends_on=[Owner])
class TodoList:
    slug: str

    @classmethod
    def factory(cls, owner: Owner) -> Self:
        return cls(owner=owner, slug=faker.slug())
```

`depends_on=[Owner]` is the `SubFactory`. A dependency the caller does not supply is built by that
resource's own factory, recursively, and the factory is handed it by the name of its kind. Faker is
yours, and so is `@sql.row`: it comes from an adapter in the suite, not from ATF.

**Where it differs**

- **The relationship is declared once, on the class.** In factory_boy the model has a foreign key
  and the factory has a `SubFactory` — the same fact twice. Here the field is both.
- **Types resolve it, so an editor can follow it.** `SubFactory(OwnerFactory)` is a string away from
  a runtime error; `owner: Owner` is not.
- **One classmethod, and no declaration language.** No `Sequence`, no `LazyAttribute`, no traits, no
  `post_generation` hooks, no build-versus-create strategies. If you use those, you will write plain
  Python inside `factory` instead.
- **A one-test difference is a sentence per field, not a keyword override.** Where factory_boy
  writes `TodoListFactory(owner=None)`, a scenario writes `Given the todo_list "groceries" but
  "owner" is "null"`. It edits a declared resource rather than building a fresh one.

## Cucumber / Gherkin

**A phrase replaces glue code.** The sentences that touch resources, results and interfaces are
built in — they come from the systems in play. What you add is vocabulary, written in Gherkin:

```gherkin
@phrase
Scenario: a customer who has already paid
  Given the owner "primary"
  And the todo_list "groceries"
  When I complete the task "laundry"
```

`Given a customer who has already paid` is now a sentence. It is a tagged scenario, never collected
as a test, and it spans all three verbs: one that arranges is said as a `Given`, one that claims as
a `Then`. Phrases nest.

**Where it differs**

- **No step definitions for the common cases.** Arranging, running, clicking and asserting are
  already sentences. You write glue for what your domain has and ATF does not.
- **You can still write Python.** [A step you write](../reference/act.md#a-step-you-write) is
  `@when` and `@then`, with a public `claims` library, so a step you wrote fails as well as a
  built-in does.
- **The built-in vocabulary is a small fixed set.** Cucumber's grammar is whatever you define. ATF's
  is whatever the systems, your phrases and your registered claims allow — narrower, deliberately.
- **A scenario is sentences, and nothing else.** No data tables, no `"""` DocStrings, no YAML or
  JSON in a step. The one table left is `Examples` under a `Scenario Outline`. Anything structured
  is several sentences, and when several sentences repeat they become one phrase.
- **Phrases live in one flat namespace.** Anywhere under the specs directory, shippable between
  suites as an ordinary Python package — so two phrases cannot share a sentence, project-wide.
- **The same test can be a pytest function instead.** A scenario and a pytest test compile to the
  same thing, so a team that finds Gherkin a tax can decline it without leaving the framework.

## Terraform

**Same model, and ATF converges.** You declare the state you want; ATF finds what is there, compares
it, creates what is missing and updates what differs. `atf status <env>` is the plan, `atf make
<env>` is the apply, and `mutable: false` on an environment is a plan-only lock — false unless
stated. ATF computes the diff itself; the adapter is only handed the changes to write.

**It converges without a state file.** Nothing records what ATF made last time. Recognition re-reads
reality every run — `unique_by="email"` means "look for an owner with this email, right now" — and
reality is one of three words: `present`, `absent`, `unreachable`.

**Where it differs**

- **The declaration is the only memory.** Terraform reconciles against what it last recorded, so a
  wrong record produces a wrong plan. ATF reconciles against what is there, so two people can run
  against one environment without a lock.
- **A declaration is partial, not total.** The fields you named must hold; the fields you did not
  name are left alone. Terraform owns the whole object and reverts what it does not know about.
- **The recognising field is the address.** In Terraform the address is `aws_instance.web` and the
  state file maps it to an ID. Here the address is the value: the email, the slug, the nickname. A
  thing with no stable field is not modelled as a resource.
- **No destroy, and no orphans.** Deleting a declaration removes it from the graph, not the row from
  the database, because ATF has no record that it put it there. Cleanup of per-test things is
  [scope](../reference/arrange.md#scope), not a lifecycle.
- **Much smaller in every other direction.** No providers ecosystem, no modules, no outputs, no
  workspaces. Seven systems ship in the box over five drivers, and `@adapter` is how a team adds
  the eighth.

[Why there is no state file](../explanation/why-there-is-no-state-file.md) has the argument, and
what trusting the environment over a record costs.

## dbt

**`ref()` is `depends_on`.**

```python
class TodoList:
    owner: Owner          # this is ref('owner')
```

The graph is a by-product of writing normally: it is the fields, so it cannot be out of date.
Selection works the way you expect:

```sh
atf run --select +groceries   whatever touches this
atf impact groceries          what breaks if this does
atf unused                    what nothing asks for
```

`atf docs` is `dbt docs`: the specs as markdown, carrying the last verdict.

**Where it differs**

- **ATF does not own its nodes.** dbt builds the table it describes. ATF describes something in a
  system it did not build, so it must go and look — recognition instead of materialisation.
- **A node is a row, not a model.** `TodoList` is a class, but `groceries` is one list. The graph
  has instances in it as well as types.
- **The selector language is a fraction of dbt's.** `+name` and `--tag`, plus `--failed`. No graph
  operators, no `state:modified`, no unions and intersections.
- **No tests-on-models split.** In dbt the model and its tests are separate objects. Here the
  resource *is* the precondition of the tests, and the claims are in the specs.

## Playwright

**The interface band uses Playwright's model of the page.** Elements are addressed by role and
accessible name, said in Gherkin:

```gherkin
When I type "4242 4242" into the textbox "Card number"
When I click the button "Pay now"
Then the button "Pay now" is disabled
Then the words "Payment received" are showing
```

If you already write `getByRole('button', { name: 'Pay now' })`, there is nothing to learn but the
sentence.

**Where it differs**

- **A page is one system among several.** `@browser.page` sits beside `@filesystem.file`, `@filesystem.directory`, `@shell.process`
  and whatever your database adapter is called, so a scenario can arrange a row and click a button
  in the same breath. Playwright is a browser library; ATF is not.
- **A browser is observed, not made.** `@browser.page(when_absent="observe")` — it is something to look
  at, and ATF will not create it.
- **No ARIA snapshot.** There is no whole-screen claim, because a scenario is sentences and an
  accessible tree is not one. You lose the catch-everything property of a snapshot and gain a
  failure that names a sentence.
- **No selector escape hatch in a scenario.** What is not exposed as a role with an accessible name
  is not addressable from Gherkin. That is a real constraint. It pushes you towards fixing the
  accessibility, and where you cannot, you write a Python step.
- **Narrower than the library, on purpose.** Tracing, network interception, multiple contexts and
  video are Playwright's, and a Python step is where you reach them.

## Django models

**A resource class looks like a Django model, and it is not one.** It is *the test's view of a
thing*, not the application's definition of it.

```python
@todo.owner()
class Owner:
    email: str
```

An owner in your application has a dozen columns. This says the test cares about one, and that one
is how it recognises an owner. The class is the shape; the decorator is the system.

**Where it differs**

- **It does not import your models, and that is deliberate.** The test's view stays still while the
  application's model churns, and it works against a staging environment where your code is not
  loaded. The cost is duplication and drift: expect to keep the two in step by hand.
- **Partial by design.** Only the fields the test recognises and sets. A resource is not a mapping
  of a table.
- **No manager, no queryset, no `save()`, no migrations.** The table must already exist — ATF
  arranges rows, not schema — and `unique_by` is how ATF looks a thing up, not a constraint it
  creates.
- **It does not have to be a database at all.** The same class shape backs `@filesystem.file`, `@browser.page` and
  `@shell.process`. A file on disk and a running process are resources with fields, and the graph does not
  know the difference.

## Where to go next

- **[The model](the-model.md)** — the whole map, once the anchors above have given you somewhere to
  hang it.
- **[What we borrowed](../explanation/what-we-borrowed.md)** — the same debts stated as debts, with
  what was left behind and why.
- **[Run a suite](../tutorial/1-run-a-suite.md)** — the fastest way to find out whether any of this
  is true.
