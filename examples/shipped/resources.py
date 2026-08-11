"""The systems ATF ships, with no adapter of the suite's own.

`filesystem` and `process` come with ATF, so `extensions:` is empty and this module imports its
decorators from `atf` itself.

The scopes here are the point. `workspace` is a directory that lives for the run; `draft` is a file
inside it that lives for one test. Teardown is **always reverse lineage**, so the file goes before
the directory — and this is a case where getting it wrong fails loudly rather than quietly, because
removing a directory that still has something in it does not work.
"""

from atf import filesystem, shell


@filesystem.directory(scope="session")
class Workspace:
    path: str


@filesystem.file(scope="function")
class Draft:
    path: str
    text: str


@shell.process(unique_by="command", scope="session")
class Sleeper:
    command: str


# Named for what they are rather than after their kinds: `workspace = Workspace(...)` is refused at
# load, because `workspace` is also the name a test uses to ask for any `Workspace`.
scratch = Workspace(path="scratch")
today = Draft(path="scratch/draft.txt", text="written by ATF\n", depends_on=[scratch])
waiter = Sleeper(command='python -c "import time; time.sleep(30)"')
