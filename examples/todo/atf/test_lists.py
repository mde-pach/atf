"""The same behaviour as `lists.feature`, written in Python.

This is the library, not a second surface: the scenario and the function below arrange through the
same resolver, so neither is a second implementation of the other. `atf plan` counts these.
"""

from things import Owner, Report, TodoList


def test_a_list_shows_under_its_owner(groceries: TodoList, shell):
    """`Given the todo_list "groceries"` and this parameter are the same arrangement."""
    result = shell(f"show {groceries.owner.email}")
    assert result["exit_code"] == 0
    assert "groceries" in result["output"]


def test_lineage_comes_along(groceries: TodoList):
    """Asking for the list arranges its owner first, because the field says `needs()`."""
    assert groceries.owner.email == "primary@example.com"


def test_a_report_holds_the_owner_it_needs(quarterly: Report):
    """`Report.owner` is a field with a `needs()` on it, and it is filled by the time this runs."""
    assert quarterly.owner.email == "primary@example.com"


def test_asking_by_kind_gets_the_one_in_scope(primary: Owner, owner: Owner):
    """One `Owner` is in scope, so the kind parameter is handed it rather than a new one."""
    assert owner is primary


def test_asking_by_kind_with_nothing_in_scope_resolves_one(owner: Owner):
    """Nothing arranged an owner, so resolution builds one and `an_email` fills its field."""
    assert owner.email.startswith("generated-")
