# Act

Act is the middle verb: what a test does once its resources exist. Three ways ship, and there are
two ways to add a fourth.

## Changing a field {#action}

A test sometimes has to move a resource **mid-test** — after it has already started acting, because
the ordering is the point. One sentence does that, and nothing is declared for it:

```gherkin
When the task "laundry" field "done" becomes "1"
```

The shape is `When the {type} "{name}" field "{field}" becomes "{value}"`. It is the act-time twin of
the [variation](arrange.md#variation) that says the same thing before a test runs:

```gherkin
Given the task "laundry" but "done" is "1"     # before the test
When  the task "laundry" field "done" becomes "1"   # in the middle of one
```

It reaches the adapter's [`update`](arrange.md#adapter) — so it works for every resource whose
adapter can change one, with no option on the decorator and no extra method to implement. An adapter
with no `update` refuses by name: a page is looked at, not written to.

### A domain verb is a phrase {#domain-verb}

`When the task "laundry" field "done" becomes "1"` says the mechanism. To say the domain, write a
[phrase](../how-to/teach-atf-a-sentence.md) over it:

```gherkin
  @phrase
  Scenario: I complete the task "{name}"
    When the task "{name}" field "done" becomes "1"

  @phrase
  Scenario: I reopen the task "{name}"
    When the task "{name}" field "done" becomes "0"
```

```gherkin
When I complete the task "laundry"
```

The verb lives in the specs, where a reader can see what `complete` means, and it costs no Python at
all. A verb nobody wrote fails at collection with the nearest sentences ATF does know.

### It writes to the system, not through it {#not-through-it}

`becomes` writes to the database. It does not run your application's code for completing a task, so
it proves nothing about that code. Use it where the *state* is the point — a task already done, so
the test can assert on what happens next — and [running something](#running-something) where the
behaviour is.

Changing a field changes the environment, so it needs one that
[may be changed](the-ground.md#may-be-changed). Against an immutable environment the step fails
before it runs, naming the environment that refused.

Whatever a test changed this way is put back when the test ends, so a declaration holds after a test
as well as before it. Every `Given` in a scenario comes before every `When`, so nothing can arrange
over a change this sentence has already made — see [arranging first](arrange.md#arranging-first).

**In CI** — the step runs like any other. A failure names the type, the name it resolved, the field
and what the adapter reported.

**In the editor** — the composer offers the sentence for every field of every arranged resource, and
running it applies the change against the selected environment.

**To an agent** — the sentence is in the legal steps at that position for any resource, with no
per-type vocabulary to look up first.

## Running something {#running-something}

```gherkin
When I run "todo show primary@example.com"
```

The string is a command line. The environment's `command` configuration says what runs it: `prefix`
replaces the first word, so `prefix: "python todo.py"` turns that sentence into
`python todo.py show primary@example.com`. With no prefix the line runs as written.

What comes back is a record, not a blob of text. It carries `exit_code`, the process's exit status
as a number, and `output`, everything the process printed. You assert on those fields:

```gherkin
Then the result field "exit_code" is "0"
Then the result field "output" contains "groceries"
```

`"0"` is written as text and `exit_code` is a number. They compare equal — see
[the comparison rules](assert.md#comparison-rules).

The result lands in the default slot, `result`. A second `When I run` overwrites it unless you say
[`as "name"`](#naming-a-result).

**In CI** — the process runs non-interactively with no terminal attached. Its `exit_code` and
`output` are carried into the report, so a failure is diagnosable from the report alone.

**In the editor** — the fields are shown as fields, and you can re-run the line without re-running
the scenario around it.

**To an agent** — the result comes back as structured fields, so an agent reads `exit_code`
directly instead of parsing what a human would have read.

### `shell` {#shell}

The same act, from Python. `shell` is a [driver](arrange.md#driver), and every driver is a fixture a step or a test can ask for by name. It runs a command
line against the current environment, through that environment's `prefix`, and returns the record
`When I run` puts on a slot: `exit_code`, `output` and `ok`.

```python
def test_show_lists_the_list(groceries: TodoList, shell):
    result = shell(f"todo show {groceries.owner.email}")
    assert "groceries" in result["output"]
```

`shell` is the built-in for testing a command line, and it is what ATF uses to test its own. Ask for
it by name in a pytest function or in [a step you write](#a-step-you-write); nothing is declared to
make it available, because the `command` system is already configured by the environment.

**In CI** — the process runs non-interactively, as `When I run` does. A pytest function and a
scenario asserting the same thing read the same fields and fail on the same values.

**In the editor** — a test that uses `shell` re-runs like any other, against the selected
environment, whose `prefix` decides what the line means.

**To an agent** — Not shown. The vocabulary an agent is served is sentences, and `shell` is reached
from Python.

## Using an interface {#using-an-interface}

There is one way to reach an interface: a real browser. The `@browser.page` system drives it, through the `browser` driver — which a step can also ask for by name — and the
environment says how (`browser: { headless: true }`). There is no headless DOM simulation and no
faster second mode; a browser is slower than an HTTP call and needs a driver installed.

Controls are addressed by role and accessible name. Never by a selector.

```gherkin
When I click the button "Pay now"
When I type "4242 4242" into the textbox "Card number"
When I choose "Express" from the combobox "Delivery"
```

Three sentences: `When I click the {role} "{name}"` clicks the control with that role and accessible
name, `When I type "{text}" into the {role} "{name}"` fills it, and
`When I choose "{option}" from the {role} "{name}"` selects that option in it.

The role is an ARIA role — `button`, `textbox`, `combobox`, `link`, `checkbox`, `heading`, `list`,
`listitem`, `region`. The name is the accessible name: what a screen reader would announce, which is
usually the visible label.

The sentence stays true when the markup is rewritten, because it never mentioned the markup. It
fails when a user could not have found the control either: an unlabelled button is not addressable,
and there is no selector to route around that with.

**In CI** — headless, per the environment's configuration. A failed interaction names the role and
name it looked for, and lists the controls of that role that were on the page.

**In the editor** — the browser opens visibly, so you watch the sentence run against the real
screen.

**To an agent** — the page comes back as an ARIA snapshot, so an agent reads roles and names rather
than markup, and writes the [interface claims](assert.md#interface-claim) that name them.

## Phrase {#phrase}

A phrase is a sentence you add to the suite's vocabulary, written in Gherkin. It is a scenario
tagged `@phrase`, and it is never collected as a test.

```gherkin
@phrase
Scenario: the output contains "{words}"
  Then the result field "output" contains "{words}"
```

The title is the sentence. `{words}` is a placeholder, bound at the call site and usable anywhere in
the body. Saying it looks like any other step:

```gherkin
Scenario: showing an owner's lists
  Given the todo_list "groceries"
  When I run "todo show primary@example.com"
  Then the output contains "groceries"
```

A phrase spans all three verbs, and what its body does decides which keyword says it. A phrase that
arranges is said as a `Given`, one that acts as a `When`, one that claims as a `Then`. One phrase
may do more than one of those.

```gherkin
@phrase
Scenario: a customer who has already paid
  Given the owner "primary"
  And the todo_list "groceries"
  When I complete the task "laundry"
```

A scenario is sentences and nothing else: no tables, no blocks, nothing structured after a `Given`,
a `When` or a `Then`. Anything structured is written as several sentences, and a phrase is what you
write when they repeat. [Asserting a whole record](assert.md#a-whole-record) shows that where a
table would be missed most.

**Phrases may nest.** A phrase's body may say other phrases, to any depth. Nesting hides where a
failure came from, so ATF names the whole chain: the sentence you wrote, the sentence inside it, and
the built-in step that actually failed.

Phrases live anywhere under the `specs` directory named in `atf.yaml`, in one flat namespace. The
file a phrase is written in has no bearing on where it can be said. Two phrases with the same title
anywhere in the suite are a collision, and `atf check` reports it with both files.

A set of phrases is shareable between suites as an ordinary Python package: `.feature` files in a
package, installed with pip. Add it by import name to `specs`, which takes one entry or a list — an
entry that is not a path is imported and its directory used.

```yaml
specs:
  - ./specs
  - atf_checkout_phrases
```

A phrase is a scenario, so everything ATF does to scenarios applies to it: `atf check` validates its
body, `atf docs` renders it, and `atf impact` follows what it touches.

**In CI** — never collected, so a phrase contributes no outcome of its own. A failure inside one is
charged to the scenario that said it and names the phrase and the line within it.

**In the editor** — every phrase in scope is listed with its placeholders, and opening one shows its
body.

**To an agent** — the vocabulary is served as structured data: each phrase's sentence, its
placeholders, and which verbs it may be said as. An agent writes scenarios from sentences that exist
rather than inventing ones that do not.

## A step you write {#a-step-you-write}

When a phrase cannot compose it, write the step in Python. It is an ordinary pytest-bdd step
function.

```python
from atf import claims, when, then

@when("I list the owner's lists")
def _(shell, owner: Owner):
    return shell(f"todo show {owner.email}")

@then('the owner banks with "{iban}"')
def _(owner: Owner, iban):
    claims.field_is(owner, "iban", iban)
```

Arguments follow pytest's rule, unchanged: the name resolves and the annotation types, so
`owner: Owner` in a step means what it means in a test. [`shell`](#shell) is the fixture the
`command` system provides, and it returns the same record `When I run` produces.

What the step returns fills the default slot, so the built-in `Then the result field …` claims work
over what your step returned.

`claims` is a public library, not framework internals: `claims.field_is` raises the message the
built-in sentence would have raised, naming both sides and their kinds. See
[claims as a Python library](assert.md#claims-as-a-python-library) for the full surface.

The decorators come from `atf`. They are pytest-bdd's, with `{…}` placeholder parsing on by
default; pytest-bdd's own `when` and `then` work unchanged if you would rather bring your own
parser.

The cost of a Python step is a function to maintain and a sentence that only a Python reader can
verify. Prefer a phrase where a phrase will do.

**In CI** — indistinguishable from a built-in. The failure message comes from `claims`, so it names
both sides.

**In the editor** — Python steps appear in the vocabulary next to built-ins, with the file and line
they are defined at.

**To an agent** — exposed in the same vocabulary, with their placeholders, so an agent can say a
step you wrote.

## Naming a result {#naming-a-result}

Every act writes its result to a slot. The default slot is `result`.

```gherkin
When I run "todo show primary@example.com"
Then the result field "exit_code" is "0"
```

A second act overwrites `result`. When a test does two things and asserts on both, name them:

```gherkin
Scenario: adding a list then showing it
  Given the owner "primary"
  When I run "todo add primary@example.com groceries" as "creation"
  And I run "todo show primary@example.com" as "listing"
  Then the creation field "exit_code" is "0"
  And the listing field "output" contains "groceries"
```

The name takes the place of `result` in every claim over a slot. Names are per scenario and free of
any other namespace. Use `as` only when a test does two things.

**In CI** — the slot name appears in failure messages, so a two-act test says which act it is
complaining about.

**In the editor** — each slot is listed with its fields after the run, named as you named it.

**To an agent** — results come back keyed by slot name.

## Where to go next

- [Assert](assert.md) — every claim ATF ships, including the ones over a slot the acts on this page
  filled.
- [Arrange](arrange.md) — where the resources these sentences name come from, and how a name
  resolves to a record.
- [Extending ATF](extending-atf.md) — writing the adapter that makes `act` available to a new
  system in the first place.
