# Configure an environment

Add a named environment to `atf.yaml` so a suite can be pointed at it, and keep the environments you
must not write to unwritable.

## The shortest path

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

```sh
atf status local
```

`atf status` lists every declared resource as `present`, `absent` or `unreachable`. If the systems
answer, the environment is configured.

## One block per system

Each key under an environment names a [system](../reference/arrange.md#system) and holds that
system's own typed configuration. `command`, `browser`, `filesystem` and `process` are ATF's own;
`sqlite` is available because the manifest loaded
[its adapter](teach-atf-a-new-system.md) through `extensions:`.

```yaml
environments:
  staging:
    sqlite:     { path: /srv/todo/todo.db }
    command:    { prefix: "ssh deploy@staging todo" }
    browser:    { headless: true }
    filesystem: { root: /srv/todo/uploads }
```

Configure the systems your resources declare. A resource declared `@browser(...)` in an environment
with no `browser:` block is an error from `atf check`, not a default. Unknown keys inside a block are
an error too, so a typo is caught before a run.

## Secrets through variables

A value that begins with `$` is a reference to a process environment variable. The whole value is
replaced; there is no interpolation inside a longer string.

```yaml
environments:
  staging:
    sqlite:  { path: $STAGING_DB }
    command: { prefix: $STAGING_TODO }
    browser: { headless: true }
```

Variables are resolved for the chosen environment only, when the manifest is loaded. An unset
variable is an error naming the variable and the environment; nothing falls back to an empty string.

Put no credential and no private host in `atf.yaml`; everybody with the repository reads it. In CI
the variables come from the pipeline's secret store, and exposing one to the step that needs it is
what catches people out — the job in [Run ATF in CI](run-atf-in-ci.md) shows where `env:` goes.

## What an environment does not hold

An environment configures systems and `mutable`. That is all of it. There is no key for the client
your suite uses to talk to your own product — no `clients:`, nothing to register. That client is a
fixture your suite writes, in ordinary Python, and
[a step you write](../reference/act.md#a-step-you-write) asks for it like any other fixture.

## `mutable`

`mutable` is **false unless stated**.

```yaml
environments:
  production:
    sqlite: { path: /srv/todo/todo.db }
```

That environment is unwritable. ATF never calls an adapter's create or delete against it:

- `atf make production` refuses and explains which environment it refused.
- A resource declared `scope="function"` is not built and not removed.
- A test naming an absent resource fails naming the resource and the reason, rather than creating it.

Add `mutable: true` where writing is what you want, as `local` does at the top of this page.

The cost is real: a new environment starts unable to make anything, and every writable environment
carries one more line. Against a read-only environment, declare what must already be there with
[`when_absent="require"`](require-something-you-cannot-create.md) so the suite reports a missing
precondition instead of failing an assertion halfway down a scenario.

## Choosing an environment

For `atf run`, `atf check`, `atf docs` and `atf edit`, the flag wins, then the variable, then the
manifest: `atf run --env staging` beats `ATF_ENV=staging atf run`, which beats `default_env: local`.

`atf status`, `atf make` and `atf import-run` take the environment as an argument and use nothing
else: `atf status staging`.

Naming an environment that does not exist is an error listing the environments that do. There is no
silent fallback to `default_env`: a typo that fell back would run the wrong suite against the wrong
place and pass.

## When it goes wrong

**`unknown environment "stagng"; defined: local, staging, production`.** A typo. No fallback happened.

**`no environment chosen: pass --env, set ATF_ENV, or add default_env`.** The manifest has no
`default_env` and nothing supplied one.

**`$STAGING_DB is not set (environment "staging", sqlite.path)`.** The variable is unset in the
process. Nothing was defaulted.

**`environment "staging" configures no "browser"`.** A resource declares a system the environment does
not configure.

**`unknown key "headles" in staging.browser`.** The adapter's typed configuration rejected it.

**`environment "production" may not be changed`.** `mutable` is false, and something asked to create
or delete.

**`unreachable: sqlite (/srv/todo/todo.db: no such file)`.** The system answered nothing. That is
distinct from `absent`, which is a system answering that a resource is not there.

## Where to go next

- [Run ATF in CI](run-atf-in-ci.md) — the same environment, chosen by a variable, seeded before the
  run so tests only ever find.
- [Require something you cannot create](require-something-you-cannot-create.md) — the declaration
  that pairs with an unwritable environment.
- [The ground](../reference/the-ground.md) — what an environment and mutability are, in all three
  faces.
