# examples/todo

A complete ATF suite, run against a tiny in-process fake API so it needs no backend.

```sh
uv run pytest -q          # 8 passed
```

`conftest.py` starts `fake_api.py` and exports `TODO_URL` before ATF bootstraps. Point `TODO_URL`
at something real and that block does nothing.

New to ATF? Read [Your first spec](https://mde-pach.github.io/atf/tutorial/your-first-spec/) first;
this suite is what the tutorial's toy version grows into.

## What it exercises

| Seam | Where |
|---|---|
| REST get-or-create, single natural key | `owner` |
| Composite natural key + scoped listing | `todo_list` (`natural_key: [owner_id, slug]`, `list_path`) |
| Non-default identity field | `task` (`id_field: uuid`) |
| `${dependency.id}` and `${now+Nd HH:MM}` placeholders | `catalog/lists.yaml`, `catalog/tasks.yaml` |
| Reference mode (find-only) | `label` — the environment ships it; ATF never creates it |
| Custom adapter, multi-step create + teardown | `guest` — sign up → activate → poll until ready |
| Ephemeral lifecycle | `guest` — built per run, deleted afterwards |
| A read-only environment | `staging`, absent from `mutable_envs` |
| Read-and-compare steps ATF provides | every `Then` but one, across both features |
| A generated value | `guest` — `nickname: visitor-${uuid:hex}`, safe because a guest is ephemeral |

## Driving it from the CLI or cockpit

Nothing to set up — `adapters.py` starts the stand-in API when `TODO_URL` is unset, so every
entry point works out of the box:

```sh
atf status dev     # 1/7 present (the shipped label) — the rest absent
atf seed dev       # 6 created, 1 found; the ephemeral guest is not seeded
atf run            # 8 passed
atf serve          # the cockpit on http://127.0.0.1:8000
```

Each command gets its own short-lived API, so state does not carry between them — `atf status`
right after `atf seed` reports everything absent again. To keep one backend across commands, run
it yourself and point at it:

```sh
python fake_api.py 8765
export TODO_URL=http://127.0.0.1:8765 TODO_ACTOR=example
```

Do that before `atf serve` — the cockpit is worth looking at against a backend that remembers what
you provisioned. See
[Read your suite in the cockpit](https://mde-pach.github.io/atf/tutorial/read-your-suite-in-the-cockpit/).

`atf seed staging` exits 2: `staging` is not in `mutable_envs`.

## How little step code this needs

Seven scenarios; four step functions, all of them in `specs/steps/test_lists.py`. Three are `When`s
that call the API — performing an action is real code by definition. The fourth is a `Then`, because
"all of them are open" is a claim about a response, not about a resource ATF can read back.

`specs/steps/test_guests.py` has no step code at all: one `scenarios(…)` line, and both its
scenarios assert through the steps ATF provides.

The one worth reading twice is "Completing a task marks it done":

```gherkin
Given the task "laundry"
When I complete the task          # yours: a PATCH against the API
Then the task "laundry" field "done" is "true"     # ATF's: it reads the task back
```

The `Then` is generic even though the `When` changed the task behind ATF's back, because it goes
back to the backend and looks rather than trusting what the scenario was handed. See
[Read-and-compare steps](https://mde-pach.github.io/atf/reference/specs-and-fixtures/#read-and-compare-steps).

## Two things the catalog is doing on purpose

**`tasks.laundry` exists so `tasks.milk` stays open.** Persistent resources are get-or-created and
left in place, so a scenario that *mutates* one must own it. "Completing a task marks it done"
closes `laundry`; "A list carries only open tasks" asserts `milk` is still open. Point both at the
same task and the second scenario fails on the second run.

**The guest is one adapter, not three steps.** Signing up, activating and polling until ready is a
chain no declarative config expresses — so it lives in `adapters.py`, and the catalog treats a
guest exactly like any other resource.
