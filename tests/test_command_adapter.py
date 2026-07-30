"""The `command` adapter, where it cannot be watched from a scenario.

What it *does* is said in `specs/features/commands.feature` and exercised by every other feature
here: the whole suite drives the command under test through `When I run "…"`. What is left is the
part no scenario can reach — how a command line is split, and what the adapter says when there is
nothing to run, nowhere to run it, or no such program. Those raise before any claim gets to be
made, so a scenario about one of them could only ever be a red run.

The environment and the node body are here for the same reason: they are what a *catalog* says, and
this suite's own catalog has no command node in it — most suites need none, because the step says
the whole command line in the sentence.
"""

from __future__ import annotations

import sys

import pytest

from atf.adapters.command import CommandAdapter
from atf.model.catalog import Node
from atf.model.typespec import EPHEMERAL, TypeSpec


def node(**body) -> Node:
    return Node(
        id="commands.one",
        collection="commands",
        name="one",
        spec=TypeSpec(name="command", system="command", lifecycle=EPHEMERAL),
        body=body,
    )


class Ctx:
    env = "test"

    def resolve(self, value):
        return value

    def cached(self, key, loader):
        return loader()

    def invalidate_cache(self):
        return None


# ---- how a command line is read ----------------------------------------------


def test_a_quoted_argument_survives_as_one_word(tmp_path):
    """Split the way a shell splits it, which is how the person who wrote it expects it to read."""
    adapter = CommandAdapter(cwd=str(tmp_path))
    record = adapter.run(f"{sys.executable} -c \"print('one two')\"")
    assert record["stdout"].strip() == "one two"


def test_a_command_line_may_also_be_given_as_words(tmp_path):
    """For a caller that already has them — a suite's own step, never a feature file."""
    adapter = CommandAdapter(cwd=str(tmp_path))
    record = adapter.run([sys.executable, "-c", "print('one two')"])
    assert record["stdout"].strip() == "one two"


def test_nothing_to_run_says_so(tmp_path):
    with pytest.raises(ValueError, match="there is nothing to run"):
        CommandAdapter(cwd=str(tmp_path)).run("")


def test_something_that_is_not_there_says_which_thing(tmp_path):
    with pytest.raises(ValueError) as err:
        CommandAdapter(cwd=str(tmp_path)).run("no-such-program-anywhere --help")
    assert "no 'no-such-program-anywhere' to run here" in str(err.value)


def test_a_directory_that_is_not_there_says_so(tmp_path):
    with pytest.raises(ValueError, match="no directory at"):
        CommandAdapter().run("true", cwd=tmp_path / "nowhere")


# ---- what came back -----------------------------------------------------------


def test_output_is_both_streams_because_which_one_is_the_tools_business(tmp_path):
    adapter = CommandAdapter(cwd=str(tmp_path))
    script = "import sys; print('out'); print('err', file=sys.stderr)"
    record = adapter.run([sys.executable, "-c", script])

    assert record["stdout"].strip() == "out"
    assert record["stderr"].strip() == "err"
    assert "out" in record["output"] and "err" in record["output"]


def test_the_environment_is_the_settings_and_then_the_invocation(tmp_path):
    """A suite settles what every run needs; one run adds what only it needs."""
    adapter = CommandAdapter(cwd=str(tmp_path), env={"FROM_SETTINGS": "a"})
    script = "import os; print(os.environ['FROM_SETTINGS'], os.environ['FROM_RUN'])"
    record = adapter.run([sys.executable, "-c", script], env={"FROM_RUN": "b"})

    assert record["stdout"].strip() == "a b"


def test_an_environment_may_be_pinned_rather_than_inherited(tmp_path, monkeypatch):
    """A suite driving a tool usually wants PATH and HOME; one pinning an exact environment wants
    neither, and nothing this process happens to be carrying reaches the command."""
    monkeypatch.setenv("FROM_THIS_PROCESS", "leaked")
    adapter = CommandAdapter(cwd=str(tmp_path), inherit_env=False, env={"ONLY": "this"})
    script = "import os; print(os.environ['ONLY'], os.environ.get('FROM_THIS_PROCESS'))"
    record = adapter.run([sys.executable, "-c", script])

    assert record["stdout"].strip() == "this None"


# ---- a command as a resource --------------------------------------------------


def test_a_command_is_never_already_run(tmp_path):
    """Which is what makes one ephemeral: `find` has nothing to answer."""
    assert CommandAdapter(cwd=str(tmp_path)).find(node(command="true"), Ctx()) is None


def test_a_node_runs_the_command_line_its_body_says(tmp_path):
    adapter = CommandAdapter(cwd=str(tmp_path))
    made = node(command=f"{sys.executable} -c \"print('from the catalog')\"")
    record = adapter.create(made, made.body, Ctx())

    assert record["stdout"].strip() == "from the catalog"
    assert record["ok"] is True


def test_a_node_with_nothing_to_run_says_which_node(tmp_path):
    made = node()
    with pytest.raises(ValueError) as err:
        CommandAdapter(cwd=str(tmp_path)).create(made, made.body, Ctx())
    assert "commands.one: nothing to run" in str(err.value)
