"""The same arrangement, in Python. One resolver behind both, and `atf plan` counts these."""

from things import Owner, TodoList


def test_lineage_comes_along(groceries: TodoList):
    """Asking for the list made its owner first, because the field says `needs()`."""
    assert groceries.owner.email == "primary@example.com"


def test_asking_by_kind_gets_the_one_in_scope(primary: Owner, owner: Owner):
    """One `Owner` is in scope, so the kind parameter is handed that one."""
    assert owner is primary


def test_the_api_answers_for_what_was_arranged(groceries: TodoList, http, atf):
    """`Given the todo_list "groceries"` and this parameter are the same arrangement."""
    owner = atf.look_up("owner", "primary")
    answer = http.client.get(f"/owners/{owner['id']}/lists").json()
    assert [one["slug"] for one in answer["items"]] == ["groceries"]
