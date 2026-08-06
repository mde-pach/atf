"""What ATF's own suite needs to exist: an ATF suite on disk, for ATF to be run against.

The recursion is real and it stops one level down. The scaffolded suite is a small, ordinary one —
two resources with lineage between them, one scoped to a single test, two environments of which one
may not be changed. ATF's suite makes it exist, runs `atf` against it, and claims on what came back.
"""

from atf import browser, filesystem, process

MANIFEST = """\
resources: [./resources.py]
specs: ./specs
extensions: [./vocabulary.py]
default_env: local

environments:
  local:
    mutable: true
    filesystem: { root: . }
  readonly:
    filesystem: { root: . }
"""

RESOURCES = '''\
"""A small, ordinary suite: lineage, every scope, and something the environment owns."""

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


@filesystem(unique_by="path", scope="session")
class Meeting:
    path: str
    text: str


@filesystem(unique_by="path", when_absent="require")
class Archive:
    """Somebody else's job. ATF names it rather than making one."""

    path: str


work = Notebook(path="notebooks/work")
standup = Note(path="notebooks/work/standup.md", text="stand up\\n", depends_on=[work])
retro = Note(path="notebooks/work/retro.md", text="retro\\n", depends_on=[work])
scratch = Draft(path="drafts/scratch.md", text="scratch\\n")
weekly = Meeting(path="meetings/weekly.md", text="weekly\\n")
archived = Archive(path="archive/2025.md")
'''

SPEC = """\
Feature: notes

  @phrase
  Scenario: the notebook is there
    Then the notebook "work" exists

  @phrase
  Scenario: the working notebook holds a note
    Then the notebook is there
    And the note "standup" exists

  Scenario: a draft is arranged for one test
    Given the draft "scratch"
    Then the draft "scratch" exists

  Scenario: a marker asks for a kind where a value would be wrong
    Given the note "standup"
    Then the note "standup" field "path" is #str
    And the note "standup" field "text" is #markdown
    And the note "standup" field "nothing" is #absent

  Scenario: a claim this suite registered holds like a built-in
    Given the note "standup"
    Then the note "standup" reads like a note

  Scenario: a phrase says what several sentences say
    Given the note "standup"
    Then the working notebook holds a note

  Scenario: one field is changed for the length of one scenario
    Given the note "standup" but "text" is "varied"
    Then the note "standup" field "text" is "varied"

  Scenario: a continuation names one more field
    Given the note "standup" but "text" is "twice"
    And "path" is "notebooks/work/twice.md"
    Then the note "standup" field "path" is "notebooks/work/twice.md"

  Scenario Outline: every notebook is arranged the same way
    Given the notebook "<which>"
    Then the notebook "<which>" exists

    Examples:
      | which |
      | work  |
"""

PYTEST_SIDE = '''\
"""The same behaviour as a scenario, as a pytest function. One engine behind both."""

from resources import Note, Notebook


def test_lineage_comes_along(standup: Note):
    assert standup.path == "notebooks/work/standup.md"


def test_asking_by_kind_gets_the_one_in_scope(work: Notebook, notebook: Notebook):
    assert notebook is work
'''

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


INNER_VOCABULARY = '''\
"""What the scaffolded suite registers: one marker, one claim, one check."""

from atf import check, claim, marker


@marker("markdown")
def _(value):
    return str(value).endswith("\\n"), "it does not end in a newline"


@claim('the {kind} "{name}" reads like a note')
def _(record):
    text = (record or {}).get("text", "")
    return bool(text.strip()), "it is empty"


@check("every note lives under a notebook")
def _(suite):
    for name, node in suite.suite.instances.items():
        if type(node).__name__ == "Note" and not str(node.path).startswith("notebooks/"):
            yield name, "it is not under notebooks/"
'''

BAD_VOCABULARY = '''\
"""A check that always finds something, so `atf check` can be seen to gate."""

from atf import check


@check("every notebook is called work")
def _(suite):
    for name, node in suite.suite.instances.items():
        if type(node).__name__ == "Notebook" and name != "work":
            yield name, "it is not called work"
'''

BROKEN_RESOURCES = '''\
"""A suite that is wrong on purpose, one mistake per name."""

from atf import filesystem


@filesystem(unique_by="path")
class Notebook:
    path: str


work = Notebook(path="notebooks/work")
spare = Notebook(path="notebooks/spare")
'''

AMBIGUOUS = '''\
"""Two notebooks in scope, and a parameter that cannot say which."""

from resources import Notebook


def test_two_of_a_kind(work: Notebook, spare: Notebook, notebook: Notebook):
    raise AssertionError("this body must never run")
'''

UNKNOWN_SENTENCE = """\
Feature: a sentence nobody taught

  Scenario: it says something ATF was never told
    Given the notebook "work"
    Then it does the thing
"""

scaffolded = Workspace(
    path="suite",
    files={
        "atf.yaml": MANIFEST,
        "resources.py": RESOURCES,
        "conftest.py": CONFTEST,
        "vocabulary.py": INNER_VOCABULARY,
        "specs/notes.feature": SPEC,
        "specs/test_both_surfaces.py": PYTEST_SIDE,
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


broken = Workspace(
    path="broken",
    files={
        "atf.yaml": MANIFEST,
        "resources.py": BROKEN_RESOURCES,
        "conftest.py": CONFTEST,
        "vocabulary.py": BAD_VOCABULARY,
        "specs/test_ambiguous.py": AMBIGUOUS,
        "specs/unknown.feature": UNKNOWN_SENTENCE,
    },
)
