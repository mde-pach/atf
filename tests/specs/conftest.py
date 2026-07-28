"""The suite's whole vocabulary: four ways of saying "run the command under test".

Running a command is ATF's own `command` adapter — argv, the environment, the working directory,
the exit code, both streams and what `ok` means are the shape of a class of system, not anything
about ATF, and they used to be a hundred lines here.

What is left is the only part that *is* this suite's business: which manifest the command should
see, and where it should be standing. A suite testing a test framework has opinions about those two
things and nothing else, which is why these four steps differ only in those two things.

There is no `@then` here at all, which is the point: no assertion a reader would have to open Python
to understand. They live in a `conftest.py` because a step defined in a module is visible only
inside it, and every `.feature` here is collected by ATF with no module of its own.
"""

import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from atf_backend import Backend
from pytest_bdd import parsers, when


@pytest.fixture
def atf(client_config):
    """The stub backend the suites-under-test provision into, for resetting between scenarios."""
    return Backend(**client_config["atf"])


@pytest.fixture(autouse=True)
def _clean_backend(atf):
    """Each scenario starts against an empty environment."""
    atf.reset()


@when(parsers.parse('I run "atf {command}"'))
def _(context, materializer, command):
    context.result = _ran(materializer, context, command)


@when(parsers.parse('I run "atf {command}", holding it as {slot:w}'))
def _(context, materializer, command, slot):
    """The same action, keeping its outcome under a name a later step can say.

    `context.result` is one slot, so a scenario doing two things could only ever assert on the
    second. Naming the slot is what lets both survive to be compared.
    """
    setattr(context, slot, _ran(materializer, context, command))


@when(parsers.parse('I run "atf {command}" with {name} exported as "{value}"'))
def _(context, materializer, command, name, value):
    """Run it with something in its environment, for the promises that are about what was exported.

    The variable's name is a parameter rather than four near-identical steps, and it stays out of
    the feature file by living in a phrase — `ATF_ENV` is the framework's word, not the reader's.
    """
    context.result = _ran(materializer, context, command, env={name: value})


@when(parsers.parse('I run "atf {command}", letting it find the suite itself'))
def _(context, materializer, command):
    """Run from a directory inside the suite, with nothing pointing at the manifest.

    Every other step here hands the command its manifest, because that is what keeps a scenario
    independent of where it happened to be run from. This one is about the opposite promise: a
    person standing anywhere inside their project types `atf` and it works.
    """
    root = Path(context.workspace["id"])
    context.result = _ran(materializer, context, command, cwd=root / "specs", manifest=None)


@when(parsers.parse('I run "atf {command}" outside any suite'))
def _(context, materializer, command):
    """Nowhere near a project — where the command has to explain itself to a newcomer."""
    empty = Path(tempfile.mkdtemp(prefix="atf-tests-nowhere-"))
    try:
        context.result = _ran(materializer, context, command, cwd=empty, manifest=None, suite=None)
    finally:
        shutil.rmtree(empty, ignore_errors=True)


def _ran(materializer, context, command, *, cwd=None, manifest=..., suite=..., env=None):
    """One invocation of the command under test, through ATF's own `command` adapter.

    Everything about *running* something — argv, the environment, the working directory, the exit
    code, both streams, and what `ok` means — is the adapter's. What is left here is this suite's
    own business: which manifest the command should see, and where it should be standing. Those are
    the two things a suite testing a *test framework* has opinions about, and nothing else is.
    """
    root = Path(context.workspace["id"]) if "workspace" in context.values else None
    where = Path(cwd) if cwd is not None else root
    exported = dict(env or {})

    if manifest is ...:
        exported["ATF_MANIFEST"] = str(root / "atf.yaml")
    elif manifest is None:
        exported["ATF_MANIFEST"] = ""
    on_path = root if suite is ... else suite
    exported["PYTHONPATH"] = os.pathsep.join(
        [os.environ.get("ATF_TESTS_SRC", ""), *([str(on_path)] if on_path else [])]
    )

    return materializer.ensure(
        "command",
        "atf",
        # `sys.executable`, not whatever `python` is on PATH: the command under test has to run in
        # the interpreter this suite was started with, or it is testing a different installation.
        {"argv": [sys.executable, "-m", "atf.cli", *shlex.split(command)],
         "cwd": str(where), "env": exported},
    )
