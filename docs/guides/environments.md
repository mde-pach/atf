# Running it somewhere else

*The same suite has to run against your laptop, against CI, and against a staging system you are not
allowed to write in.*

`atf.yaml` has one key. Each environment says who owns what is in it and configures the systems the
suite uses:

```yaml
environments:
  local:
    owner: atf                 # ATF may make things here. `them` means it may only look.
    http:  { base_url: "http://127.0.0.1:8801" }
    sql:   { path: ./todo.db }
    shell: { cwd: . }

  # The same application, read-only. Every thing in it becomes observed, whatever any one said.
  theirs:
    from:  local
    owner: them
```

The first environment written is the default. `from:` takes everything above it, so the second one
says only what differs. Pick one with `--env`, or set `ATF_ENV` for a shell.

## What ATF may write

`owner: atf` means a run creates and deletes here. `owner: them` means ATF only looks: a command
asked to make something stops with `environment_not_ours` and makes nothing, and a test that needs
something absent fails with its name.

One kind can say the same thing on its own, whatever the environment allows:

```python
from atf.resources.sql import Row


class Plan(Row, at="plans", owner="them"):
    """The environment's job. ATF names one; it never makes one."""

    code: Row.Key[str]
```

A plan reports one of those as `will be left alone`.

## When it cannot be reached

```console
$ atf plan
  8 scenarios
  2 phrases
  3 python tests using atf resources        ← not in the spec

  local — the http.record system could not be reached
```

The API is not running. That is a third answer, held apart from absence, so a service that is down
never reads as a service with nothing in it. The half of `atf plan` that reads the suite still ran —
faults are found without touching anything.

Start what it needs, and the same command answers in full:

```console
$ atf plan
  local
    1 present · 4 absent · 0 drifted
      absent      primary                  will be made
      absent      groceries                will be made
      absent      laundry                  will be made
      absent      anyone                   will be resolved when asked for
```

## Configuring a system

Every block inside an environment is one system's settings, under that system's name. `sql` takes a
`path` or a `url`; `http` takes a `base_url` and optional auth, headers and pagination; `shell`
takes a `prefix` put in front of every command a test runs, and a `cwd`; `filesystem` takes a
`root`; `browser` takes a `base_url` and `headless`. What each one accepts is checked against the
system's own `Settings` before a run, and a key that is missing or of the wrong type is reported
against the manifest key it came from.
