"""The suite's whole vocabulary: two actions.

There is nothing else here, and that is the point. Running a command is something ATF has no
generic way to do — it is the third-party action the philosophy accepts as needing code — so it is
written once, returns what it got, and every claim about the outcome is one ATF makes for every
suite. No `@then` below means no assertion a reader would have to open Python to understand.
"""

from pytest_bdd import parsers, scenarios, when

scenarios("../features/provisioning.feature")
scenarios("../features/safety.feature")


@when(parsers.parse('I run "atf {command}"'))
def _(context, atf, command):
    context.result = atf.run(context.workspace, *command.split())


@when(parsers.parse('I run "atf {command}", holding it as {slot:w}'))
def _(context, atf, command, slot):
    """The same action, keeping its outcome under a name a later step can say.

    `context.result` is one slot, so a scenario doing two things could only ever assert on the
    second. Naming the slot is what lets both survive to be compared.
    """
    setattr(context, slot, atf.run(context.workspace, *command.split()))
