# The record

What a run leaves behind: the run itself, the outcome of each test, the verdict folded over those
outcomes, the history kept beside the suite, and the reports written out of it. Everything here is
data.

## The two vocabularies {#the-two-vocabularies}

There are exactly two.

- **What an environment holds**, of one resource right now: `present` · `absent` · `unreachable`.
- **What a run did**, of one test once: `passed` · `failed` · `skipped`.

The first is asked of the environment and answered by looking. The second is recorded by running.
They never mix. A resource is never `failed`. A test is never `absent`.

Everything else is derived, and there are two ways to derive it. A **fold** reduces many outcomes to
one word — a [verdict](#verdict) over a scenario's rows. A **prediction** guesses at a run that has
not happened — "blocked".

**Blocked is a prediction, not a state.** A test whose resource is absent is not blocked: naming a
resource is what makes ATF create it. One that cannot be created fails the test that named it, on
the sentence that named it. The word survives only where the editor predicts, before a run, that a
test will fail for want of a resource, and labels that a guess. Nothing in the record has a third
vocabulary.

- **In CI** — the two vocabularies are what the human output prints and what `--report` writes. An
  exit code is the narrowest possible fold of the second one.
- **In the editor** — the overview's counts, the two vocabularies side by side, one line each.
- **To an agent** — both are closed enumerations in the tool schemas, so a branch needs no fallback.

## A run {#a-run}

A run is one execution of a selection of tests against one environment.
[`atf run`](the-command.md#run) produces one.

`id`
:   Unique within the suite. Assigned when the run starts.

`environment`
:   The environment name from `atf.yaml`. A run belongs to exactly one.

`started`, `finished`
:   UTC, ISO 8601. `finished` is absent while the run is in flight.

`source`
:   `local` for a run this machine executed, `imported` for one brought in with `atf import-run`.

`label`
:   Free text carried in from CI, such as `ci` or `nightly`. Empty for local runs.

`revision`
:   The version control revision, if the suite is in one.

`selection`
:   The flags that chose the tests, so a partial run is never mistaken for a full one.

`outcomes`
:   One per test.

A laptop run and a CI run are the same shape. They differ in `source` and `label` and in nothing
else, which is what lets one be imported into the other's [history](#history).

```json
{
  "id": "r-0f3a91",
  "environment": "local",
  "started": "2026-08-03T09:14:22Z",
  "finished": "2026-08-03T09:14:26Z",
  "source": "local",
  "label": "",
  "revision": "8c41d02",
  "selection": {"tag": null, "select": null, "failed": false},
  "outcomes": [...]
}
```

A run records what it did, never what the environment held — that is asked of the environment
rather than remembered. See
[why there is no state file](../explanation/why-there-is-no-state-file.md) for what would go wrong
if a run wrote it down.

- **In CI** — the process itself. Its identity is printed once at the start, its exit code is the
  summary, and `--report` writes it out in full.
- **In the editor** — the current run streams as it goes, and earlier runs of this suite are listed
  with their environment, label and time.
- **To an agent** — a run object, fetched by id, with its outcomes. An agent asks for the last run of
  an environment without knowing its id.

## Outcome {#outcome}

An outcome is what one test did in one run. Exactly one per test per run, and there is no fourth
word.

The outcome is `passed` when every step ran and every claim held, and `failed` when a step raised or
a claim did not hold. It is `skipped` when the test did not run: it was filtered out, or an earlier
step in the same test made the rest meaningless.

A failing outcome names the line in your file and the sentence written on it.

```json
{
  "test": "specs/lists.feature::a list belongs to its owner",
  "outcome": "failed",
  "duration_ms": 412,
  "failed_at": {
    "file": "specs/lists.feature",
    "line": 12,
    "step": "Then the todo_list \"groceries\" field \"slug\" is \"groceries\"",
    "message": "field \"slug\" is \"grocery\", expected \"groceries\""
  }
}
```

Within a failed test the steps have positions rather than a second vocabulary: every step above the
failure `passed`, the line itself `failed`, and every step below it is `skipped`.

A scenario outline produces one outcome per row of its `Examples`, each a distinct test identity:

```text
specs/lists.feature::a list belongs to its owner[owner=primary]
specs/lists.feature::a list belongs to its owner[owner=visitor]
```

- **In CI** — a line per test in the human output, and the full object in the report. The exit code
  is derived from the set of outcomes, never from their text.
- **In the editor** — the failing line is highlighted in the file you wrote, with passed steps above
  it and skipped steps below it dimmed.
- **To an agent** — the outcome object, including `failed_at`. The failing sentence is a field, not
  a traceback to parse.

## Verdict {#verdict}

A verdict is a fold of outcomes into one word, for something that is not a single test: a scenario
outline with its rows, a feature file, a tag, a directory, the whole suite.

`passing` is at least one outcome, none failed and at least one passed. `failing` is at least one
outcome that failed. `skipped` is at least one outcome, every one of them skipped. `never run` is no
outcomes at all.

The fold is ordered: any `failed` makes it `failing`; otherwise any `passed` makes it `passing`;
otherwise any `skipped` makes it `skipped`; otherwise `never run`.

Failure wins: a heading over twenty rows, nineteen of them passing, is `failing`.

`never run` is a verdict, not a failure. `atf docs` renders the specs carrying the last verdict, and
a scenario nobody has run yet is labelled `never run` rather than left blank.

Verdicts never appear in a run record. A run holds outcomes; verdicts are computed from them on
demand, by whoever is drawing a heading.

- **In CI** — the exit code of `atf run` is the suite's verdict narrowed to two values: `failing` is
  `1`, everything else is `0`. A run that never started has no verdict at all and exits `2`.
  `atf docs` writes verdicts beside headings.
- **In the editor** — the colour of a heading in the tree. A folded heading is coloured by the fold
  of everything under it, so nothing hides inside a collapsed node.
- **To an agent** — a `verdict` field on any node the agent asks about, with the counts it was folded
  from, so the agent can expand rather than guess.

## History {#history}

History is past runs, one JSON file per run named by its id, in `.atf/history/` beside `atf.yaml`.
It holds runs and their outcomes, and nothing about what an environment contains.

**History is files, not a database.** A `.db` beside the manifest would read as something under
test, since a suite's own `sqlite` adapter arranges resources in exactly such a file.

What it answers, and what each question is asked of:

- Has this test been failing since Tuesday, or since just now? — one test in one environment.
- Does this test disagree with itself? — one test, and see [flakiness](#flakiness).
- What did CI see that this laptop does not? — one environment, `source = imported`.
- What did the last run of `staging` select? — one run.
- Which tests have never run at all? — the suite.

Imported runs are files of the same shape as local ones. `atf import-run staging ci-results.json`
reads a CTRF file written by `atf run --report` in CI and stores it with `source: imported`.
Afterwards `atf run --failed` reruns what CI saw, on your machine, against your environment.

History is retained per environment for the last 50 runs. The oldest file is deleted when a new one
is written.

**A corrupt history is skipped, not raised.** A run file that cannot be read, or does not have the
shape ATF expects, is reported on stderr and left out of every question history answers; the tests
still run. The cost: `--failed` and flakiness go quiet for whatever they cannot read, and
`atf run --failed` on an empty history selects nothing rather than everything.

- **In CI** — usually not present. A fresh checkout has no history; `--failed` is a local flag.
- **In the editor** — a strip beside each test showing its last runs, so a first failure and a
  fortnight of failures do not look alike.
- **To an agent** — a queryable series: outcomes for a test over time, filtered by environment and
  source.

## Flakiness {#flakiness}

A test is flaky when its outcomes in history disagree with each other. ATF flags it. ATF does not
colour it.

Within one environment's retained history, a test is flagged `flaky` when both `passed` and `failed`
are present. Outcomes that agree are not flagged, and `skipped` mixed with one other word is not
flagged either: skipping is a selection, not a disagreement.

Flakiness is carried beside the verdict, never instead of it:

```json
{"test": "specs/lists.feature::a list belongs to its owner", "verdict": "passing", "flaky": true}
```

A flaky test makes no claim about the code in either direction, so the verdict is shown as computed
and the flag says not to trust it.

- **In CI** — a field in the report. `atf run` does not exit nonzero for flakiness: a flaky test that
  passed this time passed.
- **In the editor** — a flag beside the verdict, with the disagreeing runs one click away. The
  verdict keeps its own colour.
- **To an agent** — a boolean and the outcomes it was computed from, to rerun on before believing a
  failure.

## Report {#report}

A report is a run written out in a named format. ATF holds a registry of formats keyed by name; each
name owns a writer.

```sh
atf run --report ctrf:out.json
atf run --report ctrf:out.json --report ctrf:artifacts/nightly.json
```

The argument is `format:destination`. The flag repeats; each occurrence writes one file.

`ctrf` is the only format ATF ships. It writes JSON, and `atf import-run` reads it back. JUnit XML,
Allure and anything else a pipeline reads are formats a team registers; [extending
ATF](extending-atf.md#report-format) shows JUnit registered. A page elsewhere showing
`--report junit:…` is showing a registered format, not a shipped one.

CTRF — the Common Test Report Format — is registered by name like any other and can be replaced by
one of yours. It is what `--report ctrf:out.json` writes and what `atf import-run` reads, and one
format both ways is what makes a CI run and a local run interchangeable in [history](#history).

```json
{
  "results": {
    "tool": {"name": "atf"},
    "summary": {"tests": 14, "passed": 13, "failed": 1, "pending": 0,
                "skipped": 0, "other": 0, "start": 1785316462, "stop": 1785316466},
    "tests": [
      {"name": "specs/lists.feature::a list belongs to its owner",
       "status": "failed", "duration": 412,
       "message": "field \"slug\" is \"grocery\", expected \"groceries\"",
       "filePath": "specs/lists.feature", "line": 12}
    ]
  }
}
```

The cost of a registry: a format is a public surface, so a report ATF writes today must keep its
shape tomorrow. ATF pins that promise to CTRF's specification, which is why it ships no format of
its own naming.

- **In CI** — written to a path the pipeline collects: the exit code says pass or fail, the report
  says what.
- **In the editor** — not shown, beyond an export button on a completed run. The editor reads runs
  and history directly.
- **To an agent** — not shown. An agent reads the run object, which is the same data before it was
  narrowed to fit a format.

## Where to go next

- [The command](the-command.md) — every flag that produces or consumes anything on this page,
  including `--report`, `--failed` and `import-run`, with exit codes.
- [Work out why it is red](../how-to/work-out-why-it-is-red.md) — the procedure for turning a
  failing verdict into the line that caused it.
- [Why there is no state file](../explanation/why-there-is-no-state-file.md) — why history records
  runs and never records what an environment holds.
