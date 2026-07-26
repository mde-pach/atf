"""Vocabulary for the list behaviours: the only hand-written step code in this suite."""

from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/lists.feature")


@when("I list the owner's lists")
def _(context, api):
    context.result = api.lists_of(context.owner)


@when("I read the tasks on the list")
def _(context, api):
    context.result = api.tasks_in(context.todo_list)


@when("I complete the task")
def _(context, api):
    context.result = api.complete(context.task)


@then(parsers.parse('the plan is "{expected}"'))
def _(context, expected):
    assert context.owner["plan"] == expected


@then(parsers.parse('the list "{slug}" is among them'))
def _(context, slug):
    assert slug in [item["slug"] for item in context.result]


@then(parsers.parse('the task "{title}" is open'))
def _(context, title):
    task = next(item for item in context.result if item["title"] == title)
    assert task["done"] is False


@then("the task is done")
def _(context):
    assert context.result["done"] is True
