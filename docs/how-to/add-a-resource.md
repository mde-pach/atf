# How to add a resource

Add a new entity that your specs can depend on — a customer, a subscription, a feed, whatever your
system is made of.

You add resources in two places: the **type** (declared once, in `catalog/resources.yaml`) and the
**instance** (one per thing you want to exist). If a type for what you are adding already exists,
skip to [Declare the instance](#declare-the-instance).

## Declare the type

Add an entry to `catalog/resources.yaml`. It needs a `system` — which adapter handles it — plus
whatever that adapter requires. For the built-in `rest` adapter, that is a `path` and a
`natural_key`:

```yaml
subscription:
  system: rest
  path: /subscriptions
  natural_key: reference
```

The `natural_key` is how ATF recognises an instance that already exists. Choose a field that is
stable and unique — an email, a slug, an external reference.

If no single field identifies the resource, use several:

```yaml
subscription:
  system: rest
  path: /subscriptions
  natural_key: [account_id, plan]
```

If the API returns the identity under something other than `id`, say so:

```yaml
  id_field: uuid
```

If the collection is large, point lookups at a scoped or filtered endpoint so ATF does not list
everything:

```yaml
  list_path: /accounts/{account_id}/subscriptions   # fields come from the instance body
  list_filter: [account_id]                         # or send them as query parameters
```

For the full set of keys, see the [catalog reference](../reference/catalog.md).

## Declare the instance

Add a file under `catalog/` named after the collection, or add to an existing one. The file stem
becomes the first half of the resource id, so `catalog/subscriptions.yaml` gives you
`subscriptions.<name>`:

```yaml
monthly:
  resource: subscription
  represents: A live monthly subscription on the primary account.
  body:
    reference: SUB-MONTHLY
    plan: monthly
```

Name instances after what they *are*, not what number they are: `monthly`, `expired`, `trialling` —
never `subscription_1`.

`represents:` is the one place to describe the resource. It is what the cockpit shows and what the
next person reads, so write it for them.

## Depend on another resource

If your resource cannot exist until something else does, declare it and reference its identity:

```yaml
monthly:
  resource: subscription
  represents: A live monthly subscription on the primary account.
  depends_on:
    - accounts.primary
  body:
    reference: SUB-MONTHLY
    account_id: ${accounts.primary.id}
```

ATF provisions `accounts.primary` first and substitutes its real identity before creating the
subscription. `.id` means "that resource's identity" — it resolves through the dependency's own
`id_field`, whatever that field is called.

For a date the resource needs, use a relative timestamp rather than a fixed one, so the data does
not rot:

```yaml
    renews_at: ${now+30d 09:00}
```

## Decide whether it should persist

By default a resource is **persistent**: found-or-created, then left alone. If your resource must be
brand new for every run — a one-time token, a signup, a session — mark the type ephemeral:

```yaml
signup:
  system: rest
  path: /signups
  natural_key: email
  lifecycle: ephemeral
```

ATF then creates it fresh each run and deletes it when the scenario ends. See
[About lifecycles](../explanation/lifecycles.md) for which to choose.

If the resource must already exist and ATF should never create it, make it a reference:

```yaml
  mode: reference
  ref_field: slug        # the remote field to match `natural_key` against, if it differs
```

## Check it

Loading the catalog validates it. Ask for status:

```sh
atf status dev
```

Your resource appears as `absent`, `present`, or `ephemeral`. If you made a mistake — a typo in the
type name, a dependency that does not exist, a cycle — the command exits 2 and lists **every**
problem it found, not just the first.

To create it now rather than waiting for a spec to need it:

```sh
atf seed dev --type subscription --name monthly
```

This provisions the resource and everything it depends on. The environment must be listed in
[`mutable_envs`](../reference/manifest.md#mutable_envs), or the command refuses and changes nothing.

## Use it in a spec

No registration step: the resource is immediately available to every scenario.

```gherkin
  Scenario: A monthly subscription renews
    Given the subscription "monthly"
    When I advance to the renewal date
    Then the subscription is still active
```

The `Given` line works as soon as the YAML exists. `context.subscription` holds the record the
adapter returned, so your `When`/`Then` steps can read fields off it.

A type name becomes a pytest fixture name, so a few are taken. If yours collides, the catalog
refuses to load and says so; rename the type and leave the instance names alone. The full list is in
[reserved type names](../reference/catalog.md#reserved-names).

## Where to go next

- [How to add a scenario](add-a-scenario.md) — putting the new resource to work.
- [Catalog reference](../reference/catalog.md) — every key, with the defaults.
- [About lifecycles](../explanation/lifecycles.md) — persistent, ephemeral, or reference.
- [How to add an adapter](add-an-adapter.md) — when the built-in `rest` adapter cannot reach it.
