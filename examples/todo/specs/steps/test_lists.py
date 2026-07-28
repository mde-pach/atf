"""The only hand-written step code in this suite, and only where it has to be.

Two `When`s, because each reads something back in a shape the catalog does not describe — a listing
scoped to a parent, which is a query rather than a resource. One `Then`, because "all of them" is a
claim about a response, not about a resource ATF can read back for itself.

Completing a task used to be a third. It is now `actions: {complete: {patch: {done: true}}}` on the
`task` type — the adapter offers the mechanical verb, the catalog names the domain action, and the
spec says the action. The code that went away is exactly the kind this framework exists to stop
anyone having to write.

Everything else these features claim is about a catalog resource, and ATF reads those:
`Then the task "laundry" is done` needs nothing here, even though the `When` above it changed the
task through the API. The assertion goes back to the backend and looks. The sentence itself is in
`specs/phrasebook.yaml`, which is data — so the wording is the suite's and the reading is ATF's.
"""

from pytest_bdd import scenarios, then, when

scenarios("../features/lists.feature")


@when("I list the owner's lists")
def _(context, api):
    context.result = api.lists_of(context.owner)


@when("I read the tasks on the list")
def _(context, api):
    context.result = api.tasks_in(context.todo_list)


@then("the tasks that came back are all open")
def _(context):
    assert context.result and all(task["done"] is False for task in context.result)
