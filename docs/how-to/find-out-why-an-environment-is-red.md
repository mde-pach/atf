# How to find out why an environment is red

Something is failing against staging and you do not yet know whether it is the suite, the data or
the service. This guide is the order to look in, using the cockpit.

```sh
atf serve
```

Open <http://127.0.0.1:8000> and **switch to the environment in question**, using the selector in
the top bar. Every answer the cockpit gives is about one environment; reading dev's numbers while
staging is broken wastes the first five minutes. If you type an environment name that does not
exist, you get a 404 listing the ones that do — you will never be shown dev while believing you are
looking at staging.

## Read the verdict, then the counts

The Overview opens with one sentence. **No — 3 scenarios failing** is a different morning from **Not
fully**, which is a different morning again from **Not yet**.

Underneath it, the counts separate failures that feel identical in a build log:

| What you see | What it means |
|---|---|
| scenarios **failing** | tests ran and failed — a real failure, or a flaky one |
| scenarios **blocked** | they cannot start; something they name is broken here |
| scenarios **never run** | nobody has asked yet, so nothing is known |
| the environment's **broken** list | resources ATF cannot even look up here |
| the environment's **absent** list | resources a run would simply create — usually not your problem |

Check the freshness line — *checked N mins ago* — before you trust any of it. If it is stale, press
**Rescan**; that is a read, so it is safe in any environment, including ones ATF may not change.

Click a count to go straight to those scenarios: the Overview links to
`/scenarios?state=failing` and friends.

## Separate blocked from failing

Go to **Scenarios**. Two states look equally alarming and mean completely different things.

**`failing`** means it ran, and an assertion or a step raised.

**`blocked`** means it has not run, and would not get as far as its first `When`, because something
it names is in a state a run cannot fix. There are exactly three such states — see
[readiness](../reference/cockpit.md#readiness) for what each one is — and each has a different
owner:

| Blocker | Where the fix is |
|---|---|
| `unsupported` | the `adapters` block for that environment in `atf.yaml` |
| `error` | the environment, the URL, or the credentials behind its `*_env` pointer |
| a missing [reference](../reference/catalog.md#mode) resource | whatever process sets that environment up |

!!! warning "An absent resource is not a blocker"

    A scenario naming resources this environment does not have yet is **ready**, not blocked.
    Naming a resource is precisely what makes ATF create it, so the cockpit reports it as
    information — *provisions 3 resources* — and running the scenario is what fixes it.

    A brand-new environment where everything is absent is fine. One missing feature flag the suite
    treats as a reference resource is not.

Deal with the blockers before reading a single failure. They often explain the failures next to
them.

## Clear what a run can clear

Press **Provision**. With nothing selected it takes everything ATF can create that is not there yet;
select a resource type, an instance or a scenario's missing resources to narrow it. Either way it
provisions each target's closure, dependencies first, as a background job.

The job reports into the dock at the bottom of the window, and the dock follows you around the app —
so you can start provisioning and go read the failing scenarios while it works.

From a terminal, the same thing:

```sh
atf seed staging
```

If Provision is disabled and says so, the environment is not in
[`mutable_envs`](../reference/manifest.md#mutable_envs). That is deliberate. Either add it to the
manifest, or provision through whatever process owns that environment.

`unsupported` is not fixed this way — no amount of provisioning creates an adapter. Add the system's
settings to that environment in the manifest.

If provisioning itself fails, you are now in
[How to diagnose a failing provision](diagnose-a-failing-provision.md) — that guide is the
message-by-message walkthrough.

## Read a failure at the step level

Open a failed scenario. The page shows the Gherkin and **the step the run reached**.

That single fact usually ends the investigation:

- Failed on a `Given` — provisioning, despite the resource reading `present`. Something raised while
  finding or creating it. Check the resource's status on the same page; an `error` there carries the
  adapter's message.
- Failed on the `When` — your system under test rejected the call, or the client is misconfigured
  for this environment. Check the `clients` block for the environment in the manifest.
- Failed on a `Then` — the system did something, and it was the wrong thing. This is the only case
  that is a genuine test failure, and the only one worth escalating as a bug.

The resources the scenario names are listed with their live status beside the Gherkin, so you can
see at a glance whether the failure had the data it needed.

## Decide whether to believe it

A scenario marked **flaky** has passed and failed across recent runs with no change to the suite.
Its last outcome tells you nothing. The Overview lists these under Recent runs, by scenario title
and how many times the verdict flipped.

Flakiness in an end-to-end suite is usually one of:

- **A shared resource being mutated.** One scenario changes what another asserts on, so the result
  depends on order. Give the mutating scenario its own instance — see
  [About lifecycles](../explanation/lifecycles.md#a-scenario-that-mutates-a-persistent-resource-must-own-it).
- **A slow downstream system.** The resource exists but is not ready yet. Waiting for readiness
  belongs in the adapter's `create`, not in a step.
- **Two runs against one environment at once.** Provisioning is not safe under concurrency; see
  [concurrency](../reference/fixtures.md#concurrency).

Fix the flakiness before chasing the failure. A test you cannot trust cannot tell you whether you
fixed anything.

## When it is only red in CI

Import the build's report and look at it in the same place as everything else:

```sh
atf import-run staging report.json
```

The run joins the history under `.atf/runs/`, so the cockpit shows the CI outcome on the scenario
page — including whether the test has been flaky across the mixture of local and CI runs. Make CI
upload that report as an artifact; see [How to run ATF in CI](run-atf-in-ci.md).

If CI is red and local is green against the same environment, compare what differs: the credentials
behind the `*_env` pointers, and whether CI provisioned before running.

## When the Overview says collection failed

If the Overview leads with a notice that discovery produced nothing, ATF ran `pytest --collect-only`
and the suite would not import. Every count below that notice is a claim about an empty model, so
none of them is worth reading until this is fixed.

The cause is nearly always the import-time bootstrap — a manifest error, an unset `*_env` pointer,
or a catalog problem. See it on its own:

```sh
atf status staging
```

That command does the same bootstrap with none of the pytest noise, and prints every catalog problem
at once.

## Where to go next

- [How to diagnose a failing provision](diagnose-a-failing-provision.md) — the message-by-message
  guide, once you know provisioning is the half that is broken.
- [How to keep the catalog in step with an API change](keep-the-catalog-in-step.md) — when
  everything is suddenly `absent`.
- [Cockpit reference](../reference/cockpit.md) — every state and control used above.
- [About lifecycles](../explanation/lifecycles.md) — the ownership rule behind most flakiness.
