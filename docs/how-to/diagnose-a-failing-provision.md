# How to diagnose a failing provision

A resource will not go green: `atf status` says `absent` when you expect `present`, a spec fails
before its first `When`, or the cockpit shows a red banner. Work from the message.

If you do not yet know that provisioning is the broken half, start with
[How to find out why an environment is red](find-out-why-an-environment-is-red.md) and come back
here.

## Start with status, not the test

```sh
atf status dev
```

This is the cheapest signal, and it never provisions anything. The status word tells you which
class of problem you have:

| Status | What it means | Where to look |
|---|---|---|
| `absent` | ATF looked and did not find it | your `natural_key`, or the resource genuinely does not exist |
| `error` | the adapter raised while looking | the message on the same line — see below |
| `unsupported` | no adapter is configured for that system **in this environment** | `environments.<env>.adapters` in the manifest |
| `ephemeral` | not looked up at all, by design | nothing is wrong |

## Match the message

These are the errors ATF emits, and what each actually means.

**`no adapter for system 'x' in env dev`**
The system has no entry under `environments.dev.adapters`. The adapter may well be registered — it
just has no settings for this environment. Add the block.

**`no adapter registered for system 'x' (registered: rest, reference)`**
A different failure with a similar shape: nothing called `register("x", …)`. Check that the module
defining it is listed under `adapters:` in the manifest, and that the `register` call runs at import
time rather than inside a function.

**`reference resource not found`**
A `mode: reference` resource is missing. ATF will not create it — that is the point. Either the
environment is not set up as the suite assumes, or the `natural_key` (or `ref_field`) does not match
what the backend calls it.

**`<node>: resource type 'x' needs a 'natural_key'`** / **`needs a 'path'`**
The type entry in `resources.yaml` is incomplete for the `rest` adapter.

**`POST /things: created, but no record carrying 'id' could be read back`**
The create succeeded but ATF cannot find the resulting record. Usually one of: the API answers `204`
with no body and the natural key does not round-trip; the response wraps the record in an envelope
(set `record_key`); or the identity is under a different field (set `id_field`).

**`unresolved placeholder ${accounts.primary.id}`**
The dependency has no identity yet. Since ATF validates placeholders at load, this at runtime means
the dependency itself failed to provision — look further up the output for the first failure.

**`no atf.yaml found in … or any parent directory`**
You are not inside the suite. `cd` into it, or set `ATF_MANIFEST`.

**`environment variable ATF_TOKEN is not set`**
A `*_env` pointer in the manifest has nothing behind it. This fails at startup, before anything is
touched.

## Provision one resource at a time

`atf seed` stops at the first failure, so narrow to the resource you care about and let ATF pull in
its dependencies:

```sh
atf seed dev --type project --name alpha
```

The output names each node and what happened to it — `created`, `exists`, `reference`, or the
failure. The last line before the failure tells you how far the chain got.

If you think the failures are independent rather than a single environment-wide problem, ask for
all of them at once:

```sh
atf seed dev --keep-going
```

Resources downstream of a failure are reported `blocked` and never attempted, so the output stays
free of cascade noise.

## See the HTTP traffic

The `rest` adapter raises with the status code and the first 200 characters of the body, which is
usually enough. When it is not, turn on httpx's logging:

```sh
ATF_ENV=dev python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
from atf.bootstrap import bootstrap
boot = bootstrap()
print(boot.materializer.status())
"
```

ATF's own engine logs under the `atf.materializer` logger — that is where teardown failures go,
since they are deliberately swallowed rather than raised.

## When the spec fails but the resource is fine

If `atf status` shows everything present and the spec still fails, the provisioning half is done and
the problem is in your vocabulary or your client. Run just that test with pytest's output:

```sh
uv run pytest specs/steps/test_accounts.py -k a_project_belongs -x -vv
```

`context` holds whatever the steps put there; print it in the failing step to see the record the
adapter actually returned.

## When it only fails the second time

A suite that passes once and fails on a re-run is almost always a scenario mutating a persistent
resource another scenario asserts on. Give the mutating scenario its own instance — see
[About lifecycles](../explanation/lifecycles.md#a-scenario-that-mutates-a-persistent-resource-must-own-it).

## When the catalog will not load at all

Every command exits `2` and prints every problem found, not just the first. That list is the whole
diagnosis — dangling dependencies, cycles, unknown types, duplicate names, placeholder typos and
reserved-name collisions all surface there before anything touches the network. The rules are listed
under [validation](../reference/catalog.md#validation).

## Where to go next

- [How to keep the catalog in step with an API change](keep-the-catalog-in-step.md) — when the
  answer is that the backend moved.
- [Life of a run](../explanation/life-of-a-run.md#find-or-create) — the step of the sequence these
  errors come from.
- [Catalog reference](../reference/catalog.md#type-keys-for-the-built-in-adapters) — the keys the
  messages above name.
- [Adapter SPI reference](../reference/adapter-spi.md) — when the failing adapter is your own.
