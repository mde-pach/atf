# ATF — Another Test Framework

> A build blueprint. This single document is meant to be dropped into an empty repository and used to
> construct ATF in full. It specifies the architecture, every component contract, the data formats, the web
> cockpit, and a milestone-by-milestone build order with verification at each step. Where a load-bearing
> interface exists, its shape is given exactly; where behaviour is an algorithm, it is described precisely
> enough to implement without further decisions.

---

## 0. What ATF is

ATF is a generic end-to-end test framework built around one idea: **a test is a readable spec that declares
the resources it needs, and the framework makes those resources exist before the test runs.**

Four moving parts:

1. **Catalog** — resources (the entities a test needs) declared as plain YAML data, with dependency lineage
   between them. Purely declarative; no code.
2. **Materializer** — an engine that provisions a resource and its dependency closure into a target
   environment, idempotently, by delegating the *how* to a pluggable **adapter** per backend system.
3. **Specs** — Gherkin scenarios (pytest-bdd). Each resource type becomes a generated pytest fixture, and a
   single generic step provisions any resource named in a scenario. Authors write scenarios and a small
   shared vocabulary of action/assertion steps; everything else is generated.
4. **Cockpit** — a self-contained FastAPI + htmx web app that discovers the catalog, specs, tests and
   fixtures, shows how they link, runs tests with live per-test progress, and answers one question:
   *"can I ship with confidence?"*

The engine, spec plumbing, discovery and cockpit are **generic**. A consuming project supplies only
**content** (its catalog + specs), **adapters** (how to talk to its systems), and a **manifest** (config).

### The domain relationship (the vocabulary — keep it exact everywhere)

> A **resource** is *used by* a **test** that *covers* a **spec**. A **fixture** is *used by* a **test**.

- **Resource** — one catalog node (an instance), e.g. `accounts.primary`.
- **Resource type** — a kind of resource, e.g. `account`. Declared once; many instances.
- **Spec** — a Gherkin scenario: the behaviour, in plain English.
- **Test** — a collected pytest item that covers a spec (one per scenario, or one per Examples row).
- **Fixture** — a pytest fixture a test builds on (including the generated resource-type factories).
- **Adapter** — the code that knows how to `find`/`create`/`delete` resources of a given **system**.
- **Context** — a per-scenario scratchpad; steps write what they create and read what they need.

---

## 1. Repository layout

ATF ships as an installable Python package plus a vendored front-end. A consuming project is a separate
directory that depends on it.

```
atf/                              # the framework package (this repo builds this)
  pyproject.toml                  # see Appendix A
  src/atf/
    __init__.py
    config.py                     # manifest resolution + typed Manifest (§4)
    catalog.py                    # Node model + loader + validation (§5)
    materializer.py               # provisioning engine (§8)
    adapters/
      __init__.py                 # Adapter protocol + factory registry (§7)
      rest.py                     # built-in generic REST adapter
      reference.py                # built-in find-only adapter
    bootstrap.py                  # (env) -> (Manifest, Materializer, clients) — one entry, all callers (§4)
    plugin.py                     # pytest plugin: context + factories + generic step + teardown (§10)
    discovery.py                  # specs / tests / fixtures / resource-links discovery (§11)
    runner.py                     # synchronous test run → structured results (§12)
    jobs.py                       # background runs with live progress (§12)
    cli.py                        # `atf` command (§15)
    cockpit/
      app.py                      # FastAPI app factory
      deps.py                     # cached materializer / discovery / results / active job
      routers/                    # overview, catalog, specs, tests, fixtures, search
      templates/                  # Jinja2 (base + one per vertical + partials)
      static/                     # app.css, htmx.min.js (vendored; §13.6)
  tests/                          # the framework's OWN unit tests (no network; fake adapter)
  examples/todo/                  # a minimal reference consumer (§17)
```

A consuming project (also produced by `atf init`, §15) looks like:

```
my-suite/
  atf.yaml                        # manifest (§9)
  catalog/
    resources.yaml                # resource-type registry (§6.1)
    *.yaml                        # instances (§6.2)
  adapters.py                     # optional custom adapters (§7.5)
  specs/
    features/*.feature            # scenarios
    steps/test_*.py               # scenarios() binding + vocabulary (When/Then)
    api.py                        # the system-under-test client(s) the vocabulary calls (§10.6)
  conftest.py                     # one line: pytest_plugins = ["atf.plugin"]
```

---

## 2. Tech stack & conventions

- **Python ≥ 3.11**, managed with **uv**.
- **Lint/type**: `ruff` (select `E,F,I,UP,B,SIM`, line-length 120) and **`ty` in strict mode**
  (`error-on-warning = true`, `missing-override-decorator = error`, `possibly-unresolved-reference = error`),
  scoped to `src/atf`. Zero suppressions; avoid `type: ignore`. Concrete config in **Appendix A**.
- **Tests**: `pytest`, `pytest-bdd ≥ 8`, `pytest-json-report`.
- **Web**: `fastapi`, `jinja2`, `uvicorn[standard]`; **htmx vendored** into `static/` (§13.6), no CDN, no
  build step, server-render only.
- **HTTP**: `httpx` inside adapters/clients only (chosen over requests for timeouts + typing; pinned in
  Appendix A).
- **Config parsing**: `pyyaml` (`atf.yaml`). No docstrings on obvious functions; comments terse.

---

## 3. Architecture: generic vs project

| Layer | Ships in ATF (generic) | Provided by the project |
|---|---|---|
| Manifest schema + resolution + bootstrap | ✔ | the filled-in `atf.yaml` |
| Catalog format, loader & validation | ✔ | the actual YAML nodes |
| Materializer engine | ✔ | — |
| Adapter SPI + factory registry | ✔ | custom adapters (optional) |
| Built-in adapters (REST, reference) | ✔ | their per-env config (manifest) |
| Spec plumbing (context, factories, generic step, teardown) | ✔ (pytest plugin) | `.feature` files + vocabulary + SUT client |
| Discovery / runner / jobs | ✔ | — |
| Cockpit (UI, routes, design system, security posture) | ✔ | display config + mutable-env allow-list |
| CLI | ✔ | — |

Everything project-specific reaches ATF through exactly three seams: **adapters**, **catalog+specs content**,
and the **manifest**. Nothing in `src/atf` may name a specific product, domain, URL, or secret.

---

## 4. Configuration & bootstrap (`config.py`, `bootstrap.py`)

Every entry point — the pytest plugin, the cockpit, the CLI — must find and load configuration the **same
way**. This is the wiring the rest of the system assumes; specify it first.

### 4.1 Manifest resolution

`resolve_manifest() -> Path`:
1. If `ATF_MANIFEST` is set, use it.
2. Else search upward from the current directory for `atf.yaml` (then `atf.toml`), stopping at the first hit
   or filesystem root.
3. If none found, raise `ConfigError` with a clear message (and, for the CLI, a hint to run `atf init`).

`resolve_env(manifest) -> str`: `ATF_ENV` if set, else `manifest.default_env`.

### 4.2 The `Manifest` object

`load_manifest(path) -> Manifest` parses and **validates** the file (fail fast on missing/invalid keys),
producing a typed object:

```python
@dataclass(frozen=True)
class Manifest:
    root: Path                                  # dir containing the manifest
    catalog_dir: Path                           # resolved from `catalog:`
    specs_dir: Path                             # resolved from `specs:`
    default_env: str
    adapter_modules: list[str]                  # dotted modules to import for register() calls
    environments: dict[str, EnvConfig]          # name -> per-system settings + client settings
    mutable_envs: set[str]                      # envs where Seed/Create/Run are allowed (§13.5)
    display: DisplayConfig                       # cockpit cosmetics
```

`EnvConfig` holds, per environment: `adapters: dict[system, dict]` (raw per-system settings, passed to that
system's adapter factory) and `clients: dict[name, dict]` (settings for the system-under-test clients the
specs call — see §10.6). Secrets are never literals: settings reference env vars (e.g. `value_env: ATF_TOKEN`)
and are resolved at build time.

### 4.3 One bootstrap for all callers

`bootstrap(env: str | None = None) -> Boot` is the single funnel:

```python
@dataclass
class Boot:
    manifest: Manifest
    env: str
    materializer: Materializer          # catalog loaded, adapters built for `env`
    clients: dict[str, dict]            # resolved SUT client settings for `env`
```

It: resolves + loads the manifest, imports each `adapter_modules` entry (registering adapter **factories**,
§7.2), builds `{system: adapter}` for `env` from `EnvConfig.adapters`, constructs the `Materializer`, and
resolves client settings (env-var substitution). The plugin, cockpit `deps.py`, and CLI all call `bootstrap`
— there is no other path to a configured system.

---

## 5. Node model & catalog loader (`catalog.py`)

### 5.1 The `Node` shape

```python
class Node(TypedDict):
    id: str                 # "<collection>.<name>"
    collection: str         # file stem
    name: str
    resource: str           # resource type key (into resources.yaml)
    system: str             # which adapter handles it
    mode: str               # "create" | "reference"        (default "create")
    lifecycle: str          # "persistent" | "ephemeral"    (default "persistent")
    id_field: str           # record field carrying the identity (default "id")
    config: dict[str, Any]  # remaining adapter-specific fields from the type entry
    represents: str
    depends_on: list[str]
    dependents: list[str]   # computed reverse edges
    body: dict[str, Any]
```

`system`, `mode`, `lifecycle`, `id_field`, and `config` come from the **type** (resources.yaml).
`represents`, `depends_on`, `body` come from the **instance**. **persistent** = find-or-created, reported
present/absent. **ephemeral** = built fresh each run, never reused; cockpit shows "built per run".

### 5.2 Loader + validation

`load_catalog(root, registered_systems, reserved_names) -> tuple[types, nodes]`:
1. Read `resources.yaml` → type registry.
2. Build a node per instance (`id = f"{stem}.{name}"`), merging type + instance; compute `dependents`.
3. **Validate — raise `CatalogError` listing every problem found (don't stop at the first):**
   - every node's `resource` exists in the type registry;
   - every `depends_on` id resolves to a known node (no dangling edges); the dependency graph is acyclic;
   - no two nodes of the same **type** share a `name` (types+names must be unique so `resolve_id` is
     unambiguous);
   - every type's `system` has a registered adapter factory (`system in registered_systems`);
   - **no resource type name collides with a reserved fixture name** (`reserved_names` = `{context, api, env,
     materializer, request}` ∪ pytest built-ins) — otherwise the generated factory (§10.2) would clobber it.
4. Loader does **no** network and is import-safe.

---

## 6. Catalog format (authoring)

### 6.1 `resources.yaml` — the type registry

Each key is a type; universal keys are `system`, optional `mode`, `lifecycle`, `id_field`. All other keys
are passed to the type's adapter as `config`.

```yaml
account:
  system: rest
  path: /accounts
  natural_key: email          # get-or-create key
project:
  system: rest
  path: /projects
  natural_key: [account_id, slug]     # composite natural key
external_widget:
  system: rest
  mode: reference             # find-only; error if absent
  path: /widgets
  natural_key: name
  ref_field: name             # remote field to match `name` against
job_run:
  system: rest
  path: /runs
  natural_key: token
  id_field: uuid              # this API returns identity under `uuid`, not `id`
lead:
  system: app                 # a custom, project-provided adapter
  lifecycle: ephemeral
  natural_key: email
```

### 6.2 Instance files — e.g. `projects.yaml`

```yaml
alpha:
  resource: project
  represents: A project under the primary account.
  depends_on:
    - accounts.primary
  body:
    slug: alpha
    account_id: ${accounts.primary.id}     # placeholder, resolved at provision time
```

### 6.3 Placeholders (resolved by the materializer)

- `${<collection>.<name>.id}` — the **identity** of an already-provisioned dependency, read from that node's
  `id_field`. `.id` here is a keyword meaning "identity", not a literal field name; it maps through the
  dependency's `id_field`. Resolves recursively in strings, lists, dicts. If the dependency isn't present
  yet, the containing natural-key value is treated as unresolvable (→ node counted absent, not errored).
- `${now+<N>d HH:MM}` — ISO-8601 UTC timestamp N days from now at HH:MM.

Rules: block YAML only, no head comments, `represents:` is the only description, instance names are explicit
words (never numbered).

---

## 7. Adapters (`adapters/`)

The seam between the generic engine and a concrete backend, and the primary extension point.

### 7.1 The protocol

```python
Record = dict[str, Any]                         # carries the identity under the node's id_field

class Adapter(Protocol):
    def find(self, node: Node, ctx: "Materializer") -> Record | None: ...
    def create(self, node: Node, body: Record, ctx: "Materializer") -> Record: ...
    def delete(self, node: Node, record: Record, ctx: "Materializer") -> None: ...  # optional; may no-op
```

- `find` → the live record or `None` (absent). Ephemeral adapters always return `None`.
- `create` → provisions and returns the record (identity under `node["id_field"]`). `body` is the node body
  **after** placeholder resolution.
- `delete` → best-effort teardown (used for ephemeral resources, §10.5). A no-op default is fine for backends
  without deletion.
- `ctx` lets REST-style adapters reuse the materializer's cached listing; custom adapters may ignore it.

### 7.2 Factory registry (register **factories**, not instances)

An adapter needs its environment's settings, so registration is by **factory**, not instance:

```python
AdapterFactory = Callable[[dict[str, Any]], Adapter]   # (env settings for this system) -> Adapter

_REGISTRY: dict[str, AdapterFactory] = {}
def register(system: str, factory: AdapterFactory) -> None: ...
def build(system: str, settings: dict[str, Any]) -> Adapter: ...   # KeyError names the missing system
def registered_systems() -> set[str]: ...
```

Built-in factories register on import of `atf.adapters`. Project factories register when `bootstrap` imports
the manifest's `adapter_modules`. The materializer receives already-built `{system: adapter}` from
`bootstrap` (§4.3) and only dispatches — **it contains no per-system branching.**

### 7.3 Built-in `RestAdapter` (`rest.py`)

A configurable get-or-create over a JSON REST API. Its factory reads env settings: `base_url`; `auth` (§7.4);
`pagination` (either a bare list response, or `{results_key, count_key}` for offset paging); optional
`timeout` (default 30s) and `retries` (default 0, exponential backoff). Per-type `config` supplies `path`,
`natural_key` (str|list), optional `list_path` + `list_filter` (a scoped/filtered listing endpoint for large
collections), optional `ref_field`, and the node's `id_field`.

- `find(node)`: resolve each natural-key value (placeholders included) from `body`; any unresolvable ⇒
  `None`. List `path` (or `list_path?{list_filter}=…` when configured) and return the first record whose keys
  all match. For `reference` mode with a single key, match against `ref_field`. Comparison is string-equal
  with a datetime-aware fallback (parse both as ISO-8601, compare instants). Cache listings within a
  materialize pass; invalidate on create.
- `create(node, body)`: `POST base_url+path` with `body`; return the JSON record (identity read via
  `id_field`). Configurable success codes.
- `delete(node, record)`: `DELETE base_url+path/{record[id_field]}` if the API supports it; else no-op.

### 7.4 Auth schemes

`auth` in env settings selects a scheme the adapter (and SUT clients, §10.6) apply uniformly:

- `none`.
- `header` — `{header: X-Actor, value_env: ATF_ACTOR}` (static header from an env var).
- `bearer` — `{token_env: ATF_TOKEN}` → `Authorization: Bearer …`.
- `session` — `{login_path, username_env, password_env}`: POST credentials once, capture the session
  cookie/token, reuse for the lifetime of the adapter/client.

Token-exchange or anything more exotic is delegated to a **custom adapter** (§7.5); the built-in schemes
cover the common cases.

### 7.5 `ReferenceAdapter` and custom adapters

- `ReferenceAdapter`: `find` = filtered lookup (find-only); `create` raises; `delete` no-ops. For
  `mode: reference` resources that must already exist.
- **Custom adapter** (escape hatch for multi-step provisioning): a project supplies a class implementing the
  protocol and a factory, registered from a module named in `adapter_modules`. Its `create` may run an
  arbitrary chain (e.g. sign up → patch → poll an external sync until ready) and return a synthesized record;
  its `find` may return `None` (ephemeral); its `delete` tears the instance down. This is how an ephemeral
  actor is modelled — as one adapter, so the catalog treats it like any other resource.

---

## 8. The Materializer (`materializer.py`)

The domain-free engine. Holds the loaded catalog, an env name, a listing cache, and the built
`{system: Adapter}` map (from `bootstrap`). Public surface:

```python
class Materializer:
    nodes: dict[str, Node]
    def __init__(self, catalog_root, env, adapters: dict[str, Adapter]): ...
    def reload(self) -> None: ...
    def resolve_id(self, resource_type: str, name: str) -> str: ...
    def find_existing(self, node: Node) -> Record | None: ...
    def ensure(self, resource_type: str, name: str) -> Record: ...          # raises on failure
    def status(self, collection: str | None = None) -> dict[str, dict]: ...
    def materialize(self, subset: Iterable[str]) -> dict: ...               # {results, records}
    def create_closure(self, nid: str) -> dict: ...
    def create_all(self) -> dict: ...
    def teardown(self, records: dict[str, Record]) -> None: ...             # best-effort delete (ephemeral)
```

### 8.1 Algorithms

- **closure(nid)** — DFS over `depends_on`.
- **topo(subset)** — dependency-first order within a subset.
- **resolve(value, ids)** — apply placeholder resolution (§6.3) using `{node_id: identity}`.
- **materialize(subset)** — for each node in topo order:
  - `mode == "reference"` → `find`; missing ⇒ error entry.
  - else `find`; present ⇒ `exists`; else `adapter.create(node, resolve(body, ids))` ⇒ `created`.
  - record `ids[nid]` (the identity via `id_field`) and `records[nid]` for every node. **Stop on first
    error.** Return `{"results": [{id, action, ok, detail?}], "records": {nid: record}}`.
- **ensure(type, name)** — `resolve_id` → `create_closure`; if any result is `ok == False`, **raise
  `ProvisioningError(node_id, detail)`** (do not hand back an empty record); otherwise return `records[nid]`.
  This is the single entry point the spec layer calls.
- **status(collection)** — per node: no adapter/unsupported ⇒ `unsupported`; ephemeral ⇒ `ephemeral`; else
  `find` ⇒ `present`/`absent`; exceptions ⇒ `error` (+short detail).
- **teardown(records)** — for each ephemeral node present in `records`, call its adapter's `delete`,
  swallowing and logging errors (teardown must never fail a run).

`materialize` **must** include `records` so `ensure` returns an ephemeral resource's created identity (its
`find` returns `None`).

---

## 9. Manifest schema (`atf.yaml`)

```yaml
catalog: ./catalog
specs: ./specs
default_env: dev

adapters:                       # dotted modules imported for their register() side-effects
  - my_suite.adapters

mutable_envs: [dev, staging]    # envs where the cockpit may Seed / Create / Run (§13.5)

environments:
  dev:
    adapters:                   # per-system settings → each system's adapter factory
      rest:
        base_url: https://dev.example.com
        auth: { header: X-Actor, value_env: ATF_ACTOR }
        pagination: { results_key: results, count_key: count }
        timeout: 30
      app:
        base_url: https://dev-app.example.com
        auth: { session: { login_path: /login, username_env: ATF_USER, password_env: ATF_PASS } }
    clients:                    # settings for the system-under-test client(s) specs call (§10.6)
      api:
        base_url: https://dev.example.com
        auth: { header: X-Actor, value_env: ATF_ACTOR }
  staging:
    adapters: { rest: { base_url: https://staging.example.com, auth: { header: X-Actor, value_env: ATF_ACTOR } } }
    clients:  { api: { base_url: https://staging.example.com } }

display:                        # cockpit cosmetics (optional; sensible defaults)
  systems:
    rest: { label: API, color: "#2f6be0" }
    app:  { label: App, color: "#7857d8" }
```

- Secrets are only `*_env` pointers, resolved at bootstrap.
- `environments.<env>.adapters.<system>` feeds that system's factory; `.clients.<name>` feeds the SUT client.
- `mutable_envs` is the allow-list the cockpit enforces before any mutating action.

---

## 10. Spec framework (`plugin.py`)

Enabled with `pytest_plugins = ["atf.plugin"]`. At import it calls `bootstrap` (§4.3) for the active env,
then generates three things so specs stay pure Gherkin.

### 10.1 `context`

```python
@pytest.fixture
def context() -> SimpleNamespace:      # the scenario scratchpad
    return SimpleNamespace()
```

State passes between steps only through `context`. No globals, no `target_fixture` juggling.

### 10.2 Factory fixtures — one per resource type, generated

For each type in the catalog, register a fixture named after the type whose value is `factory(name) -> record`:

```python
def _make_factory(resource_type: str):
    @pytest.fixture(name=resource_type)
    def _factory(materializer):
        return lambda name: materializer.ensure(resource_type, name)
    return _factory

for t in resource_types(): globals()[t] = _make_factory(t)
```

Real, discoverable fixtures (`account`, `project`, `lead`, …). Catalog validation (§5.2) has already
guaranteed no type name collides with a reserved fixture, so this generation is safe.

### 10.3 The generic provisioning step — one, static

```python
@given(parsers.parse('the {resource_type} "{name}"'))
def _provision(context, request, resource_type, name):
    setattr(context, resource_type, request.getfixturevalue(resource_type)(name))
```

`Given the account "primary"` provisions `accounts.primary` and stashes it on `context.account`. Multiple
resources are unambiguous (`context.account`, `context.project`, `context.lead`).

> Do **not** generate one step per type — pytest-bdd names the step fixture after the function, so
> dynamically-built steps collide and go undiscovered. One generic step capturing `{resource_type}` is the
> correct, discoverable form. Per-type *fixtures* are fine to generate; per-type *steps* are not.

**Scenario Outlines:** pytest-bdd substitutes `<placeholders>` from the `Examples:` table before the step
text reaches the parser, so `Given the account "<who>"` works unchanged — the generic step sees the concrete
name.

### 10.4 Vocabulary (authored, shared)

The only hand-written step code: `When`/`Then` actions and assertions in the project's `steps/`. Each reads
its subject from `context`, calls the SUT client, writes the outcome back.

```python
@when("I request its availability")
def _(context, api):
    context.result = api.availability_of(context.account)

@then("no slots are returned")
def _(context):
    assert context.result == []
```

> **Record contract:** a factory / `ensure` returns the *adapter's* record. Specs read fields off it
> (`context.account["email"]`, an identity, etc.). Those field names are the project's contract with its own
> backend — ATF neither defines nor validates them.

### 10.5 Teardown of ephemeral resources

An autouse, function-scoped finalizer tears down what a scenario created ephemerally:

```python
@pytest.fixture(autouse=True)
def _teardown(materializer, context):
    yield
    materializer.teardown(getattr(context, "_ephemeral", {}))
```

The generic step records each ephemeral record it provisions onto `context._ephemeral`. Teardown is
best-effort and never fails the test (§8.1). Persistent resources are left in place (they are get-or-created).

### 10.6 The system-under-test client

Specs call the project's own client (`specs/api.py`) against the **consumer** surface, which may differ from
the provisioning adapters. ATF provides its settings via a fixture:

```python
@pytest.fixture
def client_config(env):            # provided by the plugin; from manifest environments.<env>.clients
    return _BOOT.clients

# project's specs/api.py fixture consumes it:
@pytest.fixture
def api(client_config):
    return MyClient(**client_config["api"])   # base_url, auth already resolved
```

The plugin also exposes `env` (from `ATF_ENV`/`default_env`) and `materializer` (session-scoped, from
`bootstrap`). Convention: one `.feature` = one behaviour area; one `Scenario` = one spec; `scenarios("…")` in
a `steps/test_*.py` module binds them.

---

## 11. Discovery (`discovery.py`)

Turns the project into the structured model the cockpit renders. Source of truth is pytest itself.

### 11.1 Data shapes

```python
@dataclass
class Step:  keyword: str; text: str; resources: list[str]           # resources = resolved node ids
@dataclass
class Spec:  id; feature; scenario; narrative; steps; resources; tags; skipped; test_ids
@dataclass
class Test:  id; nodeid; name; params; file; covers; resources; fixtures; skipped
@dataclass
class Fixture: name; doc; scope; used_by
@dataclass
class Discovery: specs; tests; fixtures
```

### 11.2 Specs from features

Parse each `.feature`: Feature + narrative, Scenarios/Outlines, tags, steps. In each step, find provisioning
phrases with `the (\w+) "([^"]+)"`, **keep only matches whose captured word is a known resource type**
(intersect with the type registry — this avoids linking action sentences like `the account requests "X"`),
resolve `(type, name)` → node id via the loaded catalog, and record them. `id = slug(feature)::slug(scenario)`.

### 11.3 Tests + fixtures from a real pytest run

pytest-bdd resolves step fixtures lazily, so only observing a run exposes them. Run pytest once with a
throwaway `-p` plugin that: records per nodeid the feature/scenario/tags/skip from `item.obj.__scenario__`
(`pytest_collection_modifyitems`); records each fixture set up per nodeid and expands the closure through
each fixturedef's argnames (`pytest_fixture_setup`); writes the map at `pytest_sessionfinish` regardless of
outcome. Each item → a `Test` linked to its `Spec` by (feature, scenario); `resources` = the spec's
resources; `fixtures` = captured project fixtures. Fixtures come from `pytest --fixtures -v`.

> Discovery must degrade gracefully: if the run errors (env down), still return specs (static parse) and
> whatever fixtures/tests were observed.

---

## 12. Runner & Jobs (`runner.py`, `jobs.py`)

- **runner.run(nodeids | None, env) -> {nodeid: TestResult}** — subprocess `pytest … --json-report` with
  `ATF_ENV` set; parse outcome/duration/detail per test. Serialized by a lock; timeout-guarded.
  `TestResult = {nodeid, outcome, duration, detail}`.
- **jobs** — background runs with live progress. `start_run(nodeids, env) -> Job` spawns a thread running
  pytest with a progress plugin emitting one JSONL line per test event (`start`, then `result` with
  outcome/duration/detail) to a temp file the thread drains. `Job` holds per-nodeid `TState`
  (`pending→running→passed/failed/skipped/error`), `done`, `merged`. `active(env)` returns the running job;
  on completion outcomes fold into cached results. Powers the cockpit's progressive run view.

---

## 13. The Cockpit (`cockpit/`)

A single FastAPI app serving server-rendered htmx pages — the product surface. `deps.py` calls `bootstrap`,
caches the per-env materializer, status, discovery, results and active job; discovery/status refresh lazily.

### 13.1 Information architecture

A dark left **rail** in two groups: **Confidence** → **Overview** (landing); **Explore** → **Catalog**,
**Specs**, **Tests**, **Fixtures** (live counts). A **⌘K search** launcher on top; the **environment** badge
at the bottom. Shared page header grammar: breadcrumb → title → entity badge → status pill → primary action.

### 13.2 The five verticals

- **Overview** — three meter cards: **Config** (present/total, "Seed N absent"), **Coverage** (specs
  covered, resources exercised), **Health** (tests passing/failing/skipped, "Run all"). Plus *coverage gaps*
  and *recent runs*.
- **Catalog** — nav (grouped by collection) │ **dependency graph** (server-computed layout, §13.7) │
  inspector (represents, **Needs**, **Used by tests**, payload; per-node Create; Sync; Seed).
- **Specs** — list │ detail: narrative + **multi-line Gherkin with resource names linked** to their node +
  a **selectable, runnable table of covering tests**.
- **Tests** — table **grouped by covered spec**, multi-select + **Run selected / Run all**, inspector:
  *covers spec → uses resources → uses fixtures → last run*.
- **Fixtures** — list │ detail (doc, scope, *used by tests*).

### 13.3 Design system (`static/app.css`)

Entity accents (Resource/Spec/Test/Fixture each a distinct hue, on every chip/badge/graph node). Status
semantics separate from accents: present/passing green, absent/not-run neutral, failing red, skipped/attention
amber, running accent+spinner. Token-based **light and dark** themes (`prefers-color-scheme` + a `data-theme`
override). Tabular numerals; responsive; wide content scrolls in its own container. System labels/colours in
the Catalog come from manifest `display.systems` (defaulted otherwise) — the only place domain names surface,
and it is configuration.

### 13.4 Reactivity (generic, app-wide)

- Top **progress bar** on any htmx request (pollers marked `data-quiet`).
- Every mutating control uses `hx-disabled-elt="this"` + a `.htmx-request` spinner.
- **Progressive runs**: a run starts a background **job** and returns immediately; the view **polls** (an
  `hx-trigger="load delay:Nms"` element re-arming until done), showing each test queued → running →
  passed/failed. Run buttons stay disabled until completion; header counters and the run-all button re-sync
  via **out-of-band swaps**.

### 13.5 Security posture (mandatory)

The cockpit performs **mutating actions against real environments** (Seed/Create/Run). Therefore:

- **Default bind `127.0.0.1`.** `atf serve` must not listen on `0.0.0.0` without an explicit `--host` flag
  and a printed warning.
- **Mutating actions are gated by `mutable_envs`** (§9). For an env not in the allow-list, the cockpit
  renders Seed/Create/Run controls **disabled** and the routes reject the action (409) — read-only.
- **Destructive actions confirm.** Seed / Create / Run present a confirmation the user must accept; the route
  requires a confirmation token.
- **No built-in authentication.** ATF is single-user local by design; for shared hosting, put it behind an
  authenticating reverse proxy. State this in the docs and the `serve` banner.

### 13.6 Vendored htmx

Ship `htmx.min.js` in `static/` (pin a specific version, e.g. 2.x; record the version + SHA in a comment).
No CDN reference. The build (or `atf init`) documents how to refresh it.

### 13.7 Graph layout constants

Server computes a full-lineage neighbourhood of the focus node: walk `depends_on` upstream and `dependents`
downstream, place each layer in a column, centre columns vertically, emit absolutely-positioned boxes + bezier
edges. Starting constants (tune visually): `NODE_W 162, NODE_H 44, COL_GAP 232, ROW_GAP 60, PAD 60`. The
client auto-scrolls the focus node to centre on load and after each swap. Treat exact spacing as
iterate-visually; the topology (columns by depth, edges by `depends_on`) is fixed.

---

## 14. Concurrency & isolation

v1 is **single-worker**. The session materializer, its listing cache, and get-or-create are not safe under
parallel workers, and the cockpit serializes runs with a global lock (one active job per env). Do not enable
`pytest-xdist`. Multi-worker execution (per-worker materializer, provably-idempotent creates, per-worker
ephemeral namespaces) is a future extension (§18), not v1. State this limit in the docs.

---

## 15. CLI (`cli.py`)

Entry point `atf` (declared in Appendix A), reading the manifest via §4.1:

- `atf init` — scaffold a new consuming project: `atf.yaml`, `catalog/` (with a starter `resources.yaml`),
  `specs/` (a sample feature + `conftest.py` with `pytest_plugins`), and `adapters.py` stub.
- `atf serve [--env] [--host 127.0.0.1] [--port]` — run the cockpit (uvicorn); prints the security banner.
- `atf seed <env> [--type <t>] [--name <n>]` — materialize all (or a subset) into an env; refuses envs not in
  `mutable_envs`.
- `atf status <env>` — print per-resource present/absent/ephemeral.
- `atf run [paths…] [--env]` — run specs, print structured results; nonzero exit on failure (CI guard).

---

## 16. Quality gates

- `ruff check src` and `ty check` (strict) clean — enforced in CI.
- The framework has its **own** `tests/` (catalog loader + validation, materializer with an in-memory fake
  adapter, placeholder resolution, ensure-raises-on-failure, teardown calls delete, discovery parsing +
  known-type filtering, jobs progress). **No network** — use the fake adapter. The example project (§17) is
  the integration proof.
- A CI workflow runs lint + framework tests on every change. A consuming project wires `atf run` as its own
  deployment guard.

---

## 17. Example project (`examples/todo/`)

A minimal reference consumer exercising every seam without a real backend: a tiny in-process fake API served
during the test session; a `rest` type or two (`account`, and `project` with a `depends_on`); one **custom
ephemeral adapter** demonstrating the escape hatch **and** `delete` teardown; two specs (one pure-config
assertion, one provisioning a dependency chain, using the SUT-client fixture); and a filled-in `atf.yaml`
with `mutable_envs` and `clients`. Building this to green — via `atf run` and by driving the cockpit
headlessly — proves the framework end to end and doubles as living documentation.

---

## 18. Non-goals & future extensions (v1 scope boundary)

Explicitly **not** in v1 — do not build these; leave the seams clean for them later:

- **Event-emission assertions** (asserting a feature emitted event X with payload Y). Would arrive as
  vocabulary + an events adapter/observer; the adapter SPI and `context` already accommodate it.
- **Contract / route coverage** (Schemathesis-style additive-only route checks) as a distinct spec-type/
  vertical.
- **Multi-worker parallelism** (§14).
- **Built-in cockpit authentication / multi-user** (§13.5).
- **Non-HTTP adapters** beyond what the SPI already allows (the protocol is transport-agnostic; only the
  built-in adapters are HTTP).
- **The framework's own end-user documentation set** (Diátaxis: a "write your first spec" tutorial, "add an
  adapter" how-to, manifest/catalog reference, model explanation). Plan it once the engine is built; the
  blueprint here is for *builders*, not end users.

---

## 19. Build sequence (milestones — each leaves a working, verifiable system)

- **M0 — Skeleton.** `pyproject.toml` (Appendix A), package layout, uv env, ruff + ty configured and passing
  on the empty package. *Verify:* `uv run ruff check` and `uv run ty check` clean.
- **M1 — Config + Catalog.** Manifest resolution/loader/`Manifest`; `Node` + `load_catalog` **with
  validation**. *Verify:* unit tests — a fixture catalog loads with correct ids/`dependents`; each validation
  rule raises on a crafted bad catalog (dangling dep, dup name, unknown type/system, reserved-name collision,
  cycle); loader is import-safe.
- **M2 — Adapters + Materializer.** Protocol + **factory** registry; an in-memory **fake adapter**; the
  engine (closure, topo, resolve, materialize, **ensure-raises**, status, teardown). *Verify:* provision a
  dependency chain and resolve `${…id}` (incl. a non-default `id_field`) via the fake adapter; a failed
  create makes `ensure` raise; an ephemeral node returns its created record and `teardown` calls `delete`.
- **M3 — RestAdapter + ReferenceAdapter + bootstrap.** Auth schemes; pagination; scoped/composite keys.
  *Verify:* against a stub HTTP server — idempotent get-or-create, composite + scoped keys, reference-mode
  error when absent, header/bearer/session auth applied; `bootstrap(env)` builds adapters + clients from a
  manifest.
- **M4 — pytest plugin.** context + generated factories + generic step + teardown + `client_config`.
  *Verify:* the example project's pure-config spec passes; `pytest --fixtures` lists per-type factories; a
  reserved-name collision fails at load.
- **M5 — Discovery + runner + jobs.** *Verify:* discovery returns specs/tests/fixtures with resource links
  and **ignores non-type `the X "Y"` phrases**; a run yields results; a job streams queued→running→passed
  (assert on poll/JSONL output).
- **M6 — Cockpit.** deps + routers + templates + design system; five verticals, live-progress runs, ⌘K
  search, **security gating** (read-only for non-`mutable_envs`, localhost bind, confirms). *Verify:* drive
  each page headlessly against the example; seed/run/search work; a non-mutable env renders read-only; light
  and dark both render.
- **M7 — CLI + example + framework tests + CI.** `atf init/serve/seed/status/run`. *Verify:* all commands
  work on the example; framework unit tests green; lint/type clean; CI workflow runs it all.

Build strictly in order; do not start a milestone until the previous verifies.

---

## 20. Acceptance checklist (done = all true)

- [ ] The materializer contains **no** per-system branching — only registry dispatch of built adapters.
- [ ] Adapters register as **factories**; a new backend = one adapter + manifest config, no engine change.
- [ ] Every caller (plugin, cockpit, CLI) configures itself through the single `bootstrap`; the manifest is
      resolved one way.
- [ ] `ensure` **raises** with the offending node on a provisioning failure — no silent empty records.
- [ ] Ephemeral resources are created per run, returned from `ensure`, and **torn down** best-effort.
- [ ] Catalog validation rejects unknown types, dangling deps, cycles, duplicate names, unknown systems, and
      reserved-name collisions — all at load, listing every problem.
- [ ] The system-under-test client gets its base URL/auth from the manifest `clients` block, distinct from
      provisioning adapters.
- [ ] A new resource is a YAML node; a new spec is Gherkin reusing the generic step + vocabulary; a new
      behaviour is one `When`/`Then`. Tests and fixtures follow automatically.
- [ ] The cockpit answers "can I ship?" at a glance, runs tests with live per-test progress, **binds
      localhost, gates mutations by `mutable_envs`, and confirms destructive actions**.
- [ ] `id_field` is honoured wherever identity is read (placeholders, create, delete).
- [ ] `ruff` + strict `ty` pass with zero suppressions; framework unit tests need no network.
- [ ] The example builds to green from `atf run`, exercising REST, reference, and a custom ephemeral adapter
      with teardown.
- [ ] Nothing in `src/atf` names a specific product, domain, URL, or secret.

---

## Appendix A — `pyproject.toml`

```toml
[project]
name = "atf"
version = "0.1.0"
description = "Another Test Framework — declarative resources, pluggable adapters, specs, and a cockpit."
requires-python = ">=3.11"
dependencies = [
    "pyyaml",
    "httpx",
    "typing-extensions",
    "fastapi>=0.139",
    "uvicorn[standard]>=0.51",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",        # cockpit form posts (run-selected)
    "pytest>=8",
    "pytest-bdd>=8.1",
    "pytest-json-report>=1.5",
]

[project.scripts]
atf = "atf.cli:main"

[dependency-groups]
dev = ["ruff", "ty"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/atf"]

[tool.ruff]
target-version = "py311"
line-length = 120
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ty.src]
include = ["src/atf"]
[tool.ty.environment]
python-version = "3.11"
[tool.ty.terminal]
error-on-warning = true
[tool.ty.rules]
missing-override-decorator = "error"
possibly-unresolved-reference = "error"
```

> Note: `pytest`/`pytest-bdd` are runtime deps (not dev-only) because the framework *runs* the consumer's
> tests via subprocess and imports pytest in the discovery/runner/plugin.
