"""The same domain as `examples/todo`, owned by an HTTP API instead of a database.

Note what changes and what does not. Every `needs()` is identical. Only the decorator and its
options differ, which is the whole claim a system makes.

`known_by` is here because an HTTP API has no schema to read. Where a system *can* be asked — as
`sql` asks a table for what it holds unique — nothing is written at all.
"""

from atf import http, needs, shell


@shell.process(command="python api.py", port=8799, lives="the run")
class Api:
    """The API under test, started for the run and stopped when it ends.

    `port` is what makes this safe: the process is not *made* until the port answers, so nothing
    downstream races it. `lives` is written out because ATF cannot see that a server should not
    outlive the run that started it.
    """


@http.record(
    path="/owners", known_by=["email"], list_filter=["email"], collection_key="items"
)
class Owner:
    """Unique by email, fetchable only by a numeric id. `find` filters; nobody writes the id."""

    api: Api = needs()
    email: str


@http.record(
    path="/lists", known_by=["slug"], list_filter=["slug"], collection_key="items"
)
class TodoList:
    owner: Owner = needs()
    slug: str


serving = Api()
primary = Owner(api=serving, email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
