"""The same behaviour as `lists.feature`, written as pytest functions.

This is the point of `one-engine-two-surfaces`: the scenario and the function below arrange through
the same engine, so neither is a second implementation of the other.
"""

from resources import Owner, Report, TodoList


def test_a_list_shows_under_its_owner(groceries: TodoList, shell):
    """`Given the todo_list "groceries"` and this parameter are the same arrangement."""
    result = shell(f"show {groceries.owner.email}")
    assert result["exit_code"] == 0
    assert "groceries" in result["output"]


def test_lineage_comes_along(groceries: TodoList):
    """Asking for the list arranges its owner first, because `depends_on` says so."""
    assert groceries.owner.email == "primary@example.com"


def test_a_report_needs_an_owner_it_has_no_field_for(quarterly: Report):
    """`Report` has nowhere to put an owner, and still depends on one."""
    assert not hasattr(quarterly, "owner")


def test_asking_by_kind_gets_the_one_in_scope(primary: Owner, owner: Owner):
    """One `Owner` is in scope, so the kind parameter is handed it rather than a new one."""
    assert owner is primary


def test_asking_by_kind_with_nothing_in_scope_builds_one(owner: Owner):
    """Nothing arranged an owner, so `Owner.factory` runs."""
    assert owner.email == "generated@example.com"
