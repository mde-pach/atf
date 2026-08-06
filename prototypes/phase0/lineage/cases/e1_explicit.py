"""One suite module, declaring every dependency shape without an annotation carrying any of them.

In `depends_on`, a kind means "any of these" and an instance means "that one".
"""

from __future__ import annotations

from typing import Self

from ..explicit import resource, sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    """Needs nothing, and can be built without being named."""

    @classmethod
    def factory(cls) -> Self:
        return cls(email="generated@example.com")


@sqlite(table="lists", unique_by="slug", depends_on=[Owner])
class TodoList:
    """Needs *any* owner. The shape has room for one, so passing it says which."""


@sqlite(table="tasks", unique_by="slug", depends_on=[TodoList])
class Task:
    """Two links up. Nothing anywhere says "owners before lists"."""


@sqlite(table="reports", unique_by="slug", depends_on=[Owner])
class Report:
    """The case an annotation could not state: it needs an owner and its shape has no room.

    A report is written per owner and stores its slug and a rendered blob. There is nowhere to put
    an `owner` field, so a typed field gave this no edge at all — not a silent one, none.
    """


@sqlite(table="plans", unique_by="code", when_absent="require")
class Plan:
    """The environment's job. No factory, so it can only ever be asked for by name."""


@sqlite(table="invoices", unique_by="number", depends_on=[Plan])
class Invoice:
    """Needs a plan, and a plan cannot be conjured — naming none of them has to be an error."""


@resource(unique_by="name")
class Note:
    """Declared with the base decorator and no system at all, to show `@sqlite` adds only options."""


primary = Owner(email="primary@example.com")

# The parent arrives as a value, because the shape has somewhere to put it. That value is the
# declaration; `depends_on=[Owner]` on the class is answered by it.
groceries = TodoList(owner=primary, slug="groceries")
laundry = Task(todo_list=groceries, slug="laundry")

# Nothing supplies an owner, so `depends_on=[Owner]` means the factory builds one.
scratch = TodoList(slug="scratch")

# The parent arrives as a dependency and nothing else, because the shape has no field for it.
quarterly = Report(slug="quarterly", body="<html/>", depends_on=[primary])

free = Plan(code="free")
march = Invoice(number="2026-03", depends_on=[free])

# Declared and asked for by nothing, which is what `atf unused` is for.
orphan = Owner(email="orphan@example.com")
