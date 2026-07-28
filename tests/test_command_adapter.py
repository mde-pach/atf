"""The `command` adapter: argv, an environment, a working directory, and what came back.

What it *does* is exercised by every scenario in `specs/` — the whole suite runs the command under
test through it. What is here is the shape of a command line, which is a decision procedure over
the node's body and has no observable surface of its own: a string split like a shell, a list taken
as it stands, a `program` an environment configured with `args` following it.
"""

from __future__ import annotations

import sys

import pytest

from atf.adapters.command import CommandAdapter
from atf.catalog import Node


def node(**body) -> Node:
    return Node(
        id="commands.one",
        collection="commands",
        name="one",
        resource="command",
        system="command",
        mode="create",
        lifecycle="ephemeral",
        id_field="id",
        config={},
        represents="",
        depends_on=[],
        dependents=[],
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


# ---- what to run -------------------------------------------------------------


def test_a_command_line_may_be_written_as_a_string_or_a_list():
    """A string is split the way a shell would, so a quoted argument survives as one word."""
    adapter = CommandAdapter()
    made = node(argv='echo "one two" three')
    assert adapter._argv(made, made["body"]) == ["echo", "one two", "three"]

    made = node(argv=["echo", "one two", "three"])
    assert adapter._argv(made, made["body"]) == ["echo", "one two", "three"]


def test_args_follow_the_program_the_environment_configured():
    """One node serves every invocation of one tool: the scenario varies `args` and nothing else."""
    adapter = CommandAdapter(program=["atf"])
    made = node(args="seed local")
    assert adapter._argv(made, made["body"]) == ["atf", "seed", "local"]


def test_a_whole_argv_ignores_the_configured_program():
    adapter = CommandAdapter(program=["atf"])
    made = node(argv=["git", "status"])
    assert adapter._argv(made, made["body"]) == ["git", "status"]


def test_nothing_to_run_says_both_ways_of_saying_it():
    adapter = CommandAdapter()
    made = node()
    with pytest.raises(ValueError) as err:
        adapter._argv(made, made["body"])
    assert "give the node an `argv`" in str(err.value)
    assert "`args` to follow the `program`" in str(err.value)


# ---- running one -------------------------------------------------------------


def test_what_came_back_is_the_whole_of_it(tmp_path):
    adapter = CommandAdapter(cwd=str(tmp_path))
    record = adapter.create(node(), {"argv": [sys.executable, "-c", "print('hi')"]}, Ctx())

    assert record["exit_code"] == 0
    assert record["stdout"].strip() == "hi"
    assert record["stderr"] == ""
    assert record["ok"] is True


def test_ok_is_what_the_adapter_answers_rather_than_every_suite(tmp_path):
    """"How do you know it failed" is a question about commands, not about any one project."""
    adapter = CommandAdapter(cwd=str(tmp_path))
    record = adapter.create(node(), {"argv": [sys.executable, "-c", "raise SystemExit(2)"]}, Ctx())

    assert record["exit_code"] == 2
    assert record["ok"] is False


def test_output_is_both_streams_because_which_one_is_the_tools_business(tmp_path):
    adapter = CommandAdapter(cwd=str(tmp_path))
    script = "import sys; print('out'); print('err', file=sys.stderr)"
    record = adapter.create(node(), {"argv": [sys.executable, "-c", script]}, Ctx())

    assert "out" in record["output"] and "err" in record["output"]


def test_a_command_is_never_already_run(tmp_path):
    """Which is what makes one ephemeral: `find` has nothing to answer."""
    assert CommandAdapter(cwd=str(tmp_path)).find(node(argv=["true"]), Ctx()) is None


def test_something_that_is_not_there_says_which_thing(tmp_path):
    adapter = CommandAdapter(cwd=str(tmp_path))
    with pytest.raises(ValueError) as err:
        adapter.create(node(), {"argv": ["no-such-program-anywhere"]}, Ctx())
    assert "no 'no-such-program-anywhere' to run here" in str(err.value)


def test_a_directory_that_is_not_there_says_so(tmp_path):
    adapter = CommandAdapter()
    with pytest.raises(ValueError) as err:
        adapter.create(node(), {"argv": ["true"], "cwd": str(tmp_path / "nowhere")}, Ctx())
    assert "no directory at" in str(err.value)


def test_the_node_may_add_to_the_environment(tmp_path):
    adapter = CommandAdapter(cwd=str(tmp_path), env={"FROM_SETTINGS": "a"})
    script = "import os; print(os.environ['FROM_SETTINGS'], os.environ['FROM_NODE'])"
    record = adapter.create(
        node(), {"argv": [sys.executable, "-c", script], "env": {"FROM_NODE": "b"}}, Ctx()
    )
    assert record["stdout"].strip() == "a b"
