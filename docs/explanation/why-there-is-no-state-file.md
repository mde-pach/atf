# Why there is no state file

ATF declares resources and then makes them exist. That is the shape of an infrastructure tool, and
the question follows immediately: where does it record what it made? It does not. Every run, it asks
the environment what is there, compares the answer with the declaration, and changes whatever
differs.

## Recognition, and then reconciliation

A resource declares how it is recognised.

```python
@todo.owner()
class Owner:
    email: str
```

recognition is a question, not a label. Before a test that needs `primary`, ATF asks the
environment whether a row in `owners` has that email. Three answers are possible — `present`,
`absent`, `unreachable` — and there is no fourth that comes from memory.

```text
find  →  nothing        → create
      →  same           → done
      →  differs        → update
```

Create and update happen only where the environment
[may be changed](../model.md). The environment converges on the
declaration every run, and ATF gets there on a declaration and a query, without remembering a thing.

An absent resource is not a blocker. Naming a resource is precisely what makes ATF create it; naming
a field is precisely what makes ATF put it back.

ATF computes that diff, never the adapter. An adapter answers `find`, `create`, `update` and
`delete`; working out which fields differ is the framework's job. That is what lets
`atf plan` print what provisioning would alter before it alters anything, and why the
editor can show the same list before anybody presses anything.

## Terraform, fairly

Terraform got this right for its own problem. It needs memory for one thing that no amount of
re-reading can supply. Convergence does not: you can always compare the world with the configuration
and correct the difference. Deletion does. Nothing in a configuration says what used to be in it, so
without a record there is no way to tell "I never managed this" from "I made this and you have since
deleted it from the configuration, so I must destroy it". That is a correct answer to a real
question.

It is also the most-criticised part of Terraform, for a reason that is not anybody's fault. Reality
drifts from the record: someone changes a thing in a console, a deploy pipeline touches a resource
out of band. Everything downstream is an attempt to keep one file honest about a world it cannot
watch — `refresh`, `import`, `state rm`, drift detection, locking, remote backends.

ATF holds two things that can disagree, the declaration and the environment, and disagreement between
two things is a diff. Terraform holds three, and three things disagree in ways that need a vocabulary
and a set of subcommands. ATF does not solve that problem. It declines it.

## What ATF gives up

Two things, and they are real.

**It cannot delete what it no longer declares.** Remove `groceries` from `resources.py` and the row
stays where it was. ATF has no memory that the list was ever its doing, so the row is now an orphan.
Terraform would destroy it on the next apply; that is the whole point of state. `atf plan --apply` only ever
adds or corrects. The one exception is [scope](../model.md): a `the test`
resource is removed after the test that used it, and a `the run` one when the run ends,
because those removals are bounded by a process that is still running and can remember. A long-lived
environment accumulates. If that matters, truncating it is your job, not the framework's.

**A declaration is a partial specification.** The fields you named must hold. The fields you did not
name are left alone, on purpose. Add a column the resource has never mentioned, and reconciliation
has no opinion about it in either direction: it will not set it, and it will not notice that somebody
else did.

That is the right default for a framework sharing a database with an application that has its own
columns, defaults and migrations; a tool that insisted on every field would spend its life fighting
the thing under test. But the limit is real: a field nobody named can be wrong all year and no run
will say so. The fix is not a setting. It is to name the field.

## Why that is the right trade here

A test framework is a guest in the environment, not its owner. Terraform owns the infrastructure it
manages, and ownership is what earns the right to remember. ATF points at a database somebody else
migrates, a service somebody else deploys, a staging environment that a nightly job resets and four
other suites are using at the same time. In that setting, drift is the normal condition, minute to
minute.

A memory that is usually wrong is worse than no memory, because it makes confident statements. The
failure mode of a stale state file in a shared test environment is a run that refuses to proceed, or
proceeds on a false premise, and the person debugging it has to learn a second model of the world
before they can start on the first.

Two people running the same suite against the same environment also get the same answer, because
there is no local file to be out of date, and nothing holds real values the way a Terraform state
file does, so nothing needs a secure backend.

The cost is a lookup per resource per run, and a write whenever something differs, against a live
system, every time.

## What else was considered

**A cache with a short life** — remember for five minutes, or for a CI job. This is a state file with
a shorter half-life and a subtler failure: you learn about drift halfway through a run, in a later
test, which is the same "wrong test, wrong moment" problem the design works hardest to avoid.

ATF does keep memory for exactly one run. A `the run` resource is recognised once and reused
by every test that asks for it. That is a cache, and it is honest to call it one. It dies with the
process, which is the property that makes it safe.

**Tagging what it made** — an `atf-` prefix, a label, a marker column, so ATF could later reclaim its
own things. It would buy back the one thing reconciliation cannot do, and it was still declined, for
three reasons. It pushes ATF's naming into your data. It only works on systems with somewhere to put
a tag, which rules out several adapters. And it makes recognition a two-part rule — the key *and* the
tag — which breaks the resources that matter most: anything declared
[`owner="them"`](../model.md) is owned by the environment
and will never carry ATF's tag.

## One thing ATF does remember

History. Which runs happened, and what each test did. That is what `atf run --failed` reads, what
`atf explain` folds into a verdict, and what `atf run --import` brings back from CI.

History is memory about **runs**, and a run is a past event: it is finished and it cannot drift. A
state file is memory about the **environment**, and an environment changes while you are not looking.
ATF remembers the first and refuses to remember the second.

## Where to go next

- **[Declared, not executed](declared-not-executed.md)** — why the declarations are static while the
  environment is not, and why both statements are true at once.
- **[Require something you cannot create](../index.md)** — what
  to do about the resources your environment owns rather than your suite.
- **[The ground](../model.md)** — where `mutable` is defined, and what an immutable
  environment still runs.
