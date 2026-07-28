# Catalog reference

The catalog is a directory of YAML files. `resources.yaml` declares resource **types**; every other
`*.yaml` file declares **instances**. Nothing in the catalog is executable, and loading it performs
no network access.

## Directory layout {#directory-layout}

```
catalog/
  resources.yaml      the type registry
  accounts.yaml       instances; the file stem is the collection name
  projects.yaml
```

A node's id is `<file stem>.<key>`, so the key `alpha` in `projects.yaml` is `projects.alpha`.

The [collection](../explanation/glossary.md#collection) decides node ids and nothing else. A type
may have instances in several files, and one file may hold instances of several types.

## Resource types {#resource-types}

Each top-level key of `resources.yaml` is a type name. Four keys are interpreted by ATF; **every
other key is passed to the type's adapter** as `node["config"]`.

```yaml
account:
  system: rest
  path: /accounts
  natural_key: email

job_run:
  system: rest
  path: /runs
  natural_key: token
  id_field: uuid
```

### `system` {#system}

**Required**, string. The [system](../explanation/glossary.md#system) this type lives in, and
therefore which adapter handles it. It must have a registered adapter factory, or the catalog
refuses to load and lists the systems that do.

Settings for a system are per environment, under
[`environments.<name>.adapters`](manifest.md#environments-name).

### `mode` {#mode}

`create` (default), `reference`, or `data` — what ATF is being asked to *do* about the resource.

| `mode` | Means | Absent means |
|---|---|---|
| `create` | ATF makes it exist. | it will be created |
| `reference` | a precondition ATF cannot create. | **blocks** — the environment is not configured the way the suite assumes |
| `data` | an observation: something to look at and claim things about. | nothing. It is simply not there yet |

A **`reference`** type is looked up and never created, and an absent one is a failure worth stopping
for. See [`mode: reference` and `system: reference`](#reference-mode-vs-system) for the distinction
from the built-in adapter of the same name.

A **`data`** type is also never created, and that is the only thing the two share. An observation is
not a precondition: a page a scenario reads, or a record the system under test is expected to have
left behind, is something to make a claim *about*, and "it is not there" is frequently the claim.
So `data` never blocks, never appears in [`atf seed`](cli.md#atf-seed) — there is nothing to seed —
and never makes an environment un-ready. It still reports `present` / `absent` in
[`atf status`](cli.md#atf-status), because that is the observation.

```yaml
# The list the system under test is supposed to create. This suite watches for it; it never makes it.
todo_list:
  system: rest
  mode: data
  path: /lists
  natural_key: [owner_id, slug]
```

Reach for `reference` when the suite cannot run without it, and `data` when the suite is there to
find out.

### `lifecycle` {#lifecycle}

`persistent` (default) or `ephemeral`.

A [persistent](../explanation/glossary.md#persistent) resource is found-or-created and left in
place. An [ephemeral](../explanation/glossary.md#ephemeral) one is never looked up, is created
fresh on each pass, and is deleted when the scenario that provisioned it ends.

Which to choose is a design decision, not a lookup: see
[About lifecycles](../explanation/lifecycles.md).

### `id_field` {#id_field}

String, default `id`. The record field carrying the resource's
[identity](../explanation/glossary.md#id-field).

It is what `${<node>.id}` resolves to, what `delete` uses to address the resource, and what a
`create` response must carry for ATF to accept it.

### Reserved type names {#reserved-names}

A type name becomes a pytest fixture name, so it may not collide with one already taken. The catalog
refuses to load and names the offender.

| Source | Names |
|---|---|
| ATF's own fixtures | `api`, `client_config`, `context`, `env`, `materializer` |
| pytest built-ins | `cache`, `capfd`, `capfdbinary`, `caplog`, `capsys`, `capsysbinary`, `doctest_namespace`, `monkeypatch`, `pytestconfig`, `record_property`, `record_testsuite_property`, `recwarn`, `request`, `tmp_path`, `tmp_path_factory`, `tmpdir`, `tmpdir_factory` |

Separately, generated factories land in the `atf.plugin` module's namespace, so a type whose name
matches something that module already defines raises at import time with the same advice: rename the
type. Instance names are unconstrained.

### `mode: reference` and `system: reference` {#reference-mode-vs-system}

Two different mechanisms share the word.

- **`mode: reference`** is an engine rule: ATF looks the resource up and never creates it. It
  applies whatever adapter handles the type.
- **`system: reference`** selects the built-in `ReferenceAdapter` — a `rest` adapter whose `create`
  raises. It is find-only for JSON APIs specifically.

A find-only REST resource normally wants both, as `examples/todo` does:

```yaml
label:
  system: reference       # the find-only adapter
  mode: reference         # and the engine rule that it is never created
  path: /labels
  natural_key: name
```

Setting `system: reference` alone leaves `mode` at its default `create`, so provisioning raises
`ValueError` from the adapter instead of reporting the resource missing.

## Instance files {#instance-files}

Each top-level key of an instance file is an instance name.

```yaml
alpha:
  resource: project
  represents: A project under the primary account.
  depends_on:
    - accounts.primary
  body:
    slug: alpha
    account_id: ${accounts.primary.id}
```

Instance names within one type must be unique across the whole catalog; different types may reuse a
name.

### `resource` {#resource}

**Required**, string. The type, as named in `resources.yaml`. A name that is not in the registry is
a load error.

### `represents` {#represents}

String, default `""`. A description of this instance, and the only prose the catalog carries. It is
what the cockpit shows and what the next person reads.

Describe what the resource is *for*, not what it contains — the body already says that.

### `depends_on` {#depends_on}

List of node ids, default `[]`. Resources provisioned before this one, in
[dependency-first order](../explanation/life-of-a-run.md#topological-sort).

A single id may be given as a bare string. Every entry must name a real node, and the graph must be
acyclic; both are checked at load.

A `${...}` reference to a node that is not also in `depends_on` is rejected, because it would
otherwise be resolved before the thing it names had been provisioned.

### `body` {#body}

Mapping, default `{}`. The fields the resource is made of, passed to the adapter after
[placeholder](#placeholders) resolution. ATF does not interpret its contents beyond resolving
placeholders and reading the [`natural_key`](#natural_key) fields out of it.

## Placeholders {#placeholders}

Placeholders appear anywhere in `body` — in strings, lists, or nested mappings — and are resolved
immediately before the adapter creates the resource. One form is the framework's own; everything
else is a call to a [provider](providers.md).

### `${<collection>.<name>.id}` {#placeholder-id}

The identity of that node, read through *its* [`id_field`](#id_field). `.id` is a keyword meaning
"identity", not a literal field name.

Collection and instance names may contain only letters, digits, `_` and `-`.

```yaml
    account_id: ${accounts.primary.id}
```

### `${<provider>:<argument>}` {#placeholder-provider}

Anything that is not a node reference is a [provider](providers.md) call — a named source of
values, registered the way an adapter is.

```yaml
    due_at: ${now+30d 09:00}     # an ISO-8601 UTC timestamp 30 days from now, at 09:00
    token: ${uuid}
    nickname: ${fake:first_name}
```

`${now±<N>d HH:MM}` is exact: `${now}`, `${now+1d}` and `${now+1h}` are all rejected. Use it rather
than a fixed date, so the data does not rot.

A node reference always wins over a provider name, so a registered name cannot shadow a collection.

**A generated value in a natural key is refused when the catalog loads.** A value that changes
every run never matches what is already out there, so every run would create another record — see
[where a generated value may go](providers.md#where).

### Typing and interpolation {#placeholder-typing}

A string consisting of exactly one placeholder takes the resolved value's type. A placeholder
embedded in surrounding text is interpolated as a string.

```yaml
    account_id: ${accounts.primary.id}          # the identity itself, with its own type
    label: acct-${accounts.primary.id}-live     # a string
```

### When a placeholder cannot be resolved {#unresolved}

An unresolvable reference in a natural-key field makes the resource count as **absent** rather than
raising — ATF cannot look for something whose key it does not know yet.

During a create it is reported as an `error` result that stops the pass; `Materializer.ensure`
re-raises it as `ProvisioningError`. Because references are validated at load, an `Unresolved` at
run time almost always means the dependency itself failed to provision — look further up the output.

## Type keys for the built-in adapters {#type-keys-for-the-built-in-adapters}

Keys read from `node["config"]` by the `rest` and `reference` adapters. A custom adapter reads
whatever keys it likes from the same place.

### `path` {#path}

**Required**, string. The collection path, appended to `base_url`. Used for listing, creating and
deleting.

### `natural_key` {#natural_key}

**Required**, string or list of strings. The body field(s) identifying an existing record.

This is what makes provisioning idempotent: ATF lists the collection and matches on these fields, so
a second pass recognises what the first one created. Choose something stable, unique, and settable
at creation time.

```yaml
natural_key: email                  # one field
natural_key: [account_id, slug]     # composite
```

A natural-key field absent from the body, or holding an unresolvable placeholder, makes the resource
count as absent.

### `list_path` {#list_path}

String, default [`path`](#path). An alternative listing path, for when listing the whole collection
is too expensive. `{field}` placeholders are filled from the resolved body:

```yaml
list_path: /accounts/{account_id}/projects
```

A field named in the template but missing from the body is an error naming the field.

### `list_filter` {#list_filter}

String or list of strings. Body fields sent as query parameters when listing, for backends that
filter server-side:

```yaml
list_filter: [account_id]
```

A field whose value cannot be resolved yet is omitted from the query rather than failing.

### `ref_field` {#ref_field}

String. The remote field matched against the natural key, when the backend calls it something other
than the body does.

Applies only to a type whose `natural_key` is a **single** field; it is ignored for a composite key,
where each field is matched under its own name.

### `record_key` {#record_key}

String. The field of the create response holding the record, for APIs that wrap it in an envelope:

```yaml
record_key: data
```

### `delete_path` {#delete_path}

String, default `<path>/<identity>`. An alternative delete path. `{field}` placeholders are filled
from the **record**, not the body.

### `deletable` {#deletable}

Boolean, default `true`. When `false`, `delete` does nothing — for backends with no deletion
endpoint. Only ephemeral resources are ever deleted, so this matters only for them.

### Matching and request rules {#matching-rules}

- Natural-key matching compares values as strings, falling back to comparing them as ISO-8601
  instants when both parse as datetimes.
- Listings are cached for the duration of one provisioning pass, and invalidated on every create.
- A `create` response carrying no identity triggers a re-read; if that finds nothing, the error
  suggests [`record_key`](#record_key) and [`id_field`](#id_field).
- `DELETE` responses of 404, 405 and 501 are treated as success.

## Validation {#validation}

Loading the catalog reports **every** problem found, not the first. A catalog is rejected when:

- `resources.yaml` is missing;
- a type has no `system`, or an unrecognised `mode` or `lifecycle`;
- a type's `system` has no registered adapter factory;
- a type name collides with a [reserved name](#reserved-names);
- an instance has no `resource`, or names a type absent from `resources.yaml`;
- a `depends_on` entry names a node that does not exist;
- a `${...}` placeholder names a node that does not exist, or one absent from `depends_on`;
- the dependency graph contains a cycle;
- two instances of the same type share a name;
- a file is not a mapping, or is invalid YAML.

Every command exits `2` on a rejected catalog, and that list of problems is the whole diagnosis.

## Node fields {#node-fields}

The structure adapters receive. `system`, `mode`, `lifecycle`, `id_field` and `config` come from the
type; `represents`, `depends_on` and `body` from the instance.

| Field | Type | Description |
|---|---|---|
| `id` | string | `<collection>.<name>`. |
| `collection` | string | The file stem. |
| `name` | string | The instance key. |
| `resource` | string | The type name. |
| `system` | string | The adapter that handles it. |
| `mode` | string | `create`, `reference` or `data`. |
| `lifecycle` | string | `persistent` or `ephemeral`. |
| `id_field` | string | Field carrying the identity. |
| `config` | mapping | Type keys other than the four universal ones. |
| `represents` | string | The instance description. |
| `depends_on` | list | Node ids this resource requires. |
| `dependents` | list | Node ids requiring this resource. Computed. |
| `body` | mapping | The instance body, **unresolved**. |

## Where to go next

- [How to add a resource](../how-to/add-a-resource.md) — these keys in the order you meet them.
- [How to keep the catalog in step with an API change](../how-to/keep-the-catalog-in-step.md) — when
  the backend moves underneath them.
- [Manifest reference](manifest.md) — where a system's settings are declared.
- [About lifecycles](../explanation/lifecycles.md) — choosing `persistent` or `ephemeral`.
