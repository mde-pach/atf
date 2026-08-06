# Add a resource

Take something your tests need from not existing at all to being provisioned in an environment.

## The shortest path

Declare the shape and the system that holds it.

```python
# resources.py
from adapters.sqlite import sqlite      # your suite's adapter, not ATF's


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
```

The class is the shape. The decorator is the [system](../reference/arrange.md#system), and it carries
that system's own configuration. `unique_by` is [recognition](../reference/arrange.md#recognition):
the field ATF reads to decide whether this record is already there. `table` is the other half of
that: this adapter never guesses a table from a class name, because a class is a shape your suite
chose and a table is a name your database chose.

ATF ships `@command`, `@browser`, `@filesystem` and `@process`. `@sqlite` is not one of them: it is an
[adapter](../reference/arrange.md#adapter) living in your own suite, and importing a decorator from
your own code is the normal case. [Teach ATF a new system](teach-atf-a-new-system.md) opens the file.

Name an instance in the same module.

```python
primary = Owner(email="primary@example.com")
```

A resource's name is its variable's name. Construction declares; it touches nothing.

Ask for it.

```gherkin
Scenario: a new owner has no lists
  Given the owner "primary"
  When I run "todo show primary@example.com"
  Then the result field "output" contains "no lists"
```

The same test as a pytest function:

```python
def test_a_new_owner_has_no_lists(primary: Owner, shell):
    result = shell(f"todo show {primary.email}")
    assert result["output"].strip() == "no lists"
```

The name resolves and the annotation types — pytest's own rule for fixtures, applied to resources.
See [asking for one](../reference/arrange.md#asking-for-one) for what happens when the name does not
match an instance.

## Where the module lives, and how ATF finds it

ATF imports the modules listed under `resources` in `atf.yaml` and nothing else.

```yaml
resources: [./resources.py]
specs: ./specs
default_env: local
```

From each listed module it takes every decorated class as a resource kind, and every module-level
instance of one as a named instance. There is no scan, no plugin hook and no registry. A second file
is a second entry.

```yaml
resources: [./resources.py, ./resources/billing.py]
```

The trade-off is that a file you forget to list is invisible, and a missing entry reads as a missing
name.

## What `atf status` says, before and after

The instance is now known and absent. Absent is information, not a warning: naming a resource is what
makes ATF create it. `atf make` creates what is missing.

```console
$ atf status local
resource   instance   state
Owner      primary    absent

$ atf make local
Owner primary  created

$ atf status local
resource   instance   state
Owner      primary    present
```

You rarely need `atf make` by hand — a test that asks for `primary` provisions it. The command is for
seeing the environment settle before a run, and for filling an environment several suites share.

## Provisioning is reconciliation, not creation

ATF ensures the state you declared. It finds the record by its recognition field and acts on the
difference.

```text
find  →  nothing        → create it
      →  same           → nothing to do
      →  differs        → update it
```

A record already there with the wrong value for a declared field is neither left wrong nor rebuilt:
the field is brought into line and the row keeps its id. Change a value in `resources.py`, run the
suite, and the environment follows.

**A declaration is a partial specification.** The fields you named must hold; fields you did not name
are left exactly as they are. So you can point ATF at a table it does not own the whole of, and you
cannot use a declaration to assert that a field is *absent*. If a field's absence matters, claim it
in the test.

```gherkin
Then the owner "primary" field "deleted_at" is #absent
```

## Variations

**More than one instance of a kind.** Declare each one at module level.

```python
primary = Owner(email="primary@example.com")
deputy = Owner(email="deputy@example.com")
```

A test then names the one it means: `Given the owner "deputy"`, or `def test_x(deputy: Owner)`.
Annotating `owner: Owner` without naming an instance asks for *any* owner, which is a different
request — see [Give a resource a factory](give-a-resource-a-factory.md).

**A field beyond the recognition field.** Add it to the class and pass it at construction.

```python
@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
    display_name: str


primary = Owner(email="primary@example.com", display_name="Primary")
```

`unique_by` still names `email`. Recognition decides identity; the other fields are the body ATF
writes when it creates the record.

**A resource the environment owns.** If the thing cannot be created by a test — a plan, a region, a
feature flag — declare it with `when_absent="require"` instead, covered in
[Require something you cannot create](require-something-you-cannot-create.md).

## When it goes wrong

**`unknown resource "primary"`.** Either the module is not listed under `resources` in `atf.yaml`, or
the instance is not at module level. An instance built inside a function or a class body has no
variable name ATF can read.

**`atf make` refuses: environment "staging" may not be changed.** `mutable` is false unless stated.
Add `mutable: true` if that environment really is yours to change, and see
[may be changed](../reference/the-ground.md#may-be-changed) for why the default runs that way round.

**`two owners in scope: primary, deputy`.** A test arranged two instances of one kind and then asked
for the kind rather than a name. Name the one you mean.

**`Owner: unique_by names "email", which is not a field`.** `atf check` catches this without running
anything. Run it after every declaration you make.

## Where to go next

- [Depend on another resource](depend-on-another-resource.md) — when the resource you added is needed
  by another one, and you would rather not write the ordering down.
- [Give a resource a factory](give-a-resource-a-factory.md) — when a test needs an owner but does not
  care which one.
- [Arrange](../reference/arrange.md#resource) — the full set of declaration options.
