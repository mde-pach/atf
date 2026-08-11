"""What this suite needs to exist before a test runs.

`@todo.owner` and `@todo.list` are this suite's own, written once in `adapters/todo.py` over the
application's own API. The rest use ATF's built-in `@sql.row`, which is what a suite reaches for
when a thing has no interface of its own to go through.

Note what carries a dependency. `depends_on` does, and only `depends_on`. `TodoList` has a field
for its owner and `Report` has nowhere to put one, and both are the same edge in the graph.
"""

from adapters.todo import todo

from atf import sql


@todo.owner()
class Owner:
    email: str

    @classmethod
    def factory(cls) -> "Owner":
        return cls(email="generated@example.com")


@todo.list(depends_on=[Owner])
class TodoList:
    slug: str

    @classmethod
    def factory(cls, owner: "Owner") -> "TodoList":
        return cls(owner=owner, slug="generated")


@sql.row(table="tasks", unique_by="slug", depends_on=[TodoList])
class Task:
    """Nothing here declares a verb.

    `complete` and `reopen` are phrases in `specs/lists.feature`, each standing over one `becomes`
    sentence, and `done` is an ordinary field held to what it says.
    """

    slug: str
    done: bool


@sql.row(table="reports", unique_by="slug", depends_on=[Owner])
class Report:
    """Written per owner, and storing only its own slug and a rendered body.

    There is nowhere to put an `owner` field, and the report still needs an owner. `depends_on` is
    what says so.
    """

    slug: str
    body: str


@sql.row(table="plans", unique_by="code", when_absent="require")
class Plan:
    """The environment's job. No factory, so it can only ever be asked for by name."""

    code: str


@sql.row(table="tenants", unique_by=("region", "code"), scope="session")
class Tenant:
    """Recognised by its code *within a region*, so two regions may each have an `acme`.

    `unique_by` takes several fields when one does not tell two resources apart. They are fields the
    resource carries; a dependency goes in `depends_on`.
    """

    region: str
    code: str


@sql.row(table="guests", unique_by="nickname", scope="function")
class Guest:
    """Made fresh for each test that asks for it, and removed after."""

    nickname: str


primary = Owner(email="primary@example.com")
secondary = Owner(email="secondary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
laundry = Task(todo_list=groceries, slug="laundry", done=False)
quarterly = Report(slug="quarterly", body="<html/>", depends_on=[primary])
free = Plan(code="free")
acme = Tenant(region="eu", code="acme")
acme_us = Tenant(region="us", code="acme")
visitor = Guest(nickname="visitor")
