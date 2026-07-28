from pytest_bdd import scenarios, then

scenarios("../features/lists.feature")


@then("the list belongs to the owner")
def _(context):
    assert context.todo_list["owner_id"] == context.owner["id"]
