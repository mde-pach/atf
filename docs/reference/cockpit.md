# Cockpit reference

The cockpit is a server-rendered web app started with `atf serve`. It reads the catalog, the specs
and the test results for one environment at a time, and can provision resources and run tests in
environments the manifest marks mutable.

## Pages

| Path | Shows |
|---|---|
| `/` | Overview: the Config, Coverage and Health meters, coverage gaps, recent runs, absent resources. |
| `/catalog` | Every resource grouped by collection, the lineage graph of the focused node, and its inspector. |
| `/catalog/node/{node_id}` | The same page focused on one resource. |
| `/specs` | Every scenario grouped by feature; the detail shows the Gherkin with resource names linked, the Examples table, and the covering tests. |
| `/specs/{spec_id}` | One spec. |
| `/tests` | Every test grouped by the spec it covers, with checkboxes and Run controls. |
| `/tests/detail/{test_id}` | One test: the spec it covers, the resources it uses, the fixtures it builds on, its last result. |
| `/fixtures` | Fixtures in use, separated into those generated from the catalog and the rest. |
| `/fixtures/{name}` | One fixture: docstring, scope, and the tests that used it. |

## The environment switcher

Every page reads `?env=<name>`, falling back to the `HX-Env` header and then to the environment
`atf serve --env` selected. Unknown names fall back silently to the default. The selector in the
sidebar reloads the page with the new value.

Each environment has its own cached materializer, status, discovery, results and job.

## Discovery

Opening any page triggers discovery for that environment if it is not already cached: ATF runs
`pytest --collect-only` in a subprocess to learn which tests exist, what they cover and which
fixtures they use.

Collection **never executes a test** and never provisions anything, so viewing a page is safe in
any environment. It does import the suite, which means a manifest error or an import error surfaces
as a banner on the page rather than as tests.

Discovery has a 300-second timeout. On timeout the page still renders — specs come from a static
parse of the `.feature` files — but the Tests and Fixtures pages are empty and the banner says so.

## Mutating actions

| Control | Route | Effect |
|---|---|---|
| **Seed** | `POST /catalog/seed` | Provisions every absent resource, and the dependencies of each. |
| **Create** | `POST /catalog/create/{node_id}` | Provisions one resource and its dependency closure. |
| **Sync** | `POST /catalog/sync` | Reloads the catalog from disk and re-reads status. Does not change the environment. |
| **Run selected / Run all** | `POST /tests/run` | Starts a background run of the chosen tests. |

Each requires two things:

- the environment must appear in `mutable_envs`, or the route returns **409** and the control
  renders disabled;
- the request must carry the confirmation token, or the route returns **409**.

The token is generated once per `atf serve` process and embedded in every page. **Restarting the
server invalidates every open tab** — reload the page before acting on it. The browser replays the
token automatically, so it defends against another site posting to your cockpit, not against you.

Submitted test ids are intersected with the tests discovery found; anything else is rejected.

## Runs

A run starts a background job and the page returns immediately. The view polls
`GET /tests/progress` every 400 ms, showing each test as `pending`, `running`, then its outcome.
Polling stops when the job finishes, and the Overview meters re-sync.

There is **one active job per environment**. Starting a run while one is in flight returns the
running job rather than starting a second. A run that exceeds 30 minutes is killed and reported as
timed out, releasing the slot.

Results are held in memory for the life of the process; there is no run history on disk.

## Search

`⌘K` (or `Ctrl-K`) opens a search over resources, specs, tests and fixtures. Matches are ranked
exact, then prefix, then substring, and capped at 12.

## Themes

The interface follows the operating system's light or dark setting, and the toggle in the top bar
overrides it. The choice is stored in `localStorage`.

## Security posture

The cockpit has **no authentication**. `atf serve` binds `127.0.0.1`; any other `--host` prints a
warning. For shared access, put it behind an authenticating reverse proxy. See
[the CLI reference](cli.md#atf-serve).

## See also

- [How to diagnose a failing provision](../how-to/diagnose-a-failing-provision.md).
- [CLI reference](cli.md) — `atf serve`.
