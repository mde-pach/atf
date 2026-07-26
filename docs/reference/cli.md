# CLI reference

```
atf [-h] {init,serve,seed,status,run} ...
```

Every command locates the manifest as described in the [manifest reference](manifest.md).

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | The command ran and reported failure: a failing test, or a resource that could not be provisioned. |
| `2` | The command did not run: a configuration or catalog error, an unknown environment, a refused mutation, or invalid arguments. |
| `130` | Interrupted. |

## `atf init`

```
atf init [directory]
```

Writes a starter suite: `atf.yaml`, `catalog/` with a two-type registry and two instances,
`adapters.py`, `conftest.py`, `specs/` with one feature, its steps, an SUT client and a `conftest.py`
exposing it, plus `.gitignore` and `README.md`.

| Argument | Default | Description |
|---|---|---|
| `directory` | `.` | Directory to write into. Created if absent. |

Existing files are never overwritten; files already present are skipped and the command reports
which were written.

## `atf serve`

```
atf serve [--env ENV] [--host HOST] [--port PORT]
```

Runs the cockpit under uvicorn and prints a security banner naming the URL, the absence of
authentication, and the mutable environments.

| Option | Default | Description |
|---|---|---|
| `--env` | `ATF_ENV`, else `default_env` | Environment shown on first load. |
| `--host` | `127.0.0.1` | Interface to bind. Any value other than `127.0.0.1`, `localhost` or `::1` also prints a warning to stderr. |
| `--port` | `8000` | Port to bind. |

The cockpit has no authentication. Mutating routes reject environments absent from `mutable_envs`
with 409 and require a confirmation token.

## `atf seed`

```
atf seed ENV [--type TYPE] [--name NAME] [--keep-going]
```

Provisions resources into `ENV`, dependencies first, and prints one line per node with its action
(`created`, `exists`, `reference`, `blocked`) or failure, then a tally.

| Argument | Description |
|---|---|
| `ENV` | **Required.** The environment to provision into. Must appear in `mutable_envs`. |
| `--type` | Restricts to one resource type. |
| `--name` | Restricts to one instance of `--type`. Requires `--type`. |
| `--keep-going` | Attempt independent resources after a failure instead of stopping at the first. |

Without `--keep-going`, the first failure ends the pass and the remaining resources are not
attempted; the output says how many were skipped. This is the default because provisioning failures
are usually correlated — a bad token or an unreachable backend fails every resource, and reporting
it once is clearer than reporting it two hundred times.

With `--keep-going`, a failed resource's dependents are reported `blocked` and never attempted,
while unrelated resources are still provisioned. Use it when you believe the failures are
independent and want them all in one pass.

To see every problem without changing anything, use [`atf status`](#atf-status) instead — it is
read-only and always reports every resource.

With neither option, every **persistent** resource is provisioned; ephemeral resources are skipped,
because nothing would tear them down. Naming an ephemeral type explicitly provisions it.

With `--type` or `--name`, the selected resources and their dependencies are provisioned.

Exits 2 when `ENV` is absent from `mutable_envs`, when `--type` names an unknown type, when
`--name` matches nothing, or when `--name` is given without `--type`. Exits 1 when provisioning
fails.

## `atf status`

```
atf status ENV
```

Prints one line per resource with its status, then a summary counting present resources against the
persistent total.

| Status | Meaning |
|---|---|
| `present` | Found in the environment. |
| `absent` | Not found. |
| `ephemeral` | Built per run; not looked up. |
| `unsupported` | No adapter is configured for that resource's system in this environment. |
| `error` | The adapter raised while looking it up. The message follows on the same line. |

Read-only; permitted in any environment.

## `atf run`

```
atf run [paths ...] [--env ENV]
```

Runs the specs in a subprocess with the environment set, then prints one line per test with its
outcome and duration, the last line of the failure for tests that failed, and a summary.

| Argument | Default | Description |
|---|---|---|
| `paths` | the manifest's `specs` directory | pytest node ids or paths to run. |
| `--env` | `ATF_ENV`, else `default_env` | Environment to run against. |

Exits 1 if pytest exits non-zero — a failing test, but also a collection error, a missing step
definition or a usage error. Suitable as a CI gate; read the output to tell which.

## Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `ATF_MANIFEST` | `serve`, `seed`, `status`, `run` | Path to the manifest, bypassing the upward search. `init` does not read it. |
| `ATF_ENV` | `serve`, `run` | Active environment, unless `--env` is given. `seed` and `status` take the environment as a required positional argument and ignore this variable. |
| *manifest `*_env` pointers* | all commands | Supply the values the manifest points at. An unset pointer is an error at startup. |

## See also

- [How to run ATF in CI](../how-to/run-atf-in-ci.md).
- [Write your first spec](../tutorial/write-your-first-spec.md).
