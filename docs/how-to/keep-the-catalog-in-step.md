# How to keep the catalog in step with an API change

The service moved: a field was renamed, an endpoint changed shape, identities are issued
differently. The catalog describes that service, so it has to move too.

This guide is the mapping from *what changed in the API* to *what to change in
`catalog/resources.yaml`*, and how to be sure you got it right.

## Recognise which kind of drift you have

| Symptom | Likely cause |
|---|---|
| `atf status` says `absent` for something you can see in the API | the [natural key](../reference/catalog.md#natural_key) no longer matches |
| Every run creates another copy | the same, and it is now costing you data |
| `error` with a 404 on the collection | the [`path`](../reference/catalog.md#path) moved |
| `created, but no record carrying 'id' could be read back` | identity or response shape changed |
| A dependent resource fails with `unresolved placeholder` | the dependency's [`id_field`](../reference/catalog.md#id_field) changed |
| Listing became slow, or times out | the collection outgrew a full listing |

Start with `atf status` in every case. It makes one read request per type and changes nothing:

```sh
atf status dev
```

## The API renamed the field you match on

If the field is still in the body under the new name, rename it in both places:

```yaml
account:
  system: rest
  path: /accounts
  natural_key: email_address     # was: email
```

```yaml
primary:
  resource: account
  body:
    email_address: primary@example.com
```

If the API **accepts** one name on create but **returns** another — a common asymmetry — keep the
body as the API wants it and tell ATF what to match against:

```yaml
  natural_key: email
  ref_field: emailAddress        # what the listing calls it
```

[`ref_field`](../reference/catalog.md#ref_field) applies only to a single-field natural key. With a
composite key, every field is matched under its own name, so both sides have to agree.

## The endpoint moved

```yaml
  path: /v2/accounts
```

`path` is used for listing, creating and deleting. If only listing moved — a nested route, say —
leave `path` alone and add a [`list_path`](../reference/catalog.md#list_path):

```yaml
  list_path: /organisations/{org_id}/accounts
```

`{field}` is filled from the resolved instance body, so `org_id` has to be a field of the body,
often a `${...}` reference to a dependency.

## Identity moved

If the API now returns the identity under a different key:

```yaml
  id_field: uuid
```

This has a blast radius. Every `${<this node>.id}` in the catalog resolves through the node's own
`id_field`, so the placeholders keep working untouched — but anything of yours that read
`context.account["id"]` in a step now needs `["uuid"]`. Grep for it.

## The response got wrapped

If create now answers `{"data": {...}}` instead of the record:

```yaml
  record_key: data
```

Without it, ATF cannot see the identity in the response, re-reads the collection to find the record,
and fails with advice pointing here if that lookup comes up empty.

## The collection got big

A full listing on every lookup stops being acceptable at some size. Push the filtering to the
backend:

```yaml
  list_filter: [account_id]      # sent as query parameters
```

or scope the path, as above. Both are described in the
[catalog reference](../reference/catalog.md#type-keys-for-the-built-in-adapters).

## Creation now needs a field it did not before

That is an instance change, not a type change — add it to each affected body:

```yaml
primary:
  resource: account
  body:
    email: primary@example.com
    region: eu-west-1
```

If the value has to differ per environment, it does not belong in the catalog. Either give each
environment its own instance, or make the field the adapter's business.

## Verify the fix

Three commands, in this order.

```sh
atf status dev
```

Everything you expect should read `present`. An `absent` here means the natural key still is not
matching.

```sh
atf seed dev --type account --name primary
atf seed dev --type account --name primary
```

Run it **twice**. The second pass must report `exists`, not `created`. If it reports `created` both
times, `find` is not recognising what `create` made, and you have a duplicate-generating catalog —
which is the expensive version of this bug.

```sh
atf run
```

Then the suite, to catch the steps that read renamed fields off the record.

## Clean up what the drift created

While the natural key was wrong, every run made another copy. Those are real records in a real
environment, and ATF will not remove them: it only deletes ephemeral resources it created within a
scenario.

Find them by the field you *used* to match on, and delete them with whatever tool owns that
environment. Do it before the next scheduled run, or the count keeps going up.

## Make the next change cheaper

- **Match on something the API owns and will not rename** — an external reference or a slug beats a
  display field.
- **One type per endpoint.** A type used for two endpoints has to drift twice.
- **Let CI tell you.** A nightly `atf status` against staging turns silent drift into a failed job;
  see [How to run ATF in CI](run-atf-in-ci.md).

## Where to go next

- [Catalog reference](../reference/catalog.md#type-keys-for-the-built-in-adapters) — every key the
  built-in adapters read.
- [How to diagnose a failing provision](diagnose-a-failing-provision.md) — when the message is not
  in the table above.
- [How to add an adapter](add-an-adapter.md) — when the change cannot be expressed as
  configuration.
