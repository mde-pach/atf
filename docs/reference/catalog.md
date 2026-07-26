# Catalog reference

The catalog is a directory of YAML files. `resources.yaml` declares resource **types**;
every other `*.yaml` file declares **instances**. Nothing in the catalog is executable.

## Directory layout

```
catalog/
  resources.yaml      the type registry
  accounts.yaml       instances; the file stem is the collection name
  projects.yaml
```

A node's id is `<file stem>.<key>`, so the key `alpha` in `projects.yaml` is `projects.alpha`.

## `resources.yaml`

Each top-level key is a type name. Four keys are interpreted by ATF; every other key is passed to
the type's adapter as `node["config"]`.

| Key | Type | Default | Description |
|---|---|---|---|
| `system` | string | — | **Required.** The adapter that handles this type. Must have a registered factory. |
| `mode` | `create` \| `reference` | `create` | `reference` types are found, never created. |
| `lifecycle` | `persistent` \| `ephemeral` | `persistent` | `ephemeral` resources are created for each run and deleted afterwards. |
| `id_field` | string | `id` | The record field carrying the resource's identity. |

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

A type name must not collide with a reserved pytest fixture name: `api`, `client_config`,
`context`, `env`, `materializer`, `request`, or a pytest built-in (`cache`, `capfd`, `capfdbinary`,
`caplog`, `capsys`, `capsysbinary`, `doctest_namespace`, `monkeypatch`, `pytestconfig`,
`record_property`, `record_testsuite_property`, `recwarn`, `tmp_path`, `tmp_path_factory`, `tmpdir`,
`tmpdir_factory`).

### `mode: reference` and `system: reference`

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

## Instance files

Each top-level key is an instance name.

| Key | Type | Default | Description |
|---|---|---|---|
| `resource` | string | — | **Required.** The type, as named in `resources.yaml`. |
| `represents` | string | `""` | Description of the instance. The only prose the catalog carries. |
| `depends_on` | list of node ids | `[]` | Resources provisioned before this one. |
| `body` | mapping | `{}` | The fields the resource is made of. Passed to the adapter after placeholder resolution. |

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

Instance names within one type must be unique across the whole catalog; the same name may be used by
different types.

## Placeholders

Placeholders appear anywhere in `body` — in strings, lists, or nested mappings — and are resolved
immediately before the adapter creates the resource.

| Form | Resolves to |
|---|---|
| `${<collection>.<name>.id}` | The identity of that node, read through *its* `id_field`. `.id` is a keyword meaning "identity", not a literal field name. |
| `${now+<N>d HH:MM}` | An ISO-8601 UTC timestamp `N` days from now at `HH:MM`, e.g. `2026-07-27T09:00:00Z`. |
| `${now-<N>d HH:MM}` | The same, `N` days in the past. |

These two forms are the whole vocabulary; anything else raises `Unresolved`. Collection and
instance names may contain only letters, digits, `_` and `-`, and the timestamp form requires
exactly `now±<N>d HH:MM` — `${now}`, `${now+1d}` and `${now+1h}` are all rejected.

A string consisting of exactly one placeholder takes the resolved value's type. A placeholder
embedded in surrounding text is interpolated as a string.

```yaml
    account_id: ${accounts.primary.id}          # the identity itself
    label: acct-${accounts.primary.id}-live     # a string
```

An unresolvable reference in a natural-key field makes the resource count as absent rather than
raising. During `create` it is reported as an `error` result that stops the pass; `ensure`
re-raises it as `ProvisioningError`.

## Validation

`load_catalog` reports every problem found, not the first. A catalog is rejected when:

- `resources.yaml` is missing;
- a type has no `system`, or an unrecognised `mode` or `lifecycle`;
- a type's `system` has no registered adapter factory;
- a type name collides with a reserved fixture name;
- an instance has no `resource`, or names a type absent from `resources.yaml`;
- a `depends_on` entry names a node that does not exist;
- a `${...}` placeholder names a node that does not exist, or one absent from `depends_on`;
- the dependency graph contains a cycle;
- two instances of the same type share a name;
- a file is not a mapping, or is invalid YAML.

Loading performs no network access.

## Node fields

The structure adapters receive. `system`, `mode`, `lifecycle`, `id_field` and `config` come from the
type; `represents`, `depends_on` and `body` from the instance.

| Field | Type | Description |
|---|---|---|
| `id` | string | `<collection>.<name>`. |
| `collection` | string | The file stem. |
| `name` | string | The instance key. |
| `resource` | string | The type name. |
| `system` | string | The adapter that handles it. |
| `mode` | string | `create` or `reference`. |
| `lifecycle` | string | `persistent` or `ephemeral`. |
| `id_field` | string | Field carrying the identity. |
| `config` | mapping | Type keys other than the four universal ones. |
| `represents` | string | The instance description. |
| `depends_on` | list | Node ids this resource requires. |
| `dependents` | list | Node ids requiring this resource. Computed. |
| `body` | mapping | The instance body, unresolved. |

## Type keys for the built-in adapters

Keys read from `node["config"]` by the `rest` and `reference` adapters.

| Key | Type | Default | Description |
|---|---|---|---|
| `path` | string | — | **Required.** Collection path, appended to `base_url`. Used for listing, creating and deleting. |
| `natural_key` | string or list | — | **Required.** Body field(s) identifying an existing record. |
| `list_path` | string | `path` | Alternative listing path. `{field}` placeholders are filled from the resolved body, e.g. `/accounts/{account_id}/projects`. |
| `list_filter` | string or list | — | Body fields sent as query parameters when listing. |
| `ref_field` | string | — | Remote field matched against the natural key. Applies to any type whose `natural_key` is a single field; ignored when it is a list. |
| `record_key` | string | — | Field of the create response holding the record, for APIs that wrap it in an envelope. |
| `delete_path` | string | `<path>/<identity>` | Alternative delete path. `{field}` placeholders are filled from the record. |
| `deletable` | boolean | `true` | When `false`, `delete` does nothing. |

Natural-key matching compares values as strings, falling back to comparing them as ISO-8601
instants when both parse as datetimes. Listings are cached for the duration of a materialize pass
and invalidated on every create. `DELETE` responses of 404, 405 and 501 are treated as success.

## See also

- [How to add a resource](../how-to/add-a-resource.md).
- [Manifest reference](manifest.md) — where `system` settings are declared.
- [About lifecycles](../explanation/lifecycles.md) — choosing `persistent` or `ephemeral`.
