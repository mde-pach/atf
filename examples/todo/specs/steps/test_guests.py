from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/guests.feature")


@when("I read the guest")
def _(context, api):
    context.result = api.guest(context.guest)


@then("the guest is ready")
def _(context):
    assert context.result["state"] == "ready"


@then(parsers.parse('the label "{name}" is found'))
def _(context, api, name):
    assert api.label(name) == context.label
