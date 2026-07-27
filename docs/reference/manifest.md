# Manifest reference

The manifest is a YAML file named `atf.yaml` at the root of a suite. It declares where the catalog
and specs live, which environments exist, and how each backend is reached.

Validation reports every problem in the file at once, not the first, and exits `2`.

## Resolution {#resolution}

ATF locates the manifest in this order:

1. The path in the [`ATF_MANIFEST`](cli.md#atf_manifest) environment variable. If that path does not
   exist, ATF raises `ConfigError`.
2. The nearest `atf.yaml` found by searching the current directory and each parent up to the
   filesystem root.

`atf.toml` is recognised by the search but not supported; loading one raises `ConfigError`.

The active environment is the `--env` option where the command accepts one, otherwise the
[`ATF_ENV`](cli.md#atf_env) environment variable, otherwise [`default_env`](#default_env).

## Top-level keys {#top-level-keys}

### `catalog` {#catalog}

Path, default `./catalog`. The directory holding `resources.yaml` and the instance files, relative
to the manifest. See the [catalog reference](catalog.md).

### `specs` {#specs}

Path, default `./specs`. The directory holding `.feature` files and step modules, relative to the
manifest. It is also what [`atf run`](cli.md#atf-run) runs when given no paths.

### `default_env` {#default_env}

**Required**, string. The environment used when neither `--env` nor `ATF_ENV` is set. It must be a
key of [`environments`](#environments).

### `adapters` {#adapters}

List of strings, default `[]`. Dotted module paths imported at startup for their `register()` side
effects. A single module may be given as a bare string.

A module that resolves to a file inside the suite is loaded from that path directly, so the suite
never has to go on `sys.path` — where a file named `types.py` or `json.py` would shadow the standard
library for the rest of the process. Only a module that is *not* found in the suite is imported
normally, with the manifest's directory appended to `sys.path` first.

```yaml
adapters:
  - adapters             # ./adapters.py in the suite
  - my_package.queues    # an installed package
```

### `mutable_envs` {#mutable_envs}

List of strings, default `[]`. The environments in which ATF may create, provision or run. Every
entry must be a key of [`environments`](#environments).

This is the single gate on everything that changes an environment:

- [`atf seed`](cli.md#atf-seed) exits `2` in an environment absent from the list, and changes
  nothing;
- the cockpit renders its Provision and Run controls disabled there, and the routes return **409**.

Leaving production off this list makes the protection structural rather than a matter of
discipline. Nothing read-only is gated: [`atf status`](cli.md#atf-status) and every cockpit page
work in any environment.

### `environments` {#environments}

**Required**, mapping. Per-environment settings, keyed by environment name. See
[per-environment settings](#environments-name).

### `display` {#display}

Mapping, default `{}`. Cockpit cosmetics — labels and colours for your systems. See
[cockpit display](#display-settings).

## Per-environment settings {#environments-name}

```yaml
environments:
  dev:
    adapters:
      rest:
        base_url: https://dev.example.com
        auth: { header: X-Actor, value_env: ATF_ACTOR }
    clients:
      api:
        base_url: https://dev.example.com
```

### `adapters.<system>` {#env-adapters}

Mapping of system name to settings. Each entry is passed verbatim to the factory registered for that
system, with [`*_env` pointers](#environment-variable-pointers) already resolved.

A system with no entry here has **no adapter in this environment**. Its resources report status
`unsupported`, and provisioning one fails with the same word. That is how one manifest describes an
environment where only some of your systems exist.

### `providers.<name>` {#env-providers}

Settings for one [provider](providers.md), the named source behind a `${...}` that is not a node
reference. Interpreted by the provider, not by ATF.

```yaml
environments:
  dev:
    providers:
      fake:
        locale: en_GB
```

A provider with no settings needs no entry here — `now`, `uuid` and `env` work everywhere.

### `clients.<name>` {#env-clients}

Mapping of client name to settings, exposed to specs through the
[`client_config`](specs-and-fixtures.md#client_config) fixture. ATF does not interpret the contents.

This is deliberately separate from `adapters`: one is how ATF provisions data, the other is how your
tests talk to the system under test. They usually point at the same place, and they need not.

## Environment-variable pointers {#environment-variable-pointers}

Any key ending in `_env` whose value is a string is replaced, at startup, by the key without that
suffix and the value of the named environment variable. Substitution is recursive through nested
mappings and lists.

```yaml
auth: { bearer: { token_env: ATF_TOKEN } }    # becomes { bearer: { token: <$ATF_TOKEN> } }
```

Secrets therefore never appear as literals in a manifest, and the manifest is safe to commit. An
unset variable raises `ConfigError` naming both the key that wants it and the variable, before
anything is touched.

## Built-in adapter settings {#built-in-adapter-settings}

Settings for the systems `rest` and `reference`, given under
[`environments.<name>.adapters`](#env-adapters). `reference` accepts the same keys as `rest`.

### `base_url` {#base_url}

**Required**, string. The root URL for the API. A trailing slash is stripped, and redirects are
followed.

### `auth` {#auth}

Mapping, default none. The authentication scheme. Four are recognised; anything else raises
`AuthError`.

#### `none` {#auth-none}

No authentication. The same as omitting `auth`.

#### `header` {#auth-header}

Sends a fixed header with every request.

```yaml
auth: { header: X-Actor, value_env: ATF_ACTOR }
```

`header` names the header, `value` carries it — normally as `value_env`. A missing value is an
error.

#### `bearer` {#auth-bearer}

Sends `Authorization: Bearer <token>`.

```yaml
auth: { bearer: { token_env: ATF_TOKEN } }
```

A literal string is accepted in place of the mapping.

#### `session` {#auth-session}

Posts credentials once, on the first request, then reuses the resulting cookie or token for the life
of the client.

| Key | Default | Description |
|---|---|---|
| `login_path` | `/login` | Path posted to, resolved against `base_url`. |
| `username`, `password` | — | Credentials, normally supplied as `username_env` and `password_env`. |
| `username_field`, `password_field` | `username`, `password` | Field names in the login payload. |
| `form` | `false` | Send the payload as form data rather than JSON. |
| `token_key` | — | Response field holding the token. When unset, ATF tries `token`, `access_token`, `session_token`, `key`, `jwt`. |
| `token_header` | `Authorization` | Header the token is sent in. |
| `token_format` | `Bearer {token}` | Format applied to the token. |

Login is not repeated. A login response of 400 or above, or one carrying neither a cookie nor a
recognised token, raises `AuthError`.

### `pagination` {#pagination}

Mapping, default none. Offset-pagination settings. **When absent, list endpoints must return a bare
JSON array**; when present, ATF pages through them.

| Key | Default | Description |
|---|---|---|
| `results_key` | `results` | Response field holding the page of records. |
| `count_key` | `count` | Response field holding the total. Paging stops when the number fetched reaches it. |
| `limit_param` | `limit` | Query parameter carrying the page size. |
| `offset_param` | `offset` | Query parameter carrying the offset. |
| `page_size` | `100` | Records requested per page. |
| `max_pages` | `1000` | Safety limit. Exceeding it raises, suggesting the backend is ignoring the offset. |

A short page also ends the paging, so a backend with no `count_key` still terminates.

### `timeout` {#timeout}

Number, default `30`. Per-request timeout in seconds.

### `retries` {#retries}

Integer, default `0`. Retries for transport errors and 5xx responses, with exponential backoff.

**Only idempotent methods are retried** — `GET`, `HEAD`, `PUT`, `DELETE`, `OPTIONS`. A `POST` is
never retried, because a backend that created the record and *then* failed would be sent a
duplicate, which is exactly what get-or-create must never do.

### `verify` {#verify}

Boolean, default `true`. TLS certificate verification.

### `success_codes` {#success_codes}

List of integers, default `[200, 201, 202, 204]`. The status codes `create` accepts.

### `headers` {#headers}

Mapping, default `{}`. Additional headers sent with every request. Merged over the auth scheme's own
headers.

## Cockpit display {#display-settings}

| Key | Type | Default | Description |
|---|---|---|---|
| `systems.<system>.label` | string | the system name, title-cased | Name shown for that system in the cockpit. |
| `systems.<system>.color` | string | derived from the system name | CSS colour used for that system's badges. |

Systems absent from `display` are given a generated label and colour, so this key is never required.

```yaml
display:
  systems:
    rest:  { label: API, color: "#2f6be0" }
    queue: { label: Queue, color: "#7857d8" }
```

## Complete example {#complete-example}

```yaml
catalog: ./catalog
specs: ./specs
default_env: dev

adapters:
  - my_suite.adapters

mutable_envs: [dev, staging]

environments:
  dev:
    adapters:
      rest:
        base_url: https://dev.example.com
        auth: { header: X-Actor, value_env: ATF_ACTOR }
        pagination: { results_key: results, count_key: count }
        timeout: 30
      queue:
        broker_url: amqp://localhost
        token_env: QUEUE_TOKEN
    clients:
      api:
        base_url: https://dev.example.com
        auth: { header: X-Actor, value_env: ATF_ACTOR }
  production:
    adapters:
      rest:
        base_url: https://example.com
        auth: { bearer: { token_env: ATF_TOKEN } }
    clients:
      api:
        base_url: https://example.com

display:
  systems:
    rest:  { label: API, color: "#2f6be0" }
    queue: { label: Queue, color: "#7857d8" }
```

`production` is absent from [`mutable_envs`](#mutable_envs): the cockpit renders its mutating
controls disabled and its mutation routes return 409, and `atf seed production` exits 2.

## Where to go next

- [Catalog reference](catalog.md) — the files `catalog` points at.
- [CLI reference](cli.md) — the commands that read this file.
- [How to run ATF in CI](../how-to/run-atf-in-ci.md) — supplying the `*_env` pointers on a build
  machine.
- [How to add an adapter](../how-to/add-an-adapter.md) — adding a system of your own to
  `environments.<name>.adapters`.
