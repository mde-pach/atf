# 2. Point ATF at your own API

In [lesson 1](your-first-spec.md) you ran a suite against a stand-in. This lesson replaces it with a
real service, describes one of your own resources, and provisions it for real. It takes about ten
minutes.

You need the suite from lesson 1, and a JSON API you can reach — a local development server is
ideal. It needs one collection endpoint you can `GET` to list and `POST` to create. Anything you can
create and re-create safely will do.

Throughout, replace `https://dev.example.com` with your own URL and `/accounts` with your own path.

## Stop the stand-in

Open `conftest.py` at the root of your suite. Near the top is the block that starts the stand-in
API, wrapped in a condition — it runs only while nothing else has supplied a URL. Read it now; you
are about to make it stop.

Delete that block once you are pointing at a real service, or leave it in place: once the manifest
names your own URL it does nothing. Keeping it means the suite still runs for a colleague who has
not set anything up.

## Point the manifest at your service

Open `atf.yaml`. Two blocks name a URL, and they are separate on purpose:

```yaml
environments:
  dev:
    adapters:
      rest:
        base_url: https://dev.example.com    # how ATF creates the data
    clients:
      api:
        base_url: https://dev.example.com    # how your test talks to the service
```

`adapters` is ATF's own access, used to find and create resources. `clients` is your steps' access,
handed to your client fixture in `specs/api.py`. They usually point at the same place, and they are
different keys because they need not — see [About the model](../explanation/the-model.md).

Change both to your service's URL.

## Supply the credentials

ATF never stores a secret in a file. The manifest holds a *pointer*: any key ending in `_env` names
an environment variable, and the value is read from there at startup.

```yaml
        auth: { header: X-Actor, value_env: ATF_ACTOR }
```

Set whatever your manifest names before running anything:

```sh
export ATF_ACTOR=...
```

If your API uses a bearer token instead, say so:

```yaml
        auth: { bearer: { token_env: ATF_TOKEN } }
```

The [manifest reference](../reference/manifest.md#auth) lists the four schemes. An unset pointer
fails at startup, naming the variable, before anything is touched.

## Describe one of your resources

Open `catalog/resources.yaml` and replace the sample `account` type with something your API actually
serves:

```yaml
account:
  system: rest
  path: /accounts
  natural_key: email
```

Three keys, and only the last needs thought.

`path` is the collection endpoint, appended to `base_url`. ATF lists it to find things and posts to
it to create them.

`natural_key` is the field that tells ATF a resource **already exists**. Pick something stable and
unique that you can set on creation — an email, a slug, an external reference. Get this right and
the second run reuses what the first one made. Get it wrong and every run creates another copy.

If your API returns the new record's identity under something other than `id`, add
`id_field: uuid`, or whatever it calls it.

Now the instance, in `catalog/accounts.yaml`:

```yaml
primary:
  resource: account
  represents: The account most specs hang off.
  body:
    email: atf-primary@example.com
```

`body` is exactly what gets posted. Name the instance after what it *is* — `primary`, `expired`,
`trialling` — never `account_1`.

## Ask the environment what it has

```sh
atf status dev
```

```
  accounts.primary  absent

0/1 present in dev
```

This is the loop to stay in while you get a type right: it makes one read request and changes
nothing.

Three answers mean you have work to do first:

- **`unsupported`** — no adapter is configured for that system in this environment. Check the
  `adapters` block under your environment in `atf.yaml`.
- **`error`** — the adapter raised while looking. The message is on the same line; a wrong URL or a
  rejected credential looks like this.
- **`absent` when you know it exists** — the natural key is not matching. Check the field name is
  what the API returns, not just what it accepts.

[How to diagnose a failing provision](../how-to/diagnose-a-failing-provision.md) covers each of
these properly.

## Create it for real

```sh
atf seed dev --type account --name primary
```

```
  [  ok] accounts.primary                         created

1 created in dev.
```

Go and look in your API — the account is there. Now run exactly the same command again:

```sh
atf seed dev --type account --name primary
```

```
  [  ok] accounts.primary                         exists

1 already present in dev.
```

`exists`, not `created`. ATF listed the collection, matched your natural key, found what it
made a moment ago, and left it alone. That is what makes a suite safe to run over and over against
one environment — and it is why the natural key was the one key worth thinking about.

!!! note "`atf seed` needs permission"

    Seeding only works in environments listed under `mutable_envs` in the manifest. Anywhere else
    the command exits 2 and changes nothing. `dev` is on that list in the scaffolded manifest;
    production should never be.

## Point a scenario at it

Your existing scenario should now run against your service. Open `specs/api.py` — that is the client
your steps call, and it reads its URL and credentials from the `clients` block you edited:

```python
@pytest.fixture
def api(client_config):
    return Api(**client_config["api"])
```

Give it a method that calls your endpoint, then write the step that uses it in
`specs/steps/test_accounts.py`:

```python
@when("I fetch the account")
def _(context, api):
    context.result = api.get_account(context.account["id"])
```

`context.account` is the record your API returned when ATF created it — the real record, with its
real identity. ATF passes it through untouched; the field names are between you and your backend.

Then run it:

```sh
atf run
```

## Tidy up the scaffold

The starter suite came with a `project` type and an `alpha` instance that your API probably does not
serve. Delete `catalog/projects.yaml` and the `project` entry in `catalog/resources.yaml`, along
with any scenario naming them. The catalog will tell you if you miss a reference — a `depends_on` or
a `${...}` pointing at a node that no longer exists is a load error, not a silent one.

## What you have done

- Replaced the stand-in with a real service, for ATF and for your steps.
- Supplied credentials as pointers rather than literals.
- Described a resource your API actually serves, and chosen its natural key.
- Provisioned it twice and seen the second pass reuse the first pass's work.

## Where to go next

- **[3. Read your suite in the cockpit](read-your-suite-in-the-cockpit.md)** — the last lesson: see
  the whole suite, and what is red, in one place.
- [How to add a resource](../how-to/add-a-resource.md) — dependencies, placeholders, lifecycles.
- [How to add an adapter](../how-to/add-an-adapter.md) — when your backend is not a JSON API, or
  creating a thing takes more than one call.
- [Catalog reference](../reference/catalog.md#type-keys-for-the-built-in-adapters) — every key the
  `rest` adapter reads, including scoped listings and envelope responses.
