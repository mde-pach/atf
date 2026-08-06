# Teach ATF a sentence

A [phrase](../reference/act.md#phrase) gives your suite its own vocabulary, written in Gherkin, with
no Python. Because [a scenario is sentences and nothing else](write-a-scenario.md#the-rule), it is
also the only compression a feature file has.

## The shortest path

Write a scenario, tag it `@phrase`, and put it anywhere under `specs:`:

```gherkin
@phrase
Scenario: the output contains "{words}"
  Then the result field "output" contains "{words}"
```

Now every feature in the suite can say it:

```gherkin
  Scenario: an owner's lists are shown
    Given the todo_list "groceries"
    When I run "todo show primary@example.com"
    Then the output contains "groceries"
```

A phrase is never collected as a test. It is a body of steps with a title, and the keyword you say it
with follows what the body does: one that arranges is said as a `Given`, one that acts as a `When`,
one that claims as a `Then`.

## Four uses

### 1. Alias a step, so the feature stops carrying a field name

```gherkin
@phrase
Scenario: the command succeeded
  Then the result field "exit_code" is "0"

@phrase
Scenario: the command was refused
  Then the result field "exit_code" is "1"
```

```gherkin
    When I run "todo add ghost@example.com ideas"
    Then the command was refused
```

The cost is a layer of indirection: a reader who wants to know what "refused" means has to find the
phrase. It pays when the alias appears in a dozen scenarios, or when the underlying detail is likely
to change. It does not pay for a sentence said once.

### 2. Collapse a set of claims into the thing it means

A record is claimed one field per sentence. When the same fields are claimed together scenario after
scenario, the set is a concept nobody has named.

```gherkin
@phrase
Scenario: the account is set up the way a new customer should be
  Then the account "primary" field "plan" is "free"
  And the account "primary" field "seats" is "1"
  And the account "primary" field "trial_ends_at" is #datetime
```

```gherkin
    Then the account is set up the way a new customer should be
```

The three claims said what the values are; the phrase says why they matter. See
[assert a record field by field](assert-a-record-field-by-field.md) for the claims themselves.

### 3. A compound arrange

Three lines of setup that always travel together become one line that says what the setup is *for*.

```gherkin
@phrase
Scenario: a customer who has already paid
  Given the owner "primary"
  And the todo_list "groceries"
  When I complete the task "laundry"
```

```gherkin
  Scenario: a paid customer sees their receipt
    Given a customer who has already paid
    When I run "todo show primary@example.com"
    Then the command succeeded
```

That phrase contains a `When` and is said as a `Given`. Getting to the state you want takes acting;
the scenario using it should not have to show the acting.

### 4. Nest phrases

A phrase may say another phrase, to any depth.

```gherkin
@phrase
Scenario: a customer who has already paid, with a second list
  Given a customer who has already paid
  And the todo_list "ideas"
```

A failure five levels down still names the sentence you wrote: the innermost step that failed is
reported with the chain of phrases that led to it. Cycles are an error, found by `atf check`.

## Captures

Braces in the title name a capture. The same name in the body is replaced by what was said.

```gherkin
@phrase
Scenario: the todo_list "{name}" belongs to "{email}"
  Then the todo_list "{name}" field "slug" is "{name}"
  And the owner "{email}" exists
```

A capture arrives as text, and matches up to the closing quote of the value it stands in. A phrase may
take several. The names are yours, and they must agree between the title and the body. A capture
named in the body but not in the title matches nothing and is an error at `atf check`.

## Where phrases live

Anywhere under `specs:`, in any `.feature` file, at any depth. Directories organise them; they do not
scope them. Every phrase in the suite is in **one flat namespace**.

The cost of a flat namespace is collisions. Two phrases with the same title, in different
directories, are an error naming both files rather than a silent shadow. Name a phrase for the domain
it belongs to — `a customer who has already paid`, not `setup`.

## Share a vocabulary between suites

Phrases ship as an ordinary Python package. Put the `.feature` files in the package, and name the
package in `specs:`:

```yaml
specs: [./specs, checkout_vocabulary]
```

A name that is not a path is resolved as an installed package, and its phrases join the same flat
namespace as yours. An imported phrase is said exactly like a local one, and can be nested inside one.

The trade-off: the phrase titles become an API. Renaming `a customer who has already paid` breaks
every suite that says it, as "no sentence matches" in a repository whose owners changed nothing.

## When it goes wrong

**"No sentence matches …"** — the scenario is missing its `@phrase` tag, or its file is outside every
path in `specs:`. A phrase file that is collected but untagged shows up differently: as a test that
runs and probably fails.

**Two phrases with the same title** — `atf check` names both files. Rename one; there is no
precedence rule, deliberately.

**A phrase that needs to compute something** — Gherkin has no expressions, and a phrase is Gherkin.
When you want arithmetic, a loop or a value from outside the suite,
[write a step in Python](write-a-step-in-python.md) instead.

## Where to go next

- [Write a step in Python](write-a-step-in-python.md) — for the part a phrase cannot express, with
  failure messages as good as a built-in's.
- [Write a scenario](write-a-scenario.md) — the sentences you get before teaching ATF any of your
  own.
- [Act](../reference/act.md#phrase) — how a phrase resolves against the built-in grammar.
