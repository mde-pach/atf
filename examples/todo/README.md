# examples/todo

A complete ATF suite, run against a tiny in-process fake API so it needs no backend.

```sh
uv run pytest -q          # 8 passed
```

`conftest.py` starts `fake_api.py` and exports `TODO_URL` before ATF bootstraps. Point `TODO_URL`
at something real and that block does nothing.

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

## Driving it from the CLI or cockpit

Those need the API running as a separate process:

```sh
python fake_api.py 8765
export TODO_URL=http://127.0.0.1:8765 TODO_ACTOR=example

atf status dev     # 1/7 present (the seeded label) — the rest absent
atf seed dev       # 7/7 provisioned; the ephemeral guest is not seeded
atf run            # 8 passed
atf serve          # the cockpit
```

`atf seed staging` exits 2: `staging` is not in `mutable_envs`.

## Two things the catalog is doing on purpose

**`tasks.laundry` exists so `tasks.milk` stays open.** Persistent resources are get-or-created and
left in place, so a scenario that *mutates* one must own it. "Completing a task marks it done"
closes `laundry`; "A task lands on its list" asserts `milk` is still open. Point both at the same
task and the second scenario fails on the second run.

**The guest is one adapter, not three steps.** Signing up, activating and polling until ready is a
chain no declarative config expresses — so it lives in `adapters.py`, and the catalog treats a
guest exactly like any other resource.
