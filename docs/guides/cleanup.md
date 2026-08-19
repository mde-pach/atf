# Leaving nothing behind

*Your test passed, the next one found its row, and now you are reading a failure in a test that
never touched it.*

Nobody types how long a thing lives. Each one earns the weakest span that is still safe, read off
what the suite says about it:

```console
$ atf plan --lives
  how long each thing lives
  anyone     the run   it is resolved rather than declared
  primary    the run   it cannot outlive serving
  serving    the run   written on the declaration — ATF cannot see this one
  groceries  the test  some scenario changes it
  laundry    the test  some scenario changes it
```

Three rules, and the command says which one applied:

**Some scenario changes it** → it lives for the test. Read off the sentences: a step that declares
it writes, naming that thing. `groceries` is changed by a scenario, so every test that asks for one
gets its own, and it goes at the end of that test.

**It is resolved rather than declared** → it lives for the run. A field left to `needs()` means
every asker could get a different one, so it cannot be shared past the run that made it.

**It is declared with fixed values** → it stays. Nothing changes it and nothing about it varies, so
making it again next run would be making the same thing twice.

Nothing outlives what it depends on. A span is floored by the shortest one in the whole lineage, and
when the floor is what decided it, the reason names the thing that set it — `primary` above.

## When ATF cannot see it

`lives=` on the declaration overrides the reading, for effects that happen outside the graph:

```python
from atf.resources.process import Process


class Api(Process, lives="the run"):
    """The API under test, started for the run and stopped when it ends."""

    command: Process.Key[str] = "python api.py"
    port: int = 8801
```

Nothing in the suite says a server should stop when the run does, so the declaration says it. That
is the only reason to write `lives=`, and `atf plan --lives` marks every one of them.

## The order things go in

Teardown is reverse lineage: a child goes before the parent it hangs off. A task row is deleted,
then the list it points at, then the process serving both. That order is the whole of why a
directory made for one test can be removed at the end of it — what was inside it went first.

## Something changed it behind your back

Nothing is remembered between runs. A run and a plan both ask the environment what it holds, every
time, so there is no file to go stale.

```console
$ echo tampered > tmp/scratch/draft.txt
$ atf plan local
  local
    1 present · 1 absent · 1 drifted
      absent      waiter                   will be made
      drifted     today                    text
```

`drifted` names the fields that differ from the declaration. `--apply` writes those back and nothing
else:

```console
$ atf plan local today --apply
      drifted     today                    text

  applied
    scratch                  unchanged
    today                    updated
```

`--apply` writes, so name a thing to keep it to that one and its lineage.

Changing a value that *recognises* a thing — a path, a slug, whatever the table holds unique — makes
a different thing. It reads as `absent`, and the declared one is made again beside it.

## Proving it

Run the suite twice. One green run says nothing about residue; the second is where a leak lands.

```console
$ atf run
0 failed, 11 passed, 0 skipped   (r-83579b)
$ atf run
0 failed, 11 passed, 0 skipped   (r-32e9b6)
```
