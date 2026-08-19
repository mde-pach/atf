# Running less of it

*The suite takes too long, or you only care about the part you just changed.*

## Only what touches this

```console
$ atf run --select laundry --dry-run
atf/lists.feature::a row the API has no endpoint for is declared over the database
atf/lists.feature::a domain verb is a phrase over a field change, and its effect lasts
2 tests selected
```

`--select` reads the sentences. It takes what `atf explain` takes — a thing, a kind, a system, a
phrase, a scenario or a file — and selects every test that reaches one, through lineage or
otherwise. `--select owner` selects eight here, and nothing had to be tagged for that to be true.

Naming something the suite does not declare stops before anything runs:

```console
$ atf run --select groceres
nothing is called 'groceres'. Did you mean:
  groceries  (a thing)
```

Naming something real that no test reaches is an answer, and exits `0`.

Beside it: `--failed` for what broke last time, `-k` for an expression over test identities, and
`--tag` for what is genuinely not derivable from the sentences.

## What can run beside what

Two tests that share nothing permanent cannot interfere, and the graph knows which those are. A run
lays itself out concurrently with no flag and no marker on a test.

```console
$ atf run --explain
11 tests
  7 can run beside something else, in 1 sets
  4 run alone
         3  "a Python test body" has an effect nothing declares
         1  "I ask for the lists of "primary"" has an effect nothing declares
  set of 7
      atf/lists.feature::a domain verb is a phrase over a field change, and its effect lasts
      atf/lists.feature::a field nobody gave a value is filled by resolution
      atf/lists.feature::a row the API has no endpoint for is declared over the database
```

`--explain` lays the run out and runs none of it. The cost is in the second block: a sentence whose
effect nothing declares is treated as any effect at all, and that is what puts a test on its own. A
Python test body is opaque by nature, and so is a word of yours until it says otherwise —
`@act("…", effect="reads")` is how one rejoins a set.

`--jobs` is `auto`, which leaves one core free.

## Across machines

```console
$ atf run --shard 1/4
```

Every shard slices the same layout, so four machines cover the run between them with no coordination.
`--shuffle` runs them in an order nothing chose and prints the seed; `--seed 7` runs that order again.

## Without making anything

`--no-make` runs against what is already there and fails on anything missing, naming it. `--dry-run`
prints what would run and runs none of it.
