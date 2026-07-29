"""What this suite has to say about running the command under test, which is very little.

Running a command is ATF's own: `When I run "atf status local"` is a step the framework ships, and
the command line, the environment, the exit code, both streams and what `ok` means all belong to
its `command` system. None of that is about ATF-the-thing-under-test, and it used to be a hundred
lines here.

What is left says the one thing a scenario about a *test framework* sometimes has to: where the
command was standing, and what the developer had exported. Where it stands is settled when the
scenario builds its suite (`aim_the_command_at` in `suite_adapters.py`), so the ordinary case says
nothing at all — the three steps below are for the scenarios that are *about* the exception.

There is no `@given` and no `@then` here, which is the point: nothing provisioned by hand, and no
assertion a reader would have to open Python to understand. They live in a `conftest.py` because a
step defined in a module is visible only inside it, and every `.feature` here is collected by ATF
with no module of its own.
"""

from pathlib import Path

import pytest
from atf_backend import Backend
from backend import start_if_absent
from pytest_bdd import parsers, when
from suite_adapters import aim_the_command_at


@pytest.fixture(scope="session", autouse=True)
def _environment():
    """The environment these scenarios run against, started if it is not already up.

    An ordinary session fixture, which is what the manifest naming its address rather than a `*_env`
    pointer buys: the server has to be answering by the time a scenario asks for a resource, not by
    the time the plugin imports. A run needs one command, and somebody who left
    `python -m tests.backend` running in another terminal keeps their server — see
    [`backend.py`](../backend.py).
    """
    started = start_if_absent()
    yield
    if started is not None:
        started.stop()


@pytest.fixture
def atf(client_config):
    """The environment the suites-under-test provision into, for resetting between scenarios."""
    return Backend(**client_config["atf"])


@pytest.fixture(autouse=True)
def _clean_backend(atf):
    """Each scenario starts against an empty environment."""
    atf.reset()


@pytest.fixture(autouse=True)
def _the_command_starts_nowhere(materializer):
    """The command starts each scenario outside any suite, with nothing exported.

    `materializer` is one engine for the whole session, so its `command` system is one object every
    scenario shares. A scenario that built a suite aimed it there; the next one must not inherit it.
    """
    aim_the_command_at(None, materializer)


@when(parsers.parse('I run "{command}", holding it as {slot:w}'))
def _(context, materializer, command, slot):
    """The same action, keeping its outcome under a name a later step can say.

    `context.result` is one slot, so a scenario doing two things could only ever assert on the
    second. Naming the slot is what lets both survive to be compared.
    """
    setattr(context, slot, materializer.adapters["command"].run(command))


@when(parsers.parse('I run "{command}" with {name} exported as "{value}"'))
def _(context, materializer, command, name, value):
    """Run it with something in its environment, for the promises that are about what was exported.

    The variable's name is a parameter rather than a step per variable, and it stays out of the
    feature file by living in a phrase — `ATF_ENV` is the framework's word, not the reader's.
    """
    context.result = materializer.adapters["command"].run(command, env={name: value})


@when(parsers.parse('I run "{command}", letting it find the suite itself'))
def _(context, materializer, command):
    """Run from a directory inside the suite, with nothing pointing at the manifest.

    Every other run hands the command its manifest, because that is what keeps a scenario
    independent of where it happened to be run from. This one is about the opposite promise: a
    person standing anywhere inside their project types `atf` and it works.
    """
    runner = materializer.adapters["command"]
    context.result = runner.run(command, cwd=Path(runner.cwd) / "specs", env={"ATF_MANIFEST": ""})


@when(parsers.parse('I run "{command}" outside any suite'))
def _(context, materializer, command):
    """Nowhere near a project — where the command has to explain itself to a newcomer.

    Said in the line rather than left to the fixture above, because this is the one kind of scenario
    that is *about* where the command was standing.
    """
    runner = materializer.adapters["command"]
    aim_the_command_at(None, materializer)
    context.result = runner.run(command)


def pytest_collection_modifyitems(items):
    """Keep every scenario on one worker when the suite is run in parallel.

    ATF's engine is single-worker by design — one session materializer, one listing cache, one
    get-or-create — so two scenarios provisioning the same environment at once is exactly the thing
    [concurrency](../../docs/reference/specs-and-fixtures.md#concurrency) forbids. Running them
    across workers really does fail, in the way that ban predicts.

    That is not a reason to run the whole repository serially, though. `xdist_group` pins these to a
    single worker, which is all the ban asks for, and leaves the Python tests — ordinary tests with
    their own temp directories and their own stub backend per worker — free to spread out. The
    scenarios then cost what they always did, and everything else costs almost nothing.
    """
    for item in items:
        item.add_marker(pytest.mark.xdist_group("the-atf-suite"))
