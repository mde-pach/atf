# Manifest reference

The manifest is a YAML file named `atf.yaml` at the root of a suite. It declares where the catalog
and specs live, which environments exist, and how each backend is reached.

## Resolution

ATF locates the manifest in this order:

1. The path in the `ATF_MANIFEST` environment variable. If that path does not exist, ATF raises
   `ConfigError`.
2. The nearest `atf.yaml` found by searching the current directory and each parent up to the
   filesystem root.

`atf.toml` is recognised by the search but not supported; loading one raises `ConfigError`.

The active environment is the `--env` option where the command accepts one, otherwise the `ATF_ENV`
environment variable, otherwise `default_env`.

## Top-level keys

| Key | Type | Default | Description |
|---|---|---|---|
| `catalog` | path | `./catalog` | Directory holding `resources.yaml` and the instance files. Relative to the manifest. |
| `specs` | path | `./specs` | Directory holding `.feature` files and step modules. Relative to the manifest. |
| `default_env` | string | — | **Required.** Environment used when neither `--env` nor `ATF_ENV` is set. Must be a key of `environments`. |
| `adapters` | list of strings | `[]` | Dotted module paths imported at startup for their `register()` side effects. The manifest's directory is added to `sys.path` first. |
| `mutable_envs` | list of strings | `[]` | Environments in which ATF may create, seed or run. Every entry must be a key of `environments`. |
| `environments` | mapping | — | **Required.** Per-environment settings. See below. |
| `display` | mapping | `{}` | Cockpit cosmetics. See below. |

Validation reports every problem in the file at once, not the first.

## `environments.<name>`

| Key | Type | Description |
|---|---|---|
| `adapters` | mapping | `system -> settings`. Each entry is passed verbatim to the factory registered for that system. |
| `clients` | mapping | `name -> settings`. Exposed to specs through the `client_config` fixture; ATF does not interpret the contents. |

A system with no entry under `adapters` has no adapter in that environment. Its resources report
status `unsupported`; provisioning one fails with the same word.

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

## Environment-variable pointers

Any key ending in `_env` whose value is a string is replaced, at startup, by the key without that
suffix and the value of the named environment variable. Substitution is recursive through nested
mappings and lists.

```yaml
auth: { bearer: { token_env: ATF_TOKEN } }    # becomes { bearer: { token: <$ATF_TOKEN> } }
```

An unset variable raises `ConfigError` naming the key and the variable.

## `display`

| Key | Type | Default | Description |
|---|---|---|---|
| `systems.<system>.label` | string | the system name, title-cased | Name shown for that system in the cockpit. |
| `systems.<system>.color` | string | derived from the system name | CSS colour used for that system's badges. |

Systems absent from `display` are given a generated label and colour.

## Built-in adapter settings

Settings for the systems `rest` and `reference`, given under `environments.<name>.adapters`.
`reference` accepts the same keys as `rest`.

| Key | Type | Default | Description |
|---|---|---|---|
| `base_url` | string | — | **Required.** Root URL for the API. A trailing slash is stripped. |
| `auth` | mapping | none | Authentication scheme. See below. |
| `pagination` | mapping | none | Offset-pagination settings. When absent, list endpoints must return a bare JSON array. |
| `timeout` | number | `30` | Per-request timeout in seconds. |
| `retries` | integer | `0` | Retries for transport errors and 5xx responses, with exponential backoff. |
| `verify` | boolean | `true` | TLS certificate verification. |
| `success_codes` | list of integers | `[200, 201, 202, 204]` | Status codes `create` accepts. |
| `headers` | mapping | `{}` | Additional headers sent with every request. |

### `auth`

| Scheme | Keys | Effect |
|---|---|---|
| `none` | — | No authentication. Also the effect of omitting `auth`. |
| `header` | `header`, `value` (usually `value_env`) | Sends the given header with every request. |
| `bearer` | `token` (usually `token_env`) | Sends `Authorization: Bearer <token>`. Accepts a literal string instead of a mapping. |
| `session` | see below | Posts credentials once, then reuses the resulting cookie or token. |

`session` keys:

| Key | Default | Description |
|---|---|---|
| `login_path` | `/login` | Path posted to, resolved against `base_url`. |
| `username`, `password` | — | Credentials, normally supplied as `username_env` and `password_env`. |
| `username_field`, `password_field` | `username`, `password` | Field names in the login payload. |
| `form` | `false` | Sends the payload as form data rather than JSON. |
| `token_key` | — | Response field holding the token. When unset, ATF tries `token`, `access_token`, `session_token`, `key`, `jwt`. |
| `token_header` | `Authorization` | Header the token is sent in. |
| `token_format` | `Bearer {token}` | Format applied to the token. |

Login occurs on the first request and is not repeated. A login response of 400 or above, or one
carrying neither a cookie nor a recognised token, raises `AuthError`.

### `pagination`

| Key | Default | Description |
|---|---|---|
| `results_key` | `results` | Response field holding the page of records. |
| `count_key` | `count` | Response field holding the total. Paging stops when the number fetched reaches it. |
| `limit_param` | `limit` | Query parameter carrying the page size. |
| `offset_param` | `offset` | Query parameter carrying the offset. |
| `page_size` | `100` | Records requested per page. |

## Complete example

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

`production` is absent from `mutable_envs`: the cockpit renders its mutating controls disabled and
its mutation routes return 409, and `atf seed production` exits 2.

## See also

- [Catalog reference](catalog.md) — the files `catalog` points at.
- [CLI reference](cli.md) — the commands that read this file.
- [How to run ATF in CI](../how-to/run-atf-in-ci.md).
