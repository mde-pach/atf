# Write a test

Write one behaviour twice: as a plain pytest function, then as a Gherkin scenario. You are still in
the suite from [chapter 1](1-run-a-suite.md), with `todo.py` fixed and green. The behaviour:
`todo show` prints the lists belonging to the email you give it, and nothing belonging to anyone
else — an email with no lists gets `no lists`.

## As a pytest function

Create `specs/test_ownership.py`:

```python
from resources import TodoList


def test_a_list_belongs_to_one_owner(groceries: TodoList, shell):
    first = shell(f"todo show {groceries.owner.email}")
    assert "groceries" in first["output"]

    result = shell("todo show nobody@example.com")
    assert "no lists" in result["output"]
```

Run it:

```console
$ atf run
```

```text
specs/showing-a-list.feature
  ...

specs/test_ownership.py

    passed   a list belongs to one owner

2 tests, 2 passing
```

Three things in that function need a second look.

**The parameter is the arrange.** There is no set-up code. `groceries` is pytest's own rule
unchanged: **the name resolves and the annotation types**. The name picks out that particular list,
the resource `resources.py` already declared; the annotation says what it is. By the time the body
runs it exists in `local` — made if it was absent, left alone if it was present.
`groceries.owner.email` is chapter 1's lineage in Python: you never asked for an owner, and you can
walk to one.

**`shell` runs something**, through the prefix `atf.yaml` gave `local`, so `shell("todo show ...")`
runs `python todo.py show ...` exactly as `When I run` did. What comes back is a record of fields —
`output` and `exit_code` for this app — read the way you read any dict.

**The claims are `assert`.** `assert "groceries" in first["output"]` is a claim: a statement that is
true or not at the moment it is checked.

## As a scenario

The same behaviour in Gherkin. Create `specs/ownership.feature`:

```gherkin
Feature: ownership

  Scenario: a list belongs to one owner
    Given the todo_list "groceries"
    When I run "todo show primary@example.com" as "first"
    And I run "todo show nobody@example.com"
    Then the first field "output" contains "groceries"
    And the result field "output" contains "no lists"
```

Line for line against the Python: the `Given` is the `groceries: TodoList` parameter, each `When I
run` is a call to `shell`, and each `Then` is an `assert`.

A test that runs one thing does not name it: the result goes into a slot called `result`, which is
what `the result field "output"` reads. This test runs two, and the second would land in the same
slot. `as "first"` gives the first run a slot of its own, and that name then stands where `result`
stood — `the first field "output"`. It is the assignment you already made by writing
`first = shell(...)`.

## They were the same run

```console
$ atf run
```

```text
specs/ownership.feature

  Scenario: a list belongs to one owner
    passed   Given the todo_list "groceries"
    passed   When I run "todo show primary@example.com" as "first"
    passed   And I run "todo show nobody@example.com"
    passed   Then the first field "output" contains "groceries"
    passed   And the result field "output" contains "no lists"

specs/showing-a-list.feature
  ...

specs/test_ownership.py

    passed   a list belongs to one owner

3 tests, 3 passing
```

One run, one report, one exit code. The reason is one line long:

> `Given the todo_list "groceries"` compiles to asking for the fixture `groceries: TodoList`.

The step runs no set-up code of its own. It asks for the same thing your parameter asked for and
gets the same answer: `groceries` was made once, before whichever of the three tests reached it
first, and the other two found it present. Neither surface is the underlying one and neither
compiles to the other, so pick per test and mix them in a suite.
[One engine, two surfaces](../explanation/one-engine-two-surfaces.md) has why the two cannot drift
apart.

## A kind, not a value

Some fields have no value a test should pin down. Every list gets a row id, and no test should care
what it is — only that it is a number:

```gherkin
Then the todo_list "groceries" field "id" is #int
```

**Quotes mean a literal. `#` means a kind.** `is "int"` compares the field with the three characters
`int` and fails; `is #int` asks whether the field is an integer at all. The kinds that ship are
`#int`, `#str`, `#bool`, `#uuid`, `#datetime` and `#date`, plus `#absent` and `#present`. Reach for
one where the value is the system's to choose — an id, a timestamp, a token — and claim a literal
everywhere else, because a kind that is too loose passes on data you would not accept.

## Teaching ATF a sentence

`the result field "output" contains "no lists"` is precise and clumsy. Say it in your own words
instead. Create `specs/phrases.feature`:

```gherkin
Feature: phrases

  @phrase
  Scenario: the output contains "{words}"
    Then the result field "output" contains "{words}"
```

That is a **phrase**: a scenario tagged `@phrase`, which makes it vocabulary rather than a test. ATF
never collects it as one. Where a scenario says `the output contains "no lists"`, ATF puts the
phrase's body in its place with `{words}` bound to `no lists`.

A phrase can hold any number of steps, which is how you claim more than one field. There is no
sentence that asserts a whole record at once: a claim over every field fails whenever anything about
the record moves, including the parts the test was never about. Name the fields you care about, one
sentence each, and when the same set turns up a third time give it a name:

```gherkin
@phrase
Scenario: the list "{slug}" is stored the way a new list should be
  Then the todo_list "{slug}" field "slug" is "{slug}"
  And the todo_list "{slug}" field "id" is #int
```

Add a field to the phrase and every scenario using it checks that too. Now say it in
`specs/ownership.feature` — the last line becomes:

```gherkin
    And the output contains "no lists"
```

```console
$ atf run --failed
```

Nothing to run: nothing failed. Run the lot instead:

```console
$ atf run
```

```text
specs/ownership.feature

  Scenario: a list belongs to one owner
    passed   Given the todo_list "groceries"
    ...
    passed   Then the first field "output" contains "groceries"
    passed   And the output contains "no lists"

specs/showing-a-list.feature
  ...

specs/test_ownership.py
  ...

3 tests, 3 passing
```

The report shows the sentence you wrote, not the one it stands for — and so does the failure, if you
break the app again. Note what the phrase did not get: the named slot. `the output contains` reads
`result`, the default one, so it fits the last line and not the `"first"` line above it. A phrase is
exactly as general as the steps you put in it.

## Where to go next

- [Declare what it needs](3-declare-what-it-needs.md) — the next step: writing the declarations the
  last two chapters have been living off.
- [Act](../reference/act.md) — every form of `When`, what a result carries, and naming results in
  full.
- [Teach ATF a sentence](../how-to/teach-atf-a-sentence.md) — phrases that arrange and phrases that
  claim, and how they nest.
