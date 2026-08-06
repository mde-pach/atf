# One engine, two surfaces

A test in ATF is either a pytest function or a Gherkin scenario. The two cannot drift apart, and that
is a property of the construction rather than a promise about maintenance.

## A step does not do anything

Underneath both surfaces there is one mechanism: pytest fixtures. A resource is a pytest fixture.
Asking for one is pytest's own rule — the parameter name resolves, the annotation types.

```python
def test_show_lists_the_list(groceries: TodoList, shell):
    result = shell(f"todo show {groceries.owner.email}")
    assert "groceries" in result["output"]
```

The Gherkin surface does not have a second way of getting a `groceries`. It has a translation.

```gherkin
Scenario: show lists the owner's lists
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "groceries"
```

`Given the todo_list "groceries"` compiles into a request for the fixture named `groceries`, and then
it is finished. It does not open a database connection. It does not insert a row. Every question
about what happens next — is the list already there, does an owner come with it, how long it lives,
what happens to it at the end — is answered by the same fixture, in the same order, with the same
messages, as it is for the pytest function above.

## Why the alternative fails

The usual shape is two implementations kept in step. A step library provisions things its way;
fixtures or factories provision them theirs. They agree at the start, because one person wrote both
in one afternoon and checked.

They come apart on lifetime, and lifetime is the worst place for it. Lifetime rather than teardown,
because [`persistent`](../reference/arrange.md#scope) is the default and most resources are never
torn down at all. What a resource has is a lifetime — one test, one run, or longer than the process —
and two arrangement paths can disagree about which of the three a thing got.

Suppose a list and its owner are both `scope="function"`. The step-library path removes the list it
made and leaves the owner, because at the time it was written no test cared about a stray owner. The
fixture path removes both, in dependency order. Both paths still pass, and the suite has left a row
in the database.

The next run is where you find out. A test that never touched Gherkin asks for *any* owner, its
factory builds one, and now there are two — so a claim that the environment holds one owner fails. Or
a unique key collides and a creation that has worked for a year raises. The red line is in a
different test, in a different file, written by a different person, on a run that did nothing wrong.
Residue does not fail where it is made.

Two implementations can be kept in step. Teams do it. It costs a rule nobody can enforce
mechanically — *change both* — and it fails silently, late, and in the wrong place. ATF removes the
possibility rather than the likelihood: a step is a request, and a request has no lifetime of its own
to get wrong.

The escape hatch does not reopen it. [A step you write](../reference/act.md#a-step-you-write) takes
resources as parameters and acts on them:

```python
@when("I list the owner's lists")
def _(shell, owner: Owner):
    return shell(f"todo show {owner.email}")
```

`owner: Owner` is the same request again. Custom steps extend the vocabulary of the Act band. They do
not get their own way of arranging things.

## Gherkin is optional

Because the engine is fixtures and the scenario is a translation, a team can take the resource model
and never write a `Scenario:` line. `atf status`, `atf make`, `atf impact` and `atf unused` read the
resource graph, and the graph does not know whether the tests above it are prose or Python.

The reverse holds too, because it is still pytest. `-k` and `-x` select and stop. `--pdb` drops you
into the failure. Coverage instruments the run. ATF did not have to reimplement any of that, which
also means it cannot fall behind it.

Making Gherkin the only surface, as Cucumber does, would have bought a single path with no
translation — a simpler engine. It was declined because Gherkin is not free. A team pays for it in a
shared vocabulary that has to be maintained, and in one layer of indirection between the sentence and
the thing. That is a good trade when the scenarios are read by people who do not write Python, and a
poor one when they are not read by anyone.

## What it costs

The engine is pytest, so ATF inherits pytest's constraints rather than choosing its own. `function`
and `session` mean what pytest means by them, down to the ordering rules; only `persistent` is ATF's
own word. When something goes wrong before a test starts — a collection error, say — the message
comes from a system ATF does not control.

A translating surface can only say what the thing underneath already does. A Gherkin step cannot mean
something the resource model has no word for, which is why the escape hatch exists — and what you
write in Python there, ATF cannot read.

Two surfaces are two places to look. Pick per test and mix them in a suite; because a step compiles
into a request for a fixture, the two are the same run. But somebody looking for a behaviour still
looks in two directories, and a team that never decides which kind of test goes where ends up with
the answer to "where is that test" always being "the other one". Decide it once and write it down.

## Where to go next

- **[Declared, not executed](declared-not-executed.md)** — the bet underneath the engine, and why the
  arrangement path is data rather than code in the first place.
- **[Every failure names your sentence](every-failure-names-your-sentence.md)** — the other reason
  scenarios and functions must share a path: they have to fail the same way, too.
- **[Write a scenario](../how-to/write-a-scenario.md)** — the practical form of this page, for the
  tests where a sentence earns its place over a function.
