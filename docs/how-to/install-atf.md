# Install ATF

Get the `atf` command onto a machine and confirm it can read a suite.

## The shortest path

```sh
pip install atf
```

```console
$ atf --version
atf 0.1.0
```

That is the whole install. `atf` is a command and a library; there is nothing to start and nothing
to log in to.

## What it needs

Python 3.11 or newer, and pytest, which comes with the package. ATF's engine *is* pytest — a
resource is a [pytest fixture](../reference/arrange.md#asking-for-one) — so pytest is a dependency
rather than an integration, and a suite that already uses pytest keeps its plugins, its `-k`, its
`--pdb` and its coverage.

## What it does not need

No backend. No server, no daemon, no database of its own, no account. ATF holds no state between
runs — it asks the systems you point it at what they hold, every time. See
[Why there is no state file](../explanation/why-there-is-no-state-file.md) for why that is a design
decision rather than a missing feature.

The systems a suite talks to are yours. `command`, `browser`, `filesystem` and `process` ship with
ATF; anything else — a database, an HTTP API, a queue — is an
[adapter](../reference/arrange.md#adapter) the suite carries, and installing ATF installs none of
its dependencies.

## The browser dependency

Install it only if a suite declares a resource on the `@browser` system.

```sh
pip install "atf[browser]"
playwright install chromium
```

Two steps, because the extra installs the Python library and the second command downloads the
browser itself. The download is a few hundred megabytes, which is the reason it is not in the base
install: a suite that tests a command line should not pay for a browser it never opens.

## Verify it

In a directory with a suite, ask whether the suite is well formed. `atf check` reads the manifest
and the specs and touches no environment, so it works before anything is configured.

```console
$ atf check
14 scenarios, 4 resources, 3 phrases
ok
```

With no suite to hand, make an empty one.

```console
$ atf init
wrote atf.yaml
wrote resources.py
wrote specs/
$ atf check
0 scenarios, 0 resources, 0 phrases
ok
```

[`atf init`](../reference/the-command.md#init) scaffolds nothing but ATF itself — a manifest with
one environment, an empty `resources.py`, an empty `specs/`. No example tests to delete.

## When it goes wrong

**`atf: command not found`.** The package went into an interpreter whose scripts directory is not on
your `PATH`. Install with the interpreter you mean to use: `python -m pip install atf`.

**Exit `2`, `no such file: atf.yaml`.** You are not in a suite directory. Point at the manifest with
`--config path/to/atf.yaml`, or run `atf init` here.

**A browser scenario fails naming an executable, not a claim.** `pip install "atf[browser]"` ran and
`playwright install chromium` did not. The library is present; the browser is not.

**pip refuses over a pytest version.** ATF needs pytest 8 or newer. An existing suite pinned below
that has to move first; nothing in ATF works around it.

## Where to go next

- [Run a suite](../tutorial/1-run-a-suite.md) — the four-chapter route in, starting from a suite and
  a 25-line app you are handed.
- [Adopt ATF in an existing suite](adopt-atf-in-an-existing-suite.md) — the other route in, for a
  repository that already has hundreds of pytest tests.
- [Configure an environment](configure-an-environment.md) — the manifest `atf init` wrote, and the
  systems to put in it.
