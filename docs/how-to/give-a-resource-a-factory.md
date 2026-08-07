# Give a resource a factory

Let a test ask for *an* owner rather than *that* owner, and have ATF build one.

## The shortest path

Add a `factory` classmethod to the resource.

```python
# resources.py
from typing import Self

from faker import Faker

from adapters.sqlite import sqlite

faker = Faker()


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str

    @classmethod
    def factory(cls) -> Self:
        return cls(email=faker.email())
```

Ask for the kind instead of a name.

```python
def test_show_reports_an_empty_owner(owner: Owner, shell):
    result = shell(f"todo show {owner.email}")
    assert result["output"].strip() == "no lists"
```

```gherkin
Scenario: a fresh owner has no lists
  Given an owner
  Then the environment has 0 todo_list
```

`Given an owner` and an unnamed annotation are the same request: nothing arranged an owner, so the
factory runs. Inside a scenario that already said `Given the owner "primary"`, the type name resolves
to what the scenario arranged and the factory does not run. See
[factory](../reference/arrange.md#factory) for the resolution order in full.

This is `factory_boy`'s factory, moved onto the resource and typed. There is one per kind.

## When to reach for it

Reach for a factory when the identity of the record does not matter to the assertion. "An owner with
no lists sees `no lists`" is true of every owner; writing it against `primary` states something
narrower than you mean, and ties the test to an instance other tests are also using.

Ask whether you would have to change the assertion if the email changed. If yes, name the instance.

## A dependency it is not given

A factory takes its dependencies as parameters, typed. On the
[`TodoList` declared with an `owner` field](depend-on-another-resource.md), that is one more
classmethod:

```python
    @classmethod
    def factory(cls, owner: Owner) -> Self:
        return cls(owner=owner, slug=faker.slug())
```

A test asking for `todo_list: TodoList` arranged no owner, so ATF builds one with `Owner.factory` and
passes it in. That recurses.

A test that asked for `primary: Owner` as well gets `primary` in the factory's hands instead. The
factory never overrides what the test already said. It fills what the test left open. See
[Depend on another resource](depend-on-another-resource.md) for what else that graph is good for.

## Generated values change the shape of every run

`faker.email()` returns a different address each run, so a factory-built arrange exercises a different
shape every time — a long local part, an apostrophe, an address that sorts before every other row.
**A factory-built failure is a lead, not a flake.** Reproduce it against the values the run recorded
rather than re-running it: see [history](../reference/the-record.md#history).

The cost is that reproducing takes a step you would not otherwise take, and a suite leaning entirely
on factories has no test that says what happens for one specific well-known record. Most suites want
both; [Declared, not executed](../explanation/declared-not-executed.md) sets the factory beside the
fixtures and setup code it stands in for.

## When it goes wrong

**`no factory for Owner`.** A test asked for the kind, nothing arranged one, and the class has no
`factory` classmethod. Either add one or name an instance.

**`two owners in scope: primary, deputy`.** The factory is not consulted, because the ambiguity is in
what the test arranged. Name the one you mean.

**Recognition collisions.** If a factory generates the `unique_by` value from something that is not
unique — a fixed prefix, a small enumeration — ATF recognises the second one as the first and hands
back the record that already exists. Generate from something with room in it.

`atf.within` is that something, and it is what to reach for once anything runs at the same time:

```python
import atf


@sqlite(table="guests", unique_by="nickname", scope="function")
class Guest:
    nickname: str

    @classmethod
    def factory(cls) -> "Guest":
        return cls(nickname=atf.within("guest"))
```

`within("guest")` is `guest-3f9a1c04`, where the second half is this run's token. Every worker of an
`atf run --jobs` run is handed a different one, so two of them cannot generate the same name. Name it
yourself with `atf run --namespace pr-1234` or `ATF_NAMESPACE`, which is what a branch running
against a shared environment wants — every name that branch writes then carries the branch in it.

**A factory that touches a system.** A factory returns a declaration. It must not create anything,
open a connection, or read the environment. Provisioning happens after resolution, and a factory that
provisions runs at the wrong time and in the wrong order.

## Where to go next

- [Vary a resource for one test](vary-a-resource-for-one-test.md) — the judgement call between a
  factory, a variation and a second named instance, side by side.
- [Depend on another resource](depend-on-another-resource.md) — what the dependency graph answers
  once `depends_on` is in place.
- [Arrange](../reference/arrange.md#factory) — the resolution rules, including a factory given a
  dependency that was itself factory-built.
