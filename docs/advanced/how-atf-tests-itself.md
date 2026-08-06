# How ATF tests itself

ATF's own test suite is an ATF suite. Its manifest is `atf.yaml`, its resources are declared in
`resources.py`, its tests are scenarios, and the system it points at is ATF. There is no second
harness underneath.

This is the strongest claim the project makes, so the page shows the suite rather than describing
it. Every file is here, whole.

## The premise

A test framework that tests itself with something else is telling you what it thinks of its own
model. ATF does not have that option: the graph, the reconciliation, the scopes and the two surfaces
are the product, and the only way to exercise them under real load is to use them.

So the suite arranges a workspace — an ATF suite scaffolded on disk — starts `atf edit` over it,
opens a page of that editor in a browser, and drives the `atf` command against it. Three of ATF's
four systems appear in one closure, and the fourth runs the commands.

The recursion is real and it stops one level down. The scaffolded workspace is a small, ordinary
suite with resources and a spec of its own. ATF's suite makes it exist, runs ATF against it, and
claims on what came back.

## The suite, whole

```text
atf/
  pyproject.toml
  atf.yaml                        # the suite's manifest
  src/atf/                        # the system under test
  tests/
    resources.py                  # workspace, editor, screen
    vocabulary.py                 # one claim, one check
    test_status.py                # the same question, asked in Python
    specs/
      phrases.feature
      making-resources.feature
      lifetimes.feature
      the-editor.feature
  .workspaces/                    # written by the suite, ignored by git
```

Nothing in that tree is special to ATF. It is the layout of
[chapter 1's todo suite](../tutorial/1-run-a-suite.md) with a `tests/` directory in front of it,
because the product and its suite live in one repository.

### `atf.yaml`

```yaml
resources: [./tests/resources.py]
specs: ./tests/specs
extensions: [./tests/vocabulary.py]
default_env: local

environments:
  local:
    mutable: true
    filesystem: { root: ./.workspaces }
    process:    { cwd: ./.workspaces/suite }
    command:    { prefix: "uv run atf --config .workspaces/suite/atf.yaml" }
    browser:    { base_url: "http://127.0.0.1:8765" }

  ci:
    mutable: true
    filesystem: { root: ./.workspaces }
    process:    { cwd: ./.workspaces/suite }
    command:    { prefix: "uv run atf --config .workspaces/suite/atf.yaml" }
    browser:    { base_url: "http://127.0.0.1:8765", headless: true }
```

Three systems are in play and each is configured once per environment. `filesystem` says where
workspaces are written. `process` says where a process starts. `command` says how `atf` is invoked —
`uv run` because the suite runs against the working tree, and
[`--config`](../reference/the-command.md#global-flags) because the workspace under test is not the
directory the suite runs from.

Both environments are `mutable: true`. The suite writes directories, starts processes and removes
both, and [`mutable` is false unless stated](../reference/the-ground.md#may-be-changed), so it has
to be said. Neither environment touches anything anyone else owns: `./.workspaces` is scratch space
inside the checkout.

The two environments differ in one setting. Nothing is inherited between them, so the other four
blocks are written out twice. That is the cost of environments that cannot silently disagree, and it
is paid here like anywhere else.

`extensions:` names one file. It registers a claim and a check — **and no adapter.** The next
section says why that is the point rather than an omission.

### `tests/resources.py`

```python
from atf import browser, filesystem, process

SUITE = {
    "atf.yaml": """\
resources: [./resources.py]
specs: ./specs
default_env: local

environments:
  local:
    mutable: true
    filesystem: { root: . }
  readonly:
    filesystem: { root: . }
""",
    "resources.py": """\
from atf import filesystem


@filesystem(path="notebooks", unique_by="name")
class Notebook:
    name: str


@filesystem(path="notes", unique_by="name")
class Note:
    notebook: Notebook
    name: str


@filesystem(path="drafts", unique_by="name", scope="function")
class Draft:
    name: str


work    = Notebook(name="work")
standup = Note(notebook=work, name="standup")
scratch = Draft(name="scratch")
""",
    "specs/notes.feature": """\
Feature: notes

  Scenario: a draft is arranged for one test
    Given the draft "scratch"
    Then the draft "scratch" exists
""",
}


@filesystem(path="suite", unique_by="name", scope="function")
class Workspace:
    """An ATF suite on disk: a manifest, a resources module and a spec."""

    name: str
    files: dict[str, str]


@process(command="atf edit --port 8765", unique_by="workspace", scope="function")
class Editor:
    """An `atf edit` process serving one workspace."""

    workspace: Workspace


@browser(when_absent="observe", unique_by="path", scope="function")
class Screen:
    """A page of that editor."""

    editor: Editor
    path: str


scaffolded = Workspace(name="scaffolded", files=SUITE)
editing    = Editor(workspace=scaffolded)
catalogue  = Screen(editor=editing, path="/catalogue")
```

Read the last three lines upwards and the whole design is in them.

`Workspace`
:   A directory under the `filesystem` root. `files` maps a path inside it to that file's contents,
    and the contents are a complete little ATF suite: two resources with lineage between them, one
    scoped to a single test, two environments of which one may not be changed. Everything ATF's
    scenarios need to observe is declared there.

`Editor`
:   A running `atf edit`, recognised by the workspace it serves. The command is fixed, so it is an
    [option](../reference/the-ground.md#settings) on the decorator; the thing that varies is the
    workspace, and that is a field.

`Screen`
:   A page of that editor. `when_absent="observe"` says ATF does not make a screen — a page that
    does not answer is a failure with a reason, never an attempt to create one. See
    [require something you cannot create](../how-to/require-something-you-cannot-create.md) for the
    other half of that idea.

The lineage is the two typed fields. `Screen.editor` is an `Editor`; `Editor.workspace` is a
`Workspace`. Nobody writes the chain out anywhere else, and one sentence pulls the whole of it:

```gherkin
    Given the screen "catalogue"
```

That writes three files to disk, starts a process, waits for the port and opens a page — in that
order, derived from the fields. Teardown runs the reverse: the page closes, the process is stopped,
the directory is removed. See [depend on another resource](../how-to/depend-on-another-resource.md)
for the rule, and [scope](../reference/arrange.md#scope) for why all three are `function`.

Every resource here is function-scoped, so the suite leaves nothing behind at all. That is unusual —
[`persistent` is the default](../reference/arrange.md#scope) — and it is deliberate: a workspace
that survived would be found by recognition on the next run and tested instead of being made.

### `tests/vocabulary.py`

```python
from atf import check, claim

SUBCOMMANDS = {"init", "status", "make", "run", "check", "docs", "edit", "impact", "unused"}


@claim('the {result} lists "{first}" before "{second}"')
def _(result, first, second):
    lines = result["output"].splitlines()
    at = {name: next((i for i, line in enumerate(lines) if name in line), None)
          for name in (first, second)}
    if None in at.values():
        return False, f'the output names neither "{first}" nor "{second}"'
    return at[first] < at[second], f'"{second}" was listed first'


@check("every scenario names the subcommand it exercises")
def _(suite):
    for scenario in suite.scenarios:
        if not SUBCOMMANDS & set(scenario.tags):
            yield scenario, f"no subcommand tag; expected one of {', '.join(sorted(SUBCOMMANDS))}"
```

The claim exists because ordering is what the suite is checking and `contains` cannot see it. It is
a claim rather than a [marker](../reference/assert.md#marker) because it is about a record — the
whole of one result slot — and not about a value.

The check is ATF's own convention, enforced by the same `atf check` that enforces ATF's. A scenario
in this suite that does not say which subcommand it drives is a finding, and
[`atf check` exits `1`](../reference/the-command.md#check) on it. See
[registering a check](../reference/extending-atf.md#registering-a-check).

### `tests/specs/phrases.feature`

```gherkin
@phrase
Scenario: the command succeeded
  Then the result field "exit_code" is "0"

@phrase
Scenario: the command refused, saying "{code}"
  Then the result field "exit_code" is "2"
  And the result field "output" contains "{code}"
```

Two sentences of ATF's own vocabulary, written in Gherkin and needing no Python. The second one is
the project's exit-code contract said once: coarse code, reason in the message. Every scenario that
expects a refusal reads that contract rather than restating it, so a change to the contract is a
change to one file. [Teach ATF a sentence](../how-to/teach-atf-a-sentence.md) is the guide.

### `tests/specs/making-resources.feature`

```gherkin
Feature: making what a suite declares

  @make
  Scenario: a dependency is made before the resource that names it
    Given the workspace "scaffolded"
    When I run "atf make local"
    Then the command succeeded
    And the result lists "Notebook" before "Note"

  @make
  Scenario: an environment that may not be changed makes nothing
    Given the workspace "scaffolded"
    When I run "atf make readonly --json"
    Then the command refused, saying "environment_immutable"
```

The first scenario is the thesis under test. The scaffolded suite declares `Note.notebook: Notebook`
and nothing else, and ATF is required to derive the order from that field alone.

The second is the safety property. `readonly` states no `mutable`, so it is false, and `atf make`
must refuse before it touches the directory. `--json` is there because the scenario claims on the
structured code rather than the wording — the same discipline
[test a command line](../how-to/test-a-command-line.md#claim-on-fields-not-on-prose) asks of any
suite driving a CLI.

### `tests/specs/lifetimes.feature`

```gherkin
Feature: what a run leaves behind

  @run
  Scenario: a resource scoped to one test is gone when the run ends
    Given the workspace "scaffolded"
    When I run "atf run" as "testing"
    And I run "atf status local scratch" as "afterwards"
    Then the testing field "exit_code" is "0"
    And the afterwards field "output" contains "absent"
```

Two runs in one scenario, so both are named. The inner suite's `Draft` is `scope="function"`, its
one scenario arranges it, and the environment must not be holding it afterwards.

`atf status` is the right question here because it never gates: it reports absence as information,
so a scenario can claim on the answer.

### `tests/specs/the-editor.feature`

```gherkin
Feature: the editor shows the same graph

  @edit
  Scenario: the catalogue lists what the suite declares
    Given the screen "catalogue"
    Then the heading "Catalogue" is showing
    And the words "Notebook" are showing
    And the words "Note" are showing
```

One `Given` and the whole closure exists. The claims are by role and accessible name, never a
selector, exactly as in [test a web interface](../how-to/test-a-web-interface.md).

This scenario is what stops the editor drifting from the command. Both surfaces read the same
engine — [one engine, two surfaces](../explanation/one-engine-two-surfaces.md) — and the way to keep
that true is a test that fails when the catalogue stops showing what `atf status` reports.

## There is no backend, and that is the point

ATF ships four systems: `command`, `browser`, `filesystem` and `process`. Look at what the suite
above uses. All four, and nothing else. The suite registers a claim and a check under `extensions:`
and no adapter at all, because there is no system ATF needs to test itself that ATF does not already
ship.

That is the test of the four. If the self-test suite had to write a fifth adapter to do its job, the
four would be the wrong four.

There has never been a fake backend to point ATF at, and building one would answer a question nobody
asked. A stub says the framework works against a stub. A command line, a browser, files on disk and
a running process are what teams already have, and they misbehave in the ways real things
misbehave — a port that is slow to bind, a directory that is not empty, a process that exits before
it is asked to.

**`@sqlite` is not part of ATF.** It appears on nearly every page of this documentation because the
tutorial's suite is a todo app over SQLite, and that suite writes its own `adapters/sqlite.py` and
names it in `extensions:`. It is the worked example of an adapter, not a component. ATF's own suite
does not import it and does not need it. See
[teach ATF a new system](../how-to/teach-atf-a-new-system.md) for the file you have been using since
the first page.

## `shell`, and testing a command line with the built-in for testing command lines

`When I run "atf make local"` is the `command` system. The first word names the tool, `prefix` says
how this environment invokes it, and what comes back is a record with `exit_code`, `output` and
`ok`. ATF tests its own CLI with the thing it ships for testing anybody's CLI. There is no private
door.

The same record is available in Python through `shell`, the fixture behind `When I run`:

```python
# tests/test_status.py
from tests.resources import Workspace


def test_status_reports_a_draft_as_absent(scaffolded: Workspace, shell):
    result = shell("atf status local scratch")
    assert result["ok"]
    assert "absent" in result["output"]
```

`scaffolded: Workspace` arranges the directory before the test, by the same graph the scenario uses.
The name resolves and the annotation types, so a pytest function and a scenario ask for a resource
the same way and compile to the same thing.

Both forms are in this suite on purpose. A scenario is the better artefact when the sentence is
worth reading; a Python test is the better one when the claim needs arithmetic. Neither is a
fallback for the other.

## A green suite proves nothing unless it can go red

A self-test that cannot fail is decoration. The only way to know whether these scenarios watch
anything is to break the framework on purpose and require the matching scenario to notice.

Three mutations, each aimed at one scenario:

Remove the topological sort from provisioning
:   `a dependency is made before the resource that names it` must fail on the ordering claim.

Make teardown a no-op for `function` scope
:   `a resource scoped to one test is gone when the run ends` must find `scratch` present.

Let `atf make` proceed against an environment that is not `mutable`
:   `an environment that may not be changed makes nothing` must go from exit `2` to exit `0`.

Apply one, run the suite, and read which scenarios went red.

**A mutation that turns the whole suite red proves nothing.** It means the scenario meant to catch it
never reached its claim, and the run says only that ATF is broken — which you already knew, because
you broke it. What you want is one named failure and the rest still green. When that does not happen,
the scenario is standing too far downstream; move the claim closer to the thing it is about.

The scenarios above were written this way round: break it first, then write the sentence that names
the breakage.

## Run the suite twice to trust cleanup

```console
$ atf run && atf run
```

One green run says nothing about residue. Teardown does not fail where it is skipped; it fails later,
in a stranger's test, on a run nobody connected to the change — and it reads as flakiness until
somebody proves otherwise.

Know what you are hunting.
[`persistent` is the default](../how-to/make-something-fresh-for-each-test.md), so a record still
there tomorrow is usually correct: that is what makes re-runs cheap and recognition worth having.
Expected residue is not a leak. **The leak is a `function` or `session` resource that outlived its
scope.**

For this suite the second run is unusually sharp, because every resource in it is function-scoped and
the environment should be empty when the run ends:

```console
$ atf run
$ atf status local
absent     Workspace   scaffolded
absent     Editor      editing
absent     Screen      catalogue
```

Anything `present` on that listing is a directory left on disk or a process still holding the port,
and the next run will fail somewhere that has nothing to do with it.

There is a cost, and it is the reason to know about it before it bites: the editor binds a fixed
port and the workspace is a fixed directory, so this suite does not run two copies of itself at
once. A second `atf run` started while the first is going fails in innocent-looking places. Run them
in sequence.

## The honest cost

A suite written as scenarios diagnoses badly when the framework itself is broken.

A unit test on the provisioning order fails alone and names the function. Its equivalent here —
`a dependency is made before the resource that names it` — fails through a workspace on disk, a
subprocess, a manifest parse and an exit code. When the graph is broken, all four of those break, so
every scenario in the suite goes red at once and the report points at the sentences rather than at
the cause. The first minutes of a bad run are spent working out which failure is the real one.

Some of that is recoverable. The mutation discipline above buys back the mapping from cause to
scenario, one break at a time, and `atf check` catches the malformed-suite class before anything
runs. The rest is a real cost, accepted for a real reason: a suite of unit tests over ATF's
internals would test the internals and say nothing about whether the model works, and the model is
the thing that could be wrong.

## Where to go next

- [One engine, two surfaces](../explanation/one-engine-two-surfaces.md) — why the editor scenario
  above is load-bearing rather than a nicety.
- [Extending ATF](../reference/extending-atf.md#first-client) — the rule behind the missing adapter:
  every built-in is registered through the same five registries a suite uses.
- [Make something fresh for each test](../how-to/make-something-fresh-for-each-test.md) — the two-run
  check and the post-run `atf status`, as a task rather than a discipline.
