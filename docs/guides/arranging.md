# Arranging what a test needs

*A test needs a row, a file, a running server — and it is not there.*

Say what has to exist, as a class with one framework word in it and one variable per thing:

```python
from atf.resources.sql import Row


class Task(Row, at="tasks"):
    todo_list: TodoList = needs()
    slug: Row.Key[str]
    done: bool


laundry = Task(todo_list=groceries, slug="laundry", done=False)
```

The class is the **kind**, `laundry` is the **thing**, and the annotations are its shape. Building
one touches nothing — no connection is opened and no row is written — so this file can be read on a
laptop with nothing running.

A test asks for it by name — a scenario in a sentence, a Python test in a parameter:

```gherkin
    Given the task "laundry"
```

```python
def test_lineage_comes_along(groceries: TodoList):
    """Asking for the list made its owner first, because the field says `needs()`."""
    assert groceries.owner.email == "primary@example.com"
```

A parameter named after a declared thing gets that thing; one named after a kind gets whichever the
test arranged, and resolves a fresh one when it arranged none. Both go through the same step: ask the environment whether it is there, make it when it is not,
bring it back to what the declaration says when it has drifted, and leave it alone when it already
matches. A declaration is partial — the fields you named must hold, and a column nobody declared
survives untouched.

## One thing needs another

`needs()` goes at the field and answers one question: how is this filled when nobody gave a value?

```python
from atf.resources.rest import Record


class TodoList(Record, at="/lists"):
    owner: Owner = needs()
    slug: Record.Key[str]
```

Bare, it resolves whatever the annotation names. `Owner` is a declared kind, so this is an edge:
asking for a list makes its owner first, in an order nobody wrote down.

With an argument it names something that produces a value:

```python
def an_email() -> str:
    """Whatever varies. ATF generates no values; this is the suite's own provider."""
    from itertools import count

    an_email.n = getattr(an_email, "n", count(1))
    return f"generated-{next(an_email.n)}@example.com"


class Owner(Record, at="/owners"):
    email: Record.Key[str] = needs(an_email)
```

ATF calls what you give it and produces nothing itself, so a generator you already use plugs in
where `an_email` is. A resolver may take declared things of its own, which is how a value depends on
lineage:

```python
def a_line(notebook: Notebook) -> str:
    """A resolver that itself takes a thing — the whole power of the pattern, in one function."""
    return f"written in {notebook.path}\n"
```

## Bending one for a scenario

```gherkin
  Scenario: giving the resolver an argument bends one declared thing
    Given the todo_list "groceries" with slug "weekly"
    Then the todo_list "groceries" slug is "weekly"
```

`with` changes one field for the length of that scenario, `and with …` names one more, and
`and without …` takes one away. The declared thing is left where it was; what the scenario gets is a
copy that goes when it does.

## Asking what is there

```console
$ atf explain groceries
  groceries · a todo_list · http.record · known by slug 'groceries'
  declared in atf/things.py

  needs      primary
  needed by  7 scenarios, 1 things
  lives      the test — some scenario changes it
  standing   absent in local
```

`atf explain` takes a thing, a kind, a system, a scenario, a phrase or a file. With no argument it
says the shape of the suite and where to point next.
