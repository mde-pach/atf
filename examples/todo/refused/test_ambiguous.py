"""Both surfaces, both ambiguous. Neither body should ever run."""
from resources import Owner, Plan


def test_two_owners_in_scope(primary: Owner, secondary: Owner, owner: Owner):
    raise AssertionError("this body must never run")


def test_a_kind_with_no_factory(plan: Plan):
    raise AssertionError("this body must never run")
