"""Every resolution `arrange.md#asking-for-one` promises, as plain pytest functions."""

from __future__ import annotations

from resources import Owner, Report, TodoList


def test_by_instance_name(primary: Owner) -> None:
    """A parameter named after an instance gets that instance."""
    assert primary.email == "primary@example.com"


def test_by_kind_with_nothing_in_scope(owner: Owner) -> None:
    """A parameter named after a kind, with nothing arranged, gets one the factory built."""
    assert owner.email == "factory-built@example.com"


def test_by_kind_with_one_in_scope(primary: Owner, owner: Owner) -> None:
    """One of that kind is in scope, so the kind parameter is handed it rather than a new one."""
    assert owner is primary


def test_lineage_comes_along(groceries: TodoList) -> None:
    """Asking for `groceries` arranges `primary` too, because the field is typed as it."""
    assert groceries.owner.email == "primary@example.com"


def test_kind_factory_builds_its_own_dependency(todo_list: TodoList) -> None:
    """`TodoList.factory` takes an `owner`, which is built by `Owner.factory`, recursively."""
    assert todo_list.slug == "factory-built"
    assert todo_list.owner.email == "factory-built@example.com"


def test_dependency_with_no_field_to_hold_it(quarterly: Report) -> None:
    """`Report` has nowhere to put an owner, so `depends_on` is the only thing carrying the edge."""
    parents = quarterly.__atf_depends_on__
    assert [p.__atf_name__ for p in parents] == ["primary"]
    assert not hasattr(quarterly, "owner")


def test_kind_factory_uses_depends_on_not_its_signature(report: Report) -> None:
    """Nothing is in scope, so `depends_on=[Owner]` is what tells the factory to fetch one."""
    assert report.__atf_depends_on__[0].email == "factory-built@example.com"


def test_two_of_a_kind_named_is_fine(primary: Owner, secondary: Owner) -> None:
    """Two in scope is only a problem for a *kind* parameter. Named ones are never ambiguous."""
    assert primary.email != secondary.email
