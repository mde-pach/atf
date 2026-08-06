"""Every case that must stop the run at collection, in one directory so one run reports them all.

Nothing here is expected to execute. The point is the message.
"""

from __future__ import annotations

from pytest_bdd import scenarios
from resources import Owner, Plan, TodoList


def test_two_owners_in_scope(primary: Owner, secondary: Owner, owner: Owner) -> None:
    """Two of a kind are arranged, so `owner` cannot say which is meant."""
    raise AssertionError("this body must never run")


def test_two_lists_in_scope(groceries: TodoList, weekly: TodoList, todo_list: TodoList) -> None:
    """The same thing one level down the lineage, to show more than one problem is reported."""
    raise AssertionError("this body must never run")


def test_kind_with_no_factory(plan: Plan) -> None:
    """`Plan` has no factory and nothing is in scope, so there is nothing to hand over."""
    raise AssertionError("this body must never run")


scenarios("two_owners.feature")
