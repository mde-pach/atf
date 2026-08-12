"""The systems ATF ships, with no system of the suite's own.

`filesystem` and `shell` come with ATF, so this module imports its decorators from `atf` itself and
registers nothing.

How long each thing lives is the point. Nothing here types a span except where ATF cannot see the
truth: `scratch` is a directory, `today` is a file inside it, and teardown is **always reverse
lineage**, so the file goes before the directory. This is the case where the wrong order fails
loudly rather than quietly, because removing a directory that still has something in it does not
work.
"""

from atf import filesystem, needs, shell


@filesystem.directory()
class Workspace:
    path: str


@filesystem.file()
class Draft:
    workspace: Workspace = needs()
    path: str
    text: str


@shell.process(lives="the run")
class Sleeper:
    """A process ATF cannot see the end of, so this one says how long it lives."""

    command: str


# Named for what they are rather than after their kinds: `workspace = Workspace(...)` is refused at
# load, because `workspace` is also the name a test uses to ask for any `Workspace`.
scratch = Workspace(path="scratch")
today = Draft(workspace=scratch, path="scratch/draft.txt", text="written by ATF\n")
waiter = Sleeper(command='python -c "import time; time.sleep(30)"')
