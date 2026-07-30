# How to adopt ATF in an existing suite

Add ATF to a repository that already has pytest tests, without rewriting them.

ATF does not replace your test suite. It adds a catalog, a provisioning step, and a set of fixtures;
your existing tests keep running untouched.

## Enable the plugin

ATF's plugin must be enabled from the **root** `conftest.py` — pytest only honours
`pytest_plugins` there:

```python
# conftest.py at the repository root
pytest_plugins = ["atf.spec.plugin"]
```

If that file already exists, add the line; if `pytest_plugins` is already defined, append to it.

Be aware of what this costs: **the plugin bootstraps at import time.** It resolves the manifest,
reads every `*_env` pointer, and loads the catalog while pytest is collecting. A missing environment
variable or a catalog typo therefore breaks collection of your *whole* suite, not just the ATF
tests. Treat the manifest as something CI must always be able to satisfy.

If you would rather contain that, put ATF's specs in their own directory with their own
`conftest.py` and run them as a separate pytest invocation.

## Add the manifest and catalog

```sh
atf init .
```

`atf init` never overwrites, so it fills in only what is missing. Delete the parts you do not want —
the sample feature and steps are illustrative.

Point `atf.yaml` at where you want things:

```yaml
catalog: ./tests/catalog
specs: ./tests/e2e
```

Both paths are relative to the manifest.

## Keep your existing tests running

If `testpaths` in your pytest config points at a directory, add the specs directory to it:

```ini
[pytest]
testpaths = tests tests/e2e
```

ATF's specs are ordinary pytest items. They can live beside your unit tests, share fixtures with
them, and be selected with `-k` and markers as usual.

## Expose your API client to the specs

If you already have a client fixture, ATF's specs can use it as-is — nothing special is required,
as long as pytest can see it (a `conftest.py` at or above the specs directory).

If you want it configured per environment, read its settings from the manifest instead of hard-coding
them:

```python
@pytest.fixture
def api(client_config):
    return MyClient(**client_config["api"])
```

with the matching block under `environments.<env>.clients.api`. The `client_config` fixture is
ATF's; `api` stays yours.

## Model your first resource

Do not port the whole fixture set. Pick one thing many tests need — an account, a tenant, a
customer — and declare it:

```yaml
# catalog/resources.yaml
account:
  system: rest
  path: /accounts
  natural_key: email
```

```yaml
# catalog/accounts.yaml
primary:
  resource: account
  represents: The account most specs hang off.
  body:
    email: primary@example.com
```

Check it before writing a spec:

```sh
atf status dev
atf seed dev --type account --name primary
```

Then convert one test to a scenario and leave the rest alone. Adopting one resource at a time keeps
the suite green throughout.

## Reuse an existing setup helper as an adapter

If provisioning already exists in Python — a factory, a helper, an SDK call — wrap it rather than
rewriting it:

```python
from atf.adapters import register


class AccountAdapter:
    def find(self, node, ctx):
        return existing_helpers.find_account(node.body["email"])

    def create(self, node, body, ctx):
        return existing_helpers.create_account(**body)

    def delete(self, node, record, ctx):
        existing_helpers.delete_account(record["id"])


register("legacy", AccountAdapter)
```

The catalog now describes what exists; your helper still knows how to make it. See
[How to add an adapter](add-an-adapter.md).

## Check the names you already use

Catalog validation rejects a resource type whose name collides with a fixture name ATF or pytest
reserves. In an existing suite this is worth checking before you commit to a vocabulary: see
[reserved type names](../reference/catalog.md#reserved-names). If a domain word collides, rename the
type — the instance names are free.

## Verify

```sh
uv run pytest -q       # your existing suite, unchanged
atf run                # just the specs, against the default environment
atf status dev         # what the catalog says exists
```

If collection now fails and it did not before, the cause is almost always the import-time bootstrap:
run `atf status dev` on its own to see the manifest or catalog error in isolation.

## Where to go next

- [How to add a resource](add-a-resource.md) — the second resource, and the tenth.
- [How to add a scenario](add-a-scenario.md) — converting a test into a spec.
- [How to run ATF in CI](run-atf-in-ci.md) — making the new suite a gate.
- [Specs and fixtures reference](../reference/specs-and-fixtures.md) — what the plugin adds to a
  suite that already has fixtures.
