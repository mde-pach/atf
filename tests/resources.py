"""What ATF's own suite needs to exist: an ATF suite on disk, for ATF to be run against.

The recursion is real and it stops one level down. The scaffolded suite is a small, ordinary one —
two resources with lineage between them, one scoped to a single test, two environments of which one
may not be changed. ATF's suite makes it exist, runs `atf` against it, and claims on what came back.
"""

from atf import browser, filesystem, process

MANIFEST = """\
resources: [./resources.py]
specs: ./specs
default_env: local

environments:
  local:
    mutable: true
    filesystem: { root: . }
  readonly:
    filesystem: { root: . }
"""

RESOURCES = '''\
"""Two resources with lineage between them, and one scoped to a single test."""

from atf import filesystem


@filesystem(unique_by="path")
class Notebook:
    path: str


@filesystem(unique_by="path", depends_on=[Notebook])
class Note:
    path: str
    text: str


@filesystem(unique_by="path", scope="function")
class Draft:
    path: str
    text: str


work = Notebook(path="notebooks/work")
standup = Note(path="notebooks/work/standup.md", text="stand up\\n", depends_on=[work])
scratch = Draft(path="drafts/scratch.md", text="scratch\\n")
'''

SPEC = """\
Feature: notes

  Scenario: a draft is arranged for one test
    Given the draft "scratch"
    Then the draft "scratch" exists
"""

CONFTEST = 'pytest_plugins = ["atf.plugin"]\n'


@filesystem(unique_by="path", scope="function")
class Workspace:
    """An ATF suite on disk: a manifest, a resources module, a conftest and a spec.

    `files` maps a path inside the workspace to that file's contents, and declaring them **makes
    this resource own the tree**. That matters here more than anywhere: the thing under test writes
    into this directory while a scenario runs, and teardown has to take all of it away. A workspace
    that survived would be found by recognition on the next run and tested instead of being made.
    """

    path: str
    files: dict[str, str]


scaffolded = Workspace(
    path="suite",
    files={
        "atf.yaml": MANIFEST,
        "resources.py": RESOURCES,
        "conftest.py": CONFTEST,
        "specs/notes.feature": SPEC,
    },
)


@process(
    command="uv run atf --config .workspaces/suite/atf.yaml edit --port 8791",
    port=8791,
    scope="function",
)
class Editor:
    """An `atf edit` process serving one workspace.

    The command is fixed, so it is an option on the decorator. What varies is the workspace, and
    that is what `depends_on` carries.
    """


@browser(when_absent="observe", unique_by="path", scope="function")
class Screen:
    """A page of that editor.

    `when_absent="observe"` says ATF does not make a screen — a page that does not answer is a
    failure with a reason, never an attempt to create one.
    """

    path: str


editing = Editor(depends_on=[scaffolded])
catalogue = Screen(path="/catalogue", depends_on=[editing])
