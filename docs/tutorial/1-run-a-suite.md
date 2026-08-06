# Run a suite

Someone has handed you a suite that tests the todo app. Install ATF, run it, read the red result,
fix the app, and get a green one.

## What you were handed

```text
todo-suite/
  atf.yaml
  todo.py
  resources.py
  adapters/
    sqlite.py
  specs/
    showing-a-list.feature
```

`todo.py` is the app, `specs/` holds the tests, and `atf.yaml` says where everything is and what ATF
is allowed to touch. `resources.py` declares the suite's **resources**: the things a test can ask
for, each one a class with a name. Chapter 3 writes one; today you only use them.

`adapters/sqlite.py` is this suite's own file, not part of ATF: it is what taught ATF to keep
resources in a SQLite database, and
[Teach ATF a new system](../how-to/teach-atf-a-new-system.md) is where you eventually read it. Use it
today without opening it.

## The app

The whole of `todo.py` — twenty-five lines, a SQLite file, two commands. It is yours to break.

```python
import sqlite3, sys

db = sqlite3.connect("todo.db")
db.executescript("""
  CREATE TABLE IF NOT EXISTS owners (id INTEGER PRIMARY KEY, email TEXT UNIQUE);
  CREATE TABLE IF NOT EXISTS lists  (id INTEGER PRIMARY KEY, slug TEXT UNIQUE,
                                     owner_id INTEGER REFERENCES owners(id));
""")

def add(email, slug):
    owner = db.execute("SELECT id FROM owners WHERE email = ?", (email,)).fetchone()
    if owner is None:
        sys.exit(f"no owner {email}")
    db.execute("INSERT INTO lists (slug, owner_id) VALUES (?, ?)", (slug, owner[0]))
    db.commit()

def show(email):
    rows = db.execute("""SELECT lists.slug FROM lists
                         JOIN owners ON owners.id = lists.owner_id
                         WHERE lists.slug = ?""", (email,)).fetchall()
    print("\n".join(r[0] for r in rows) or "no lists")

{"add": add, "show": show}[sys.argv[1]](*sys.argv[2:])
```

There is a bug in it. Find it by running the suite rather than by reading.

## The test

One scenario, in `specs/showing-a-list.feature`:

```gherkin
Feature: showing a list

  Scenario: a list shows under its owner
    Given the todo_list "groceries"
    When I run "todo show primary@example.com"
    Then the result field "output" contains "groceries"
    And the result field "exit_code" is "0"
```

Four sentences, in the order every test goes: arrange, act, assert. The two `Then` lines are
**claims** — statements that are either true or not when they are checked.

## Where `local` points

`atf.yaml`:

```yaml
resources: [./resources.py]
specs: ./specs
extensions: [./adapters/sqlite.py]
default_env: local

environments:
  local:
    mutable: true
    sqlite:  { path: ./todo.db }
    command: { prefix: "python todo.py" }
```

`extensions:` is the line that loads the adapter. `local` is an **environment**: a place the suite's
things can exist, and the place a run acts on.
Here it is the SQLite file next to the app and the command that starts it, which is why
`When I run "todo show ..."` runs `python todo.py show ...`.

`mutable: true` says this environment **may be changed** — ATF may create, update and delete what a
test asks for. `mutable` is false unless written. Where nobody wrote it, ATF only looks and reports,
and a test that would have to change something fails there, naming the resource it could not
provision.

## Install and run

```console
$ pip install atf
$ atf run
```

```text
specs/showing-a-list.feature

  Scenario: a list shows under its owner
    passed   Given the todo_list "groceries"
    passed   When I run "todo show primary@example.com"
    failed   Then the result field "output" contains "groceries"
    skipped  And the result field "exit_code" is "0"

  specs/showing-a-list.feature:6
    Then the result field "output" contains "groceries"

    output does not contain "groceries"
      output:     no lists
      exit_code:  0

1 scenario, 1 failing
```

Red, and `atf run` exited `1`. There are three exit codes and no more: `0` passed, `1` a test
failed, `2` the run never started. The reason travels in the message, not the number.

## Read the failure

That is a **run**: one execution of the suite. Every step in it got an **outcome**, and there are
exactly three. `passed` means it was done, or it was true. `failed` means it was true and is not.
`skipped` means it was never reached.

The block says where — `showing-a-list.feature:6`, and the sentence on that line quoted back as you
wrote it. It says how far it got: the two steps above passed, so `groceries` was made and the
command ran, and the step below is `skipped`, because once the output claim is false there is
nothing to learn from the exit code. Skipped means not reached, never "we do not know". And it says
what it saw: `output: no lists`, for an owner who has one.

## Fix it

The claim is right and the app is wrong. `show` looks up lists by slug and passes it an email:

```python
                         WHERE lists.slug = ?""", (email,)).fetchall()
```

Change that line in `todo.py` to join on the owner instead:

```python
                         WHERE owners.email = ?""", (email,)).fetchall()
```

## Run it again

ATF remembers the last run, so you can re-run only what did not pass:

```console
$ atf run --failed
```

```text
specs/showing-a-list.feature

  Scenario: a list shows under its owner
    passed   Given the todo_list "groceries"
    ...
    passed   Then the result field "output" contains "groceries"
    passed   And the result field "exit_code" is "0"

1 scenario, 1 passing
```

Green, and `atf run` now exits `0`. The scenario has two runs behind it: that sequence is its
**history**, and the fold of it into one word is its **verdict** — `passing`, `failing`, `skipped`,
or `never run`. Outcomes belong to a run, a verdict to a scenario.

## What the environment holds

```console
$ atf status local
```

```text
local — mutable

  present   owner      "primary"        primary@example.com
  present   todo_list  "groceries"      slug=groceries, owner="primary"
```

Both `present`. Before your first run both were `absent`: the SQLite file was empty. The run made
them, because naming a resource in a scenario is what makes ATF create it, and they are still there
— a run does not sweep the environment when it finishes.

`present`, `absent` and `unreachable` are the only three words for what an environment holds.
`absent` is not a problem to solve; it is a resource ATF will make next time a test asks. One that
cannot be made fails the test that needed it, at the sentence that needed it.

The scenario named `groceries` and never mentioned `primary`, yet `primary` is there and `groceries`
records that it belongs to it. A todo_list has an owner, so asking for the list asked for the owner.
That relationship is **lineage**, and nobody wrote it in the scenario.

## What depends on what

ATF holds lineage as a graph, and you can ask it questions:

```console
$ atf impact primary
```

```text
owner "primary"
  todo_list "groceries"
    specs/showing-a-list.feature:3  a list shows under its owner
```

Read it downwards: if `primary` breaks, `groceries` breaks, and the scenario on line 3 goes with it.
Ask about the list instead — `atf impact groceries` — and you get the scenario alone.

## Where to go next

- [Write a test](2-write-a-test.md) — the next step: your own test, in both surfaces.
- [The record](../reference/the-record.md) — runs, outcomes, verdicts and history in full, including
  what `atf run` writes for CI.
- [Work out why it is red](../how-to/work-out-why-it-is-red.md) — for when the failure is less
  obliging than this one.
