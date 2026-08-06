# Test a command line

Run the tool under test and claim on the result — on its fields, not on its prose.

## The shortest path

Tell the environment how the tool is invoked. That is one block in
[`atf.yaml`](configure-an-environment.md):

```yaml
    command: { prefix: "python todo.py" }
```

Then run it:

```gherkin
  Scenario: an owner's lists are shown
    Given the todo_list "groceries"
    When I run "todo show primary@example.com"
    Then the result field "exit_code" is "0"
    And the result field "output" contains "groceries"
```

The first word of what you run names the tool; `prefix` says how this environment invokes it. So
`todo show …` is `python todo.py show …` locally and the installed binary in CI, and the feature file
does not change between them.

`result` is the default slot. `exit_code` is the process's exit status; `output` is what the tool
wrote, both streams in the order it wrote them.

## Two runs in one scenario: name the results

`as "…"` puts a run onto a named slot instead of the default.

```gherkin
  Scenario: an added list is shown afterwards
    Given the owner "primary"
    When I run "todo add primary@example.com ideas" as "creation"
    And I run "todo show primary@example.com" as "listing"
    Then the creation field "exit_code" is "0"
    And the listing field "output" contains "ideas"
```

Without the names, the second run overwrites the first and the scenario can only claim about the
last thing it did.

A scenario that needs three slots is usually two scenarios. If the first run is only setup, it
belongs in a [phrase](teach-atf-a-sentence.md) said as a `Given` — or, better, the state it produces
belongs in a declared resource, so ATF arranges it and the scenario acts once.

## Claim on fields, not on prose

```gherkin
    Then the result field "output" contains "Error: no owner ghost@example.com"
```

That claim is about wording. Rewrite the message to `No account found for ghost@example.com — check
the address`, and the suite goes red across several files for a change that broke nothing.

Three answers, in the order to try them.

**Claim on the exit code.** It is the tool's contract and it is not prose.

```gherkin
    When I run "todo add ghost@example.com ideas"
    Then the result field "exit_code" is "1"
```

**Claim on the resource, not on the report of it.** The output is the tool's description of what it
did; the environment is what it did.

```gherkin
  Scenario: adding a list stores it
    Given the todo_list "groceries"
    When I run "todo add primary@example.com ideas"
    Then the result field "exit_code" is "0"
    And the environment has 2 todo_list
```

**When the output is the product, make it structured.** Give the tool a `--json` flag, and the claim
stops depending on layout, ordering of words, colour codes and terminal width:

```python
import json

from atf import claims, then


@then('the listing slugs are "{slugs}"')
def _(listing, slugs):
    payload = json.loads(listing["output"])
    claims.field_is(payload, "slugs", slugs.split(","))
```

```gherkin
    When I run "todo show primary@example.com --json" as "listing"
    Then the listing slugs are "groceries,ideas"
```

Note the cost. The step compares an ordered list, so it is now coupled to the tool's ordering. Say so
in the tool's own tests, sort before comparing, or claim a set.

Adding structured output is a change to the tool under test, not to the suite. The reason CLI tests
are brittle is usually that the tool has no interface except its prose, and the fix belongs in the
tool.

## ATF's own exit codes work the same way

`atf run` exits `0`, `1` or `2`, and everything about *why* travels in the message. A pipeline that
needs the reason takes it from `atf run --json`, which carries a structured error code. A CI step
that greps stderr for `unreachable` is the same mistake as a scenario claiming on `"Error: no owner
…"`. See [Run ATF in CI](run-atf-in-ci.md) for the codes and what to branch on.

## Variations

**A tool with no prefix.** Leave `prefix` out and the first word is run as-is, found on `PATH`.

**A long-running process.** `When I run` waits for the process to exit. Something that stays up is a
`@process` resource, arranged rather than acted.

**Reading the output in Python.** [`shell`](../reference/act.md#shell) is the fixture behind
`When I run`, and returns the same record — see
[write a step in Python](write-a-step-in-python.md).

## When it goes wrong

**"No command configured for this environment"** — the environment has no `command` block. Each
environment configures its own; there is no inheritance between them.

**Exit code 127, or a message from the shell** — `prefix` is wrong for this environment. `atf status
<env>` reports what is reachable before you spend a test run finding out.

**A scenario that passes without doing anything** — a `When I run` whose only claim is on `output`
passes when the tool crashes and prints the expected substring on the way down. Claim `exit_code` in
every scenario that runs something.

**A destructive command against a read-only environment** — `mutable` stops ATF making and removing
resources. It does not stop your command doing whatever it does. Pointing `command.prefix` at
production is your decision.

## Where to go next

- [Write a scenario](write-a-scenario.md) — the rest of the sentences a feature can say without any
  Python.
- [Configure an environment](configure-an-environment.md) — `prefix`, `mutable`, and running the same
  features against a second environment.
- [Assert a record field by field](assert-a-record-field-by-field.md) — claiming several fields of one result.
