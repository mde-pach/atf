# The ground

The ground is what a run stands on: the environment it is pointed at, and whether that environment
may be changed.

## Environment {#environment}

An environment is a place where resources exist. A database file, a staging deployment, a browser
pointed at a URL — one name covering all of them, because a test does not care which it is.

Every environment is declared in `atf.yaml`, at the root of the suite:

```yaml
resources: [./resources.py]
specs: ./specs
extensions: [./adapters/todo.py]
default_env: local

environments:
  local:
    mutable: true
    todo:    { path: ./todo.db }
    shell: { prefix: "python todo.py" }

  staging:
    browser: { headless: true }
```

The file has five top-level keys.

`resources`
:   The Python modules that declare resource classes and instances, as `[./resources.py]`. Required.

`specs`
:   The directory holding scenarios and phrases, as `./specs`. Required.

`extensions`
:   Paths or installed packages — `[./adapters/todo.py, atf_payments]` — imported once at
    start-up. Importing them is what registers adapters, claims, markers, report formats and checks.
    Optional; a suite that extends nothing omits it.

`default_env`
:   The environment used when a command names none, as `local`. Optional; omitting it means every
    command must name one.

`environments`
:   The environments, by name: `local:`, `staging:`. Required.

[Extending ATF](extending-atf.md) writes each of those five registrations out in full, and is the
page to read before you put a first entry under `extensions`.

A value written as `$NAME` is read from the process environment when the environment is used. If
`$NAME` is unset, ATF stops and names the variable.

### Choosing one {#choosing-an-environment}

Three ways to say which environment a command uses. Each beats the ones under it.

1. The `--env` flag, or the environment argument a command takes — `atf run --env staging`,
   `atf status staging`. This wins over everything.
2. The `ATF_ENV` variable — `ATF_ENV=staging atf run`. This wins over `default_env`.
3. `default_env` in `atf.yaml`, used when nothing else names one.

If none of the three names an environment, ATF stops. If one of them names an environment that is
not in `environments`, ATF stops and lists the names that are. It does not fall back to
`default_env`, and it does not pick the first one.

### What an environment holds {#environment-keys}

Every key below is written inside one environment. Nothing here is inherited between environments;
each is written out in full.

`mutable`
:   Whether ATF may create, change and delete here, written `mutable: true`. It is `false` unless
    stated. See [may be changed](#may-be-changed).

**Every other key is a [driver](arrange.md#driver)**, never a system. A driver is the machinery an
adapter works through — a connection, a browser, a shell — and it is the only thing that carries
settings. Several systems can share one: `file`, `directory` and `tree` all work through
`filesystem`, and configure it once.

`shell`
:   Settings for the `shell` driver: `prefix`, put in front of every command a test runs; `cwd`,
    where a command runs and where a `shell.process` is started; `start_timeout`, how long a
    `shell.process` waits for a declared port. `shell: { prefix: "python todo.py" }`. No default;
    required if any test runs a command or declares a `shell.process`.

`browser`
:   Settings for the `browser` driver: `base_url`, where a page opens; `headless`, whether a window
    is drawn. `browser: { headless: true }`. No default; required by the `page` system.

`filesystem`
:   Settings for the `filesystem` driver: `root`, the directory paths are resolved against.
    `filesystem: { root: ./workspace }`. No default; required by the `file`, `directory` and `tree`
    systems.

`http`
:   Settings for the `http` driver: `base_url`, and optionally `auth`, `headers`, `timeout`,
    `verify` and `pagination`. Required by the `rest` system.

`sql`
:   Settings for the `sql` driver: `path` to a database file, or `url` to one elsewhere — one of the
    two, never both. Required by the `sql` system.

Those are the five drivers ATF ships. Every other block is a driver the suite registered under
`extensions`, taking the settings that driver declares: `sql: { path: ./todo.db }` is the
`sqlite` driver used throughout this documentation, and its `path` is the database file. There is no
other kind of key. A suite's own client of the product — an HTTP wrapper, an SDK, a queue helper —
is an ordinary pytest fixture the suite writes, and none of ATF's business.

A driver block is needed only when something in the suite reaches it. If an adapter asks for a
driver the chosen environment has no block for, ATF stops before running anything and names the
adapter, the driver and the environment.

### Settings are not options {#settings}

Everything inside an environment block is a **setting**, and settings belong to drivers. A setting
is written in `atf.yaml` under one environment and varies from one environment to the next, and that
is the test of where a value belongs. What does not vary between environments is an **option**,
written on the resource class's
decorator and varying per resource. `sql: { path: ./todo.db }` is a setting;
`@todo.list()` carries options.

`TodoList` maps to the same table wherever it is arranged, so the table is an option. The database
file is `./todo.db` on a laptop and something else in CI, so the path is a setting. Each system
declares both as typed classes, so a misspelled key is rejected before a run rather than inside one.
[Adapter](arrange.md#adapter) shows those two classes being declared, if you want to see the types
your keys are checked against.

**In CI** — the environment is named by `--env` or `ATF_ENV`, and every report records which one ran.
Two environments in one CI file are two invocations, not one.

**In the editor** — `atf edit` opens on one environment and shows its name throughout. Switching
environments re-asks every question about what is present; nothing is carried across.

**To an agent** — `atf edit --mcp` serves the environment's name and settings as structured data, so
an agent can tell whether it is looking at a scratch database or a shared deployment before it
proposes anything.

## May be changed {#may-be-changed}

`mutable` says whether ATF may write to an environment. **It is `false` unless stated.**

In an immutable environment ATF will find, act and browse, and it will do nothing else. It creates
nothing that is missing, updates nothing that differs from its declaration, and deletes no
function-scoped resource after a test. `atf make` refuses and names the environment. A test whose
resource is absent fails, naming the resource and the environment; where the environment is mutable
the same resource is made and the test runs.

The cost is that a test needing something the environment does not have has nowhere to go. There is
no blocked state and no quiet skip: a resource that cannot be made fails the test that asked for it.
Run `atf status <env>` first — it reports every resource as `present`, `absent` or `unreachable` —
and either seed what is missing with `atf make` against an environment that is mutable, or run the
slice that the environment can already support.

**In CI** — shared environments are declared immutable, and anything that must be seeded is seeded by
a separate `atf make` step against an environment that is not. The failure message for a resource
that cannot be made names the environment, so a red run against staging is distinguishable from a
product bug.

**In the editor** — buttons that would create, change or delete are absent, not
disabled-with-an-error. The editor shows what is present and lets you run against it, and it marks
in advance which tests will fail for want of something it may not make.

**To an agent** — every resource carries whether it can be made here, so an agent asking for
something absent is told the environment is immutable rather than being handed a stack trace.

## Where to go next

- [Arrange](arrange.md) defines resources, the systems they belong to and the adapters behind them —
  read it next if the environment keys above named a system you have not met.
- [Configure an environment](../how-to/configure-an-environment.md) walks through adding a second
  environment to a suite that already has one.
- [Run ATF in CI](../how-to/run-atf-in-ci.md) covers naming an environment from a pipeline and
  keeping the mutable one out of it.
