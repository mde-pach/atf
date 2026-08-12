# Declared, not executed

Every test has preconditions. In most frameworks they are code that runs before the test. In ATF they
are typed data that exists before anything runs. That is the bet, including the parts where it loses.

## The bet

```python
@todo.list()
class TodoList:
    owner: Owner = needs()
    slug: str

groceries = TodoList(owner=primary, slug="groceries")
```

Constructing `groceries` declares it. It does not touch the database or open a connection. Importing
this module is safe on a laptop with no environment at all.

The dependency on `Owner` is a field, and `needs()` is at the field that holds it. Nobody writes it
twice, and nothing runs to make it true. It is dbt's `ref()` with one thing added that dbt does not
need: a strategy. dbt models already exist; ATF's central act is building the thing that is not
there, so its resolution has to carry *how*, not only *what*.

## What that buys

The framework holds a graph — what depends on what, and which tests need which things:

```sh
atf explain groceries        what would go red if this broke
atf run --select +groceries what is worth running after this change
atf explain                 what nothing exercises
atf plan                    is the suite well formed
atf plan staging            what is present, absent or unreachable, right now
```

None of those run a test. `atf explain` is the one to sit with: given a resource, it names the tests
that would fail if that resource became wrong. Answering it requires the closure of dependencies over
things in an environment, not over functions in a file. Ordering comes from the same closure — you
never declare that owners are created before lists, because the order follows the field.

## The alternative, fairly

The alternative is the one nearly everyone uses, and it works: preconditions as functions. A pytest
fixture, a factory_boy factory, a `setUp` method. Functions are more capable than declarations in
every respect but one: the only way to learn what a function does is to run it.

Pytest knows which tests request which fixtures, and it resolves them by parameter name — exactly the
mechanism ATF borrows. `--fixtures-per-test` will print that graph today. What it cannot know is what
a fixture *makes*: that `groceries_fixture` inserts a row in `lists` keyed by slug, or that the owner
it references will still be there tomorrow. The questions it answers are questions about your test
files. `atf explain` is a question about staging.

factory_boy is the closest ancestor, and [`needs()`](../model.md) is `SubFactory`'s idea with the
factory removed. factory_boy makes you write a `Factory` class *alongside* the model, and the two
drift — a field added to one is missing from the other, and nothing says so. Here the declaration
and the factory are the same object, so there is nothing to keep in step. And because the dependency
is a field rather than an attribute of a separate factory, it exists whether or not anything is
built, which is why `atf explain` can report on a thing no test has asked for.

## What it costs

What makes the graph readable is what a field cannot do: branch, loop, retry, poll until ready, or
decide between two shapes based on the day of the week. So ATF needs an escape hatch, and it is
[a step you write](../reference/sentences.md) — ordinary Python, taking resources as
parameters. Plain pytest fixtures also keep working next to resources.

The escape hatch is opaque to the graph, deliberately and permanently. What you write in Python, ATF
cannot read, so every use is a piece of your suite that `atf explain` cannot see. The charge
is per use: a suite that reaches for custom steps by default ends up with a graph that is technically
correct and practically incomplete, which is worse than no graph, because you will trust it.

There is a second cost. A thing is limited to what a system can do: find, create, update, delete,
and optionally browse. Something that cannot be recognised is not a thing — it is a computation with
a side effect, and it belongs in a step.

## What else was on the table

**A separate declaration file.** Django's fixtures, Rails' `fixtures.yml`, YAML seeded into a
database. Declined because data outside the language has no types, no imports, no editor, and no
refactoring: names drift between the YAML and the code that uses them, and nothing notices. ATF uses
Python classes so that the shape is checked by the tools a team already runs.

**A DSL.** A small declarative language of ATF's own would have been more precise than Python
annotations and less capable than Python. Declined on the concept budget: Gherkin is already one
borrowed language for a reader to learn, and a second invented one is more than the design can pay
for. See [the concept budget](the-concept-budget.md).

**Declaring everything, with no escape hatch.** Purity here would mean a suite hits a wall and the
answer is "wait for the next release". Three escape hatches exist for that reason, and the fact that
there are exactly three is itself a decision.

## Where to go next

- **[Why there is no state file](why-there-is-no-state-file.md)** — the declarations are static and
  the environment is re-read every run. That is the most common misunderstanding about ATF.
- **[The concept budget](the-concept-budget.md)** — what declaring what a test needs is allowed to
  cost a reader.
- **[Start](../index.md)** — the bet in its smallest working form.
