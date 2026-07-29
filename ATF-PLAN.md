# ATF — where the work is

Working tracker. `ATF-TARGET.md` is the spec; this is the state of play. Both are untracked scratch
and get deleted when the work closes.

**The goal, as restated on 2026-07-28:** ATF's tests are an ATF suite, they live in `tests/`, and
nothing references "selftest". This is *not* a port — fidelity to the old unit tests is not the bar,
and coverage may be lost where losing it makes the suite better.

---

## Where things stand

**Branch `readable-specs`, 29 commits.** All gates green: `uv run ruff check`, `uv run ty check`,
`uv run pytest -q`, `uv run mkdocs build --strict`, `examples/todo`, and
`ATF_MANIFEST=tests/atf.yaml uv run python -m atf.cli lint`.

**151 scenarios, ~465 Python tests.** Started at 21 scenarios and 573 Python tests.

`selftest/` is deleted. `tests/` is a consuming project — `atf.yaml`, `catalog/`, `specs/`,
templates under `suites/` — and one `pytest` run covers the scenarios and the Python tests together.

### The framework: eleven of thirteen changes from the target's Part 5

| Done | What it bought |
|---|---|
| C1 records at the seam | a step may return a dataclass, so the seam stops forcing hand-written `@then`s |
| C2 any slot, not only `result` | a scenario with two actions can claim something about both |
| C3 matchers | `contains`, `is empty`, counts — `the output mentions …` stopped being a suite's own step |
| **C4 the phrasebook** | the missing layer between a domain sentence and a primitive claim |
| C5 `atf lint` | the one rule of the model that can be checked by machine |
| C6 data tables | inline variation and whole-shape claims with `#markers` |
| C7 `mode: data` | an observation is not a precondition |
| C8 catalog `actions:` | **§3.1 answered** — a scenario can act on a system, not only read one |
| C9 browser adapter | role and accessible name, inline; no selector in any catalog |
| **O16 `html` adapter** | the same claims, read from the response — no browser, no selectors anywhere |
| C10 `Rule:` | Example Mapping's middle card, in the file |
| C11 auto-collection | a feature needing no code needs no file beside it |
| C12 skip-when-unavailable | a system this machine has not got skips, saying what is missing |

| C13 `atf run -k/--tag/--failed/--json` | the dev loop: narrow it, repeat what failed, hand it to CI as CTRF |
| C14 `atf docs` | the features as pages, carrying what the last run said — the thing Pickles cannot do |
| C16 `Given a fresh <resource>` | **O2 answered**: the spec says isolation, the catalog stays quiet |

**Not started:** C15 introspection + MCP, C17 `atf import openapi`. C18 is parked by the target.

**Both findings the target opens with are closed.** §3.1 by C8. §3.2 by C4 and C5 — and
`cockpit.feature`'s lint waiver, which the target called its best evidence that generic vocabulary
is not readable vocabulary, is gone.

### The suite: what is left in Python

The split has held every time. A module's **behaviour** becomes scenarios; what stays is a
**decision procedure over data** — a table, a registry, a memo, a streak — where a unit test is the
better description. Each residue module's docstring says which it is and why.

| Module | n | Verdict |
|---|---:|---|
| `test_cockpit.py` | 50 | **done.** What the interface shows is scenarios; what is left is pure functions, HTTP contracts, and states needing a run |
| `test_accessible.py` | 43 | **new, keep.** Markup in, role and name out — a decision procedure |
| `test_compose.py` | 58 | **keep, and the docstring says why.** Every test posts a draft: a request, a decision and a file on disk, none of it a page |
| `test_authoring.py` | 27 | **keep.** Every test is a write, or a write being refused |
| `test_discovery.py` | 42 | mostly convert — the cockpit's pages *are* discovery's output |
| `test_runner_jobs.py` | 32 | convert — the activity dock and `atf run` |
| `test_rest_adapter.py` | 28 | convert — a workspace whose catalog exercises the seams |
| `test_steps.py` | 42 | **trimmed.** Keeps `PASSING`: every generic `Then` paired with a line that holds |
| `test_phrasebook.py` | 22 | convert the running half; the loader is a pure function |
| `test_context.py` | 21 | partly — held slots reach the run report |
| `test_engine.py` | 17 | **keep.** A graph, a memo, a registry, an adapter told to misbehave |
| `test_store.py` | 16 | **trimmed.** Keeps pruning, flakiness, streaks |
| `test_compare.py` | 15 | convert as a Scenario Outline truth table |
| `test_acceptance.py` | 12 | keep, or convert with a source-rule adapter (grep as a data source) |
| `test_providers.py` | 10 | **trimmed.** Keeps the registry |
| `test_placeholders.py` | 7 | **keep** with `compare` — a pure decision procedure |
| `test_example.py` | 5 | **keep.** A claim about the repository, not the framework |
| `test_plugin.py` | 5 | **keep.** Fixtures and skips no scenario can watch |
| `test_mutations.py` | 4 | **keep.** A green suite proves nothing unless it can go red |
| `test_command_adapter.py` | 11 | **keep.** What raises before a claim can be made — nothing to run, nowhere to run it, no such program |

Deleted outright: `test_lint.py`, `test_collect.py`, `test_cli.py`, `test_config.py`,
`test_catalog.py`, `test_materializer.py`, `test_bootstrap.py`.

**The cockpit trio is settled.** The conversion boundary turned out not to be a matter of taste:
what a page *shows* is a scenario, and what needs a POST is not — a page resource only ever GETs, so
that nothing which reads the interface can change it. `test_cockpit.py` lost its page-rendering half
(now 14 scenarios); `test_compose.py` and `test_authoring.py` keep almost everything, because every
test in them posts a draft or writes a file. Both docstrings now say so.

---

## Open questions

| # | Question | Needed by |
|---|---|---|
| ~~O1~~ | ~~Phrasebook as YAML, or a `Phrase:` block?~~ | **settled — YAML stays**, see below |
| ~~O2~~ | ~~Should a spec *say* isolation?~~ | **settled by C16 — the spec says it**, see below |
| O3 | Do `Question` cards (Example Mapping's red cards) belong in ATF, or is that product scope creep? | C15 |
| O10 | Should `atf lint` check scenario titles? It checks step lines only | any time |
| O12 | A phrase cannot stand for a step that takes a table — the executor passes no `datatable` | when someone asks |
| O13 | Should the composer learn to build a table, so shape claims stop being hand-written? | C15 |

---

## Decisions that still constrain the work

Things a future change would be wrong to undo.

**The model**

- **A `command` adapter ships, overturning the target's Part 7.** That rejection said *"run a
  command is exactly the third-party action the philosophy accepts as needing code; sugar in the
  core is how frameworks get fat."* It conflated two things: running *the deploy script with these
  flags* is a domain action and is project code, but *a command-line program* is a class of system —
  argv, cwd, environment, exit code, two streams — exactly as a JSON API is. ATF ships adapters for
  classes of system. C9 settled it by precedent: driving a browser is far more third-party than
  spawning a subprocess, and that shipped. The measured cost of the rejection was 111 lines in this
  suite alone, written again by every suite that tests a CLI.
- **The adapter answers `ok`.** "How do you know it failed?" is a question about commands, not about
  any one project, so it is answered once rather than in every phrasebook.
- **A command resource is one invocation**, so it is ephemeral: `find` has nothing to answer and
  `create` runs it.
- **`When I run "atf seed local"` is the reading surface, and ATF ships it.** The first cut made a
  command a resource you varied — `Given the command "atf" but: | args | seed local |` — which is
  unreadable: nobody would understand `args seed local`, and a person invoking a CLI recognises the
  command line they would type. A command line is therefore **one string**, split the way a shell
  splits it. A node is still allowed (`body: {command: …}`) for a command some *other* resource
  depends on having been run, but most suites want none.
- **The command's cwd and environment are settled where the suite is built, not said per line.**
  In `tests/`, `aim_the_command_at` points the `command` system at the workspace the scenario just
  provisioned. That is what let this suite's four hand-written `When`s become ATF's own step plus
  three narrow variants, each saying only *where* it stood or what was *exported*.

- **O1 is settled: YAML stays, and its one sharp edge is gone.** The case against it was that a
  colon followed by a space starts a mapping, so `contains "registered: env, now"` loaded as a dict
  and `"flag: true"` came back a boolean. Steps are now read from the YAML *document tree* rather
  than from loaded values, so both come back as the lines they were written as. The footgun is
  taken away rather than labelled, and no line needs quoting it did not ask for.

- **A phrase stands for steps, never another phrase.** Flat, one level, refused at load. The guard
  against a phrasebook becoming a badly designed programming language.
- **A phrase runs its steps as the kind of step it was said as.** Letting one mix a `When` into a
  `Then` would hide an action inside an assertion.
- **A phrase is a real step definition, not a pre-parse rewrite.** Expanding before pytest-bdd
  parsed would be less code, but the report would show four primitive steps where the file shows one
  sentence. Cost: `phrasebook.py` imports four pytest-bdd internals, in one commented block.
- **`reference` blocks when absent; `data` does not.** An observation is not a precondition, and
  conflating them would make every page a scenario reads into something the environment must satisfy.
- **`delete` is ATF's own** and a type may not declare an action by that name. Two different things
  by one word is worse than either.
- **An action's body is adapter configuration.** ATF checks its shape and reads nothing into it —
  reading into it would be the framework deciding what a system can do.
- **No catalog holds a selector.** A control is named by role and accessible name, inline. A node
  per control is a Page Object with a YAML file for a class.
- **A variation is a copy of the node, never the node.** `self.nodes` is session state every other
  scenario reads.
- **A shape says what must *match*, not what may exist.** `#absent` recovers the only case the
  looser reading loses.

**The dev loop and the documentation**

- **`-k` matches what a person types.** A scenario has a title, so someone wanting to run "A list
  belongs to its owner" types its words — which reach pytest as `on its own` and come back as a
  parse error about column 4. A plain phrase is flattened the way pytest-bdd flattens a title; an
  expression (`and`/`or`/`not`/brackets) passes through untouched.
- **Several `--tag`s mean any of them**, and `@` is dropped, as `requires:` already has it.
- **`--failed` with nothing failed exits 0; with nothing ever run it exits 2.** A green suite must
  not look broken, and silently running everything would misrepresent what was asked.
- **`--json` is CTRF, not a shape of ATF's own.** A format nobody else reads has to be taught to
  every consumer. An `error` is reported as `failed`: a gate treating "it broke before it started"
  as softer lets a broken suite through.
- **`atf docs` reads the feature files and the run store, and nothing else** — the same seam
  `atf lint` holds. Documentation you cannot build in a checkout with no backend near it stops
  being built. Plain CommonMark, no admonitions, so a page renders in four places. **No `--check`**:
  the verdicts come from history on the machine that ran the tests, so a staleness gate would fail
  for the one reason that is not the author's fault.

**Having one to yourself**

- **O2 is settled: the spec says isolation and the catalog stays quiet.** `lifecycle: ephemeral` is
  a fact about a resource *nobody* can share; wanting one to yourself is a fact about a *scenario*,
  and the type is usually one other scenarios happily share.
- **Identity comes from the natural key**, with a discriminator appended to each key field written
  as text of its own. A key field holding a reference is the link to the parent and is left alone.
  Because the key is genuinely unique, a fresh instance is **read back live** like anything else.
- **No cascade** — that is the all-or-nothing model this exists to escape — but a node a scenario
  already has its own of is handed back to a later dependent, so a chain reads a line per link.

**`atf lint`**

- **Step lines only** — not narrative, not comments, and **not tables**, deliberately: the rule is
  aimed at technical detail embedded in a sentence, and flagging tables would push suites back to
  the one-claim-per-field that whole-shape matching replaces.
- **Waivers are comments in the feature file**, so the reason lives beside the line it excuses, and
  apply to the line directly beneath and no further.

**The composer**

- Offers slot claims only over slots a **step** produced, never a `Given`'s record — a resource claim
  re-reads live and a slot claim does not.
- Does not offer a step that takes a table: it cannot write the table, and offering a line it cannot
  finish is worse than not offering it.
- Writes **no binding module at all**. Every step it offers a new feature is one such a feature can
  already reach, and ATF collects unbound features.

**The suite**

- **No selector survives anywhere.** O16 shipped: `atf.accessible` reads role and accessible name
  out of the HTML a server sent, and the `html` adapter serves the same `Showing` protocol the
  `browser` adapter does. `element` and its eleven selector-carrying nodes are gone, as is the
  suite's own CSS engine. A claim now means one thing and costs two different amounts.
- **Reading is generic; acting needs a browser.** `controls`/`says` are on the protocol; click and
  type are not, because reading a response can never do them and pretending otherwise would make a
  suite quietly weaker on a machine with no browser.
- **Which system a claim is about is settled by the `Given` that opened a page**, noted on
  `context._showing` by the plugin. A suite may configure both, and no sentence has to say which.
- **An `aria-hidden` subtree is not part of an accessible name.** Found by dogfooding: the cockpit's
  rail marks its glyphs hidden and ATF read them anyway, so every link was called `◎ Overview`. A
  name is computed from what a person can *read*, not from the raw text.
- **`plugin.py` may not import `atf.steps`.** It registers it as a pytest plugin, and pytest rewrites
  a plugin's assertions only if it gets there before the module is imported — so importing it warns
  every consuming suite on every run. The provisioning steps write their patterns out as literals
  for exactly this reason; `steps.py` keeps the constants for the composer.
- **A landmark is not named by what is inside it.** `nav` wrapping the menu is called nothing, not
  "Catalog Compose Runs" — otherwise `the region "…"` matches whatever happens to be in one today.
- **A scenario may never depend on an ambient variable.** Two scaffolded-suite scenarios passed
  alone and failed under the full suite because they inherited an `ATF_ACTOR` the unit test they
  replaced had set explicitly.
- **A negative claim is worth doubting until its positive twin is green.** `the option "the
  todo_list" is not showing` passed because no option was called that at all.

---

## Limitations of the vocabulary, found by using it

- **A `@when` in `tests/specs` may not also be a `@given`.** The dogfood guard forbids a hand-written
  `@given` or `@then` anywhere under `specs/`, which is right — but it means a precondition the suite
  genuinely owns (what the developer had exported) has to be said on the action instead.

- **A claim's value cannot contain a double quote** — it is captured between them. A message reading
  `is "standard", not "enterprise"` has to be checked by naming the parts around the quotes.
- **`atf run` reports one line per failure.** Enough for a claim's message, which is one line by
  design. A scenario wanting more of a traceback has nowhere to read it from.
- **Prose has no accessible name.** ARIA computes one for things you can act on; `the words "…"` is
  the claim about what a page says.
- **There is no count claim about an interface.** Converting the cockpit's element assertions cost
  two of them: "the composer offers Save and never a badge" lost its negative half (a decorative
  `span` has no role to name), and "three steps shown as Gherkin" became a claim about the keyword
  and the line rather than a count of three. Both were markup assertions, and that was the forecast
  price. Add `there are {count:d} …` only when a real scenario needs it, not on speculation.

---

## Found on the way, not fixed

- **`atf init` inside a suite that already exists leaves it broken.** It never overwrites *per file*,
  so run inside `chained` it drops `catalog/accounts.yaml` into a catalog whose `resources.yaml`
  declares no such type, and `atf status` then exits 2. Whether it should refuse outright or scaffold
  only the gaps is a product decision.

---

## Standing constraints

- No Node, no build step. One semantic CSS file.
- No literal `http(s)://` under `src/atf/` except `scaffold.py`; no `type: ignore` or `noqa: F`
  anywhere in it. Both have acceptance tests, and both have caught real mistakes.
- `mutable_envs` gates provisioning and running, never authoring.
- Design a whole change before writing it.
- Run only the tests that cover the change in hand. The full suite is ~10 minutes.
