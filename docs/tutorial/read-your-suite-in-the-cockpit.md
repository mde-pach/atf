# 3. Read your suite in the cockpit

ATF ships a web app that renders your suite: what it declares, what exists, what passed, and what
cannot run yet. This lesson is a guided tour. It takes about ten minutes, and you will not need to
type much.

Use the suite from [lesson 1](your-first-spec.md) or [lesson 2](point-atf-at-your-api.md); either
works. Run a suite at least once first, so there is a result to look at:

```sh
atf run
```

## Start it

```sh
atf serve
```

```
ATF cockpit — http://127.0.0.1:8000
  This cockpit performs mutating actions against real environments and has NO authentication.
  It binds 127.0.0.1 by design; for shared access put it behind an authenticating reverse proxy.
  Mutable environments: dev
```

Read that banner once. The cockpit can change real environments and has no login, which is why it
binds to your machine only. Open <http://127.0.0.1:8000>.

The environment selector sits in the top bar, next to the buttons it gates. It decides what
everything else means: a resource is present *in dev*; a scenario passed *against staging*. Every
page answers for one environment at a time, and a read-only environment says so beside the selector.

## Overview: can I ship?

The landing page opens with a sentence, not a dashboard. **Yes**, **No — 2 scenarios failing**,
**Not fully**, or **Not yet** if nothing has ever run here. The supporting counts sit underneath it,
along with when the last run was.

If nothing has ever run, the page instead shows you the way out: *Provision 7 resources*, then *Run
5 scenarios*, as numbered steps you can press. A screen of zeros teaches nobody anything.

Then, in order:

- **Scenarios** by state — passing, failing, blocked, never run, skipped. Each count is a link.
- **Environment** — how much of your catalog exists here, split into what a run would create and
  what it could not.
- **Recent runs**, with anything flaky called out.
- **Gaps worth acting on** — resource types no scenario exercises, scenarios that have never run.

Click the **failing** count. You land on the Scenarios page already filtered to the failing ones,
and the URL says so — `/scenarios?state=failing`. That is a link worth bookmarking, or pasting into
a ticket.

## Scenarios: one page per behaviour

Click **Scenarios**. Every scenario in your suite is here, grouped by feature.

Open one. The page carries everything about that behaviour in one place:

- its **Gherkin**, as written;
- the **resources it names**, each with its live status in this environment;
- the **tests that cover it** — one, or one per row of an `Examples` table;
- its **last outcome**, and when that was;
- if it failed, **the step it failed on**, quoted from the Gherkin.

That last one is the difference between "test_a_project_belongs_to_its_account failed" and "it got
as far as `When I list the projects of the account`". You can usually stop reading there.

Scenario and test are not two things to browse. A test is the mechanical consequence of a scenario,
so the cockpit lists scenarios and shows their tests underneath.

## Absent is fine. Blocked is not.

A scenario page tells you what running it would do before you run it. Most scenarios in a fresh
environment will say something like *provisions 3 resources* — those resources are absent, and
naming them is exactly what makes ATF create them. Absent is information, not a warning. That is
the whole premise of the catalog.

A scenario marked **blocked** is different: something in what it names is in a state that running
cannot fix. There are only three:

- no adapter is configured for that resource's system in this environment;
- the adapter raised while looking the resource up;
- a [reference-mode](../explanation/glossary.md#reference-mode) resource is missing — ATF will never
  create one, so the environment is not configured the way the suite assumes.

The first is a manifest problem, the second an environment or credentials problem, the third a
setup problem. None of them is fixed by pressing Run, which is why the cockpit says so first.

## Resources: navigated by type

Click **Resources** in the rail. That is the catalog, grouped by
[resource type](../explanation/glossary.md#resource-type) — `account`, `project` — not by which YAML
file they happen to sit in. The file is a filing choice; the type is what your scenarios say.

Open a type. Its page tells you everything you need to write a scenario against it:

- the **system** it lives in, and the adapter that handles it;
- its **adapter settings** — the path, the natural key ATF matches on, any scoped listing;
- its **identity field**, the one `${...id}` resolves to;
- the **fixture name** ATF generates for it, so you can use it from a plain pytest test;
- the **Gherkin line** that provisions one, filled in with a real instance name;
- its **instances**, each with their live status.

That last-but-one item is the one to remember. If you ever forget how to ask for a resource in a
scenario, the type page has the line ready to copy.

## Provision what is missing

Press **Provision** — with a type selected, an instance selected, or nothing selected at all.

There is one provisioning verb, and it is scoped to what you chose. Nothing selected means
everything ATF can create that is not here yet. Whatever the scope, it provisions each target's
[closure](../explanation/glossary.md#closure) too, so you never have to work out the order. The
button tells you what it is about to do before you press it — *Provision 6 resources*, *Provision
alpha + 1 dependency*.

Beside it is **Rescan**, and it is worth knowing the difference. Rescan re-reads the catalog from
disk and asks the environment what exists. It changes nothing out there, so it works even in an
environment ATF is not allowed to touch. It is what you press after editing a YAML file.

Next to Rescan is when the environment was last read — *checked 2 mins ago*. Nothing in this
interface is of unknown age; every scenario carries when it last ran, too.

If your environment is not in `mutable_envs`, Provision and Run are disabled and say why. That gate
is in the manifest, not the browser.

## Run, and the history that outlives it

Select some scenarios and press **Run**, or press it with nothing selected to run the whole suite.

A dock appears at the bottom of the window, and each test moves from pending to running to its
outcome. **Navigate away** — click Resources, open a type. The dock is still there. Provisioning and
running are the same mechanism reporting into the same place, so work you started anywhere stays
watchable everywhere.

Now stop the server with `Ctrl-C` and start it again. The results are still there.

Runs are written to `.atf/runs/` under your suite root, so the cockpit knows the last outcome and
when it happened across restarts. It also uses that history to flag a **flaky** scenario — one that
has passed and failed lately without the suite changing. A flaky verdict is worth neither green nor
red, so it gets its own mark.

Runs from CI can join the same store, which is how the cockpit tells you about a failure that
happened on a build machine rather than on your laptop. See
[How to run ATF in CI](../how-to/run-atf-in-ci.md).

`.atf/` is a local cache. Keep it out of version control.

## When you are done

Press `Ctrl-C` in the terminal.

## What you have done

- Read "can I ship?" as a sentence, and followed a state count straight to the scenarios behind it.
- Found the exact Gherkin step a failing scenario died on.
- Told a scenario that cannot run apart from one that simply has work to do first.
- Provisioned a missing resource and its dependencies from the browser.
- Watched a job while navigating elsewhere, and found the result still there after a restart.

## Where to go next

- [How to find out why an environment is red](../how-to/find-out-why-an-environment-is-red.md) —
  this tour, applied to an actual bad day.
- [Cockpit reference](../reference/cockpit.md) — every vertical, control and state.
- [About the model](../explanation/the-model.md) — why the cockpit can answer questions an ordinary
  suite cannot.
