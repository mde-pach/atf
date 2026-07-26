# ATF documentation

ATF is an end-to-end test framework built on one idea: a test is a readable spec that declares the
resources it needs, and the framework makes those resources exist before the test runs.

These docs come in four kinds. Which one you want depends on what you are doing right now.

## Tutorial

Start here if you are new. It is a lesson: you build a working suite from nothing, and everything is
provided — no decisions to make, no prior knowledge assumed.

- **[Write your first spec](tutorial/write-your-first-spec.md)** — install ATF, declare a resource,
  write a scenario in plain English, and watch it provision what it needs and pass. About fifteen
  minutes.

## How-to guides

Recipes for getting a specific job done, assuming you already know your way around.

- **[How to add a resource](how-to/add-a-resource.md)** — declare a new entity your specs can depend
  on, including dependencies and placeholders.
- **[How to add an adapter](how-to/add-an-adapter.md)** — teach ATF to provision in a system the
  built-in adapters cannot reach, including multi-step creation.
- **[How to diagnose a failing provision](how-to/diagnose-a-failing-provision.md)** — read the error
  you actually got, and narrow down which half is broken.
- **[How to adopt ATF in an existing suite](how-to/adopt-atf-in-an-existing-suite.md)** — add ATF to
  a repository that already has pytest tests, one resource at a time.
- **[How to run ATF in CI](how-to/run-atf-in-ci.md)** — use your suite as a deployment guard, with
  secrets, environments and exit codes.

## Reference

Facts to look up while you work. Dry by design.

- **[Manifest](reference/manifest.md)** — every key of `atf.yaml`, the built-in adapter settings, and
  the auth schemes.
- **[Catalog](reference/catalog.md)** — the type registry, instance files, placeholders, validation
  rules, and the node structure.
- **[Specs and fixtures](reference/specs-and-fixtures.md)** — the provisioning step, the fixtures the
  plugin provides, the `Materializer`, and the exceptions.
- **[CLI](reference/cli.md)** — every command, option, exit code and environment variable.
- **[Cockpit](reference/cockpit.md)** — the pages, the mutation gate, runs, search, and the
  confirmation token's lifetime.
- **[Adapter SPI](reference/adapter-spi.md)** — the protocol, the registry, and the HTTP helpers.

## Explanation

Background and reasoning, for when you want to understand rather than do. Read away from the
keyboard.

- **[About the model](explanation/the-model.md)** — resource, spec, test, fixture, adapter: what each
  word means and why the relationships between them are the point.
- **[About declarative catalogs](explanation/why-declarative-catalogs.md)** — why resources are data
  rather than setup code, what that buys, and what it costs.
- **[About lifecycles](explanation/lifecycles.md)** — persistent versus ephemeral, why persistence is
  the default, and the ownership rule that keeps a suite re-runnable.

## Versions and stability

ATF is at **0.1.0** and is not yet released to PyPI. The adapter SPI, the manifest schema and the
catalog format are the surfaces a suite depends on; they are stable in intent but not yet frozen,
and there is no deprecation policy before 1.0. Pin a commit if you need reproducibility.

## Elsewhere in the repository

- [`examples/todo/`](https://github.com/mde-pach/atf/tree/main/examples/todo) — a complete suite
  exercising every seam against an in-process fake API.
- [`selftest/`](https://github.com/mde-pach/atf/tree/main/selftest) — ATF tested with ATF: an ATF
  suite whose system under test is the `atf` CLI.
