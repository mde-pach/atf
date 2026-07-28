"""The suite's whole vocabulary: the command under test, and four ways to run it.

Running a command is something ATF has no generic way to do — it is the third-party action the
philosophy accepts as needing code — so it is written once here, and every claim about the outcome
is one ATF makes for any suite. There is no `@then` in this suite at all, which is the point: no
assertion a reader would have to open Python to understand.

They live in a `conftest.py` rather than beside a feature because a step defined in a module is
visible only inside it, and every `.feature` here is now collected by ATF with no module of its
own. `collect.py` says that rule out loud; this is the file it points at.
"""

import pytest
from atf_cli import AtfUnderTest
from pytest_bdd import parsers, when


@pytest.fixture
def atf(client_config):
    """The `atf` command itself, pointed at the stub backend the suites-under-test provision into."""
    return AtfUnderTest(**client_config["atf"])


@pytest.fixture(autouse=True)
def _clean_backend(atf):
    """Each scenario starts against an empty environment."""
    atf.reset()


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


@when(parsers.parse('I run "atf {command}", letting it find the suite itself'))
def _(context, atf, command):
    """Run from a directory inside the suite, with nothing pointing at the manifest.

    Every other step here hands the command its manifest, because that is what keeps a scenario
    independent of where it happened to be run from. This one is about the opposite promise: a
    person standing anywhere inside their project types `atf` and it works.
    """
    context.result = atf.run_and_find(context.workspace, *command.split())


@when(parsers.parse('I run "atf {command}" outside any suite'))
def _(context, atf, command):
    """Nowhere near a project — where the command has to explain itself to a newcomer."""
    context.result = atf.run_nowhere(*command.split())
