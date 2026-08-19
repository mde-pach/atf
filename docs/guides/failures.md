# When it goes red

*A claim did not hold, and the interesting question is why the thing under it was in that state.*

```console
$ atf run
atf/lists.feature:9  Scenario: a list shows under its owner
  Then the answer names "vegetables"

  the answer: it named groceries

  groceries            present, the test
    └ primary              present, the run
      └ serving              present, the run

  → atf enter "a list shows under its owner"

1 failed, 10 passed, 0 skipped   (r-30dd5e)
```

Four things, in the order you need them. The sentence that stopped. What came back, in full. The
chain that put the subject of the claim there, each link with what the environment said about it at
the moment the claim failed and how long it lives. And the command that takes you back inside.

## Getting inside

```console
$ atf enter
  a list shows under its owner · arranged, replayed to the failing line

    ✓ Given the todo_list "groceries"
    ✓ When I ask for the lists of "primary"
    ✗ Then the answer names "vegetables"
      the answer: it named groceries
>>> primary
      a owner · present · lives the run
      email 'primary@example.com', id 2
>>> I ask for the lists of "primary"
      items [{'id': 1, 'slug': 'groceries', 'owner_id': 2}]
>>> done
```

Bare `atf enter` takes the last thing that failed. Name a scenario to enter one that passed.

At the prompt, five things work: any sentence the suite knows runs for real, including one this
scenario never had; the name of a declared thing reads it from the environment now; `next` runs the
next sentence; `keep as "…"` writes what you typed out as a scenario; `?` lists all of it.

Entering arranges for real. It writes what a run writes, and takes it away when you type `done`.

## What it did before

A run is recorded, so a scenario carries its own history:

```console
$ atf explain 'a list shows under its owner'
  a list shows under its owner
  atf/lists.feature:9

  passed since 4 runs ago · passed 23 times before that
  turned between b537d09 and b537d09

  it needs   serving → primary → groceries → http.record → shell.process
```

`--report ctrf:out.json` writes a run where a pipeline will collect it, and `atf run --import
out.json` brings a run recorded on another machine into this history.

## Running only what broke

```console
$ atf run --failed --dry-run
0 tests selected
```

`--failed` reselects what failed here last time, and nothing once it passes.
