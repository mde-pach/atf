from pytest_bdd import scenarios, then

scenarios("../features/guests.feature")


@then("the guest has an identity")
def _(context):
    assert context.guest["id"]
