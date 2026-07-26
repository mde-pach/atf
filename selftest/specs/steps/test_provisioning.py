"""The shared vocabulary. Every step reads its subject from `context` and writes back."""

from pytest_bdd import parsers, scenarios, then, when

scenarios("../features/provisioning.feature")
scenarios("../features/safety.feature")


@when(parsers.parse('I run "atf {command}"'))
def _(context, atf, command):
    context.result = atf.run(context.workspace, *command.split())


@then(parsers.parse("it exits {code:d}"))
def _(context, code):
    assert context.result.exit_code == code, context.result.output


@then(parsers.parse('the output mentions "{text}"'))
def _(context, text):
    assert text in context.result.output, context.result.output


@then(parsers.parse('the output does not mention "{text}"'))
def _(context, text):
    assert text not in context.result.output, context.result.output


@then(parsers.parse("the backend has {count:d} {collection}"))
def _(context, atf, count, collection):
    assert len(atf.records(collection)) == count


@then("the list points at the owner")
def _(context, atf):
    owner = atf.records("owners")[0]
    todo_list = atf.records("lists")[0]
    assert todo_list["owner_id"] == owner["id"]
