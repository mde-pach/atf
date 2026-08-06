"""The same domain as `examples/todo`, owned by an HTTP API instead of a database.

Note what changes and what does not. `depends_on` is identical. `unique_by` is identical. Only the
decorator and its options differ — which is the whole claim a system makes.
"""

from atf import process, rest


@rest(path="/owners", unique_by="email", list_filter=["email"], collection_key="items")
class Owner:
    """Unique by email, fetchable only by a numeric id. `find` filters; nobody writes the id."""

    email: str


@rest(path="/lists", unique_by="slug", list_filter=["slug"], collection_key="items", depends_on=[Owner])
class TodoList:
    slug: str


@process(command="python api.py", port=8799, scope="session")
class Api:
    """The API under test, started for the run and stopped when it ends.

    `port` is what makes this safe: the process is not *made* until the port answers, so nothing
    downstream races it.
    """


serving = Api()
primary = Owner(email="primary@example.com", depends_on=[serving])
groceries = TodoList(owner=primary, slug="groceries")
