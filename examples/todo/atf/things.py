"""What this suite needs to exist before a test runs.

`@todo.owner` and `@todo.list` are this suite's own, written once in `todo_system.py` over the
application's own API. The rest use ATF's built-in `@sql.row`, which is what a suite reaches for
when a thing has no interface of its own to go through.

Every edge in the graph is a `needs()` at the field that holds it — including `Report`, which has no
field for its owner until `needs()` gives it one.
"""

from todo_system import todo

from atf import needs, sql


def an_email() -> str:
    """Whatever varies. ATF does not generate values; this is the suite's own provider."""
    from itertools import count

    an_email.n = getattr(an_email, "n", count(1))
    return f"generated-{next(an_email.n)}@example.com"


@todo.owner()
class Owner:
    email: str = needs(an_email)


@todo.list()
class TodoList:
    owner: Owner = needs()
    slug: str = needs(lambda: "generated")


@sql.row(table="tasks")
class Task:
    """Nothing here declares a verb.

    `complete` and `reopen` are phrases in `lists.feature`, each standing over one `becomes`
    sentence, and `done` is an ordinary field held to what it says.
    """

    todo_list: TodoList = needs()
    slug: str
    done: bool


@sql.row(table="reports")
class Report:
    """Written per owner, and storing only its own slug and a rendered body.

    The owner is a field with no column behind it: the report has to have one, and the table keeps
    no trace of which. The system leaves out what the schema has no column for.
    """

    owner: Owner = needs()
    slug: str
    body: str


@sql.row(table="plans", owner="them")
class Plan:
    """The environment's job. ATF names one; it never makes one."""

    code: str


@sql.row(table="tenants")
class Tenant:
    """Recognised by its code within a region — which the table says, and nothing here repeats."""

    region: str
    code: str


@sql.row(table="guests")
class Guest:
    nickname: str


primary = Owner(email="primary@example.com")
secondary = Owner(email="secondary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
laundry = Task(todo_list=groceries, slug="laundry", done=False)
quarterly = Report(owner=primary, slug="quarterly", body="<html/>")
free = Plan(code="free")
acme = Tenant(region="eu", code="acme")
acme_us = Tenant(region="us", code="acme")
visitor = Guest(nickname="visitor")
anyone = Owner()
