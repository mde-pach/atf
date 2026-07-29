# ATF documentation

ATF is an end-to-end test framework built on one idea: **a test is a readable spec that declares the
resources it needs, and the framework makes those resources exist before the test runs.**

```gherkin
Scenario: A project belongs to its account
  Given the account "primary"
  And the project "alpha"
  When I list the projects of the account
  Then the project "alpha" is listed
```

You did not write `Given the account "primary"`. The account is a node in a YAML catalog; ATF
resolves it, provisions its whole dependency chain into the target environment, and hands the record
to your step. Adding a resource is a YAML node. Adding a behaviour is a scenario. Tests and fixtures
follow.

## Start here

New to ATF? The tutorial is three short lessons, and everything is provided.

1. **[Your first spec](tutorial/your-first-spec.md)** — build a working suite from nothing and watch
   it provision what it needs. Ten minutes, no server required.
2. **[Point ATF at your own API](tutorial/point-atf-at-your-api.md)** — swap the stand-in for a real
   service, and see find-or-create earn its keep.
3. **[Read your suite in the cockpit](tutorial/read-your-suite-in-the-cockpit.md)** — the web app
   that renders what your suite declares, what exists, and what is red.

In a hurry, or want the words first? Read the **[glossary](explanation/glossary.md)**, then
**[Life of a run](explanation/life-of-a-run.md)** — between them they are the whole mental model.

## How-to guides

Recipes for getting a specific job done, assuming you know your way around.

**Setting up**

- [Add a resource](how-to/add-a-resource.md) — declare a new entity your specs can depend on,
  including dependencies and placeholders.
- [Add an adapter](how-to/add-an-adapter.md) — reach a system the built-in adapters cannot,
  including multi-step creation.
- [Adopt ATF in an existing suite](how-to/adopt-atf-in-an-existing-suite.md) — add ATF to a
  repository that already has pytest tests, one resource at a time.
- [Run ATF in CI](how-to/run-atf-in-ci.md) — your suite as a deployment guard, and getting the
  results back.

**Day to day**

- [Add a scenario](how-to/add-a-scenario.md) — one more behaviour in a feature that already exists.
- [Keep the catalog in step with an API change](how-to/keep-the-catalog-in-step.md) — when the
  service moves underneath your declarations.

**When it breaks**

- [Find out why an environment is red](how-to/find-out-why-an-environment-is-red.md) — the order to
  look in, using the cockpit.
- [Diagnose a failing provision](how-to/diagnose-a-failing-provision.md) — read the error you
  actually got, and narrow down which half is broken.

## Reference

Facts to look up while you work. Dry by design, and every key has its own anchor.

- **[Manifest](reference/manifest.md)** — every key of `atf.yaml`, the built-in adapter settings,
  the auth schemes.
- **[Catalog](reference/catalog.md)** — the type registry, instance files, placeholders, validation
  rules, node structure.
- **[Specs and fixtures](reference/specs-and-fixtures.md)** — the provisioning step, the claims,
  acting on a system and on an interface, tables and markers, questions, the fixtures.
- **[Phrasebook](reference/phrasebook.md)** — one sentence, and the claims it stands for.
- **[CLI](reference/cli.md)** — every command, flag, exit code and environment variable.
- **[Cockpit](reference/cockpit.md)** — the three verticals, readiness, provisioning, the composer,
  run history.
- **[Providers](reference/providers.md)** — the `${...}` sources: generated values, the environment,
  now.
- **[Adapter SPI](reference/adapter-spi.md)** — the protocol, the registry, the HTTP helpers.

## Explanation

Background and reasoning, for when you want to understand rather than do.

- **[Glossary](explanation/glossary.md)** — every word ATF uses in a particular way, defined once.
- **[Life of a run](explanation/life-of-a-run.md)** — what happens, in order, from `atf run` to
  teardown.
- **[About the model](explanation/the-model.md)** — why resources, scenarios, tests and fixtures are
  separate things, and why the edges between them are the point.
- **[About declarative catalogs](explanation/why-declarative-catalogs.md)** — why resources are data
  rather than setup code, what that buys, and what it costs.
- **[About lifecycles](explanation/lifecycles.md)** — persistent versus ephemeral, and the ownership
  rule that keeps a suite re-runnable.

## Versions and stability

ATF is at **0.1.0** and is not yet released to PyPI. The adapter SPI, the manifest schema and the
catalog format are the surfaces a suite depends on; they are stable in intent but not yet frozen,
and there is no deprecation policy before 1.0. Pin a commit if you need reproducibility.

## Elsewhere in the repository

- [`tests/`](https://github.com/mde-pach/atf/tree/main/tests) — ATF tested with ATF: a suite
  whose system under test is the `atf` CLI. The largest worked example there is, and the only one
  that cannot drift from what ATF does, because breaking ATF turns it red.
- Whatever `atf init` writes you. There is no sample project checked in here on purpose: a
  checked-in example is a second thing to keep green and it drifts from what the tool produces,
  while the scaffold is what every new suite actually starts as.
