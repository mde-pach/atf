"""What ATF's own suite needs to exist: an ATF suite on disk, for ATF to be run against.

The recursion is real and it stops one level down. The scaffolded suite is a small, ordinary one —
lineage declared at the field that uses it, values resolution fills in, and something the
environment owns. ATF's suite makes it exist, runs `atf` against it, and claims on what came back.
"""

from atf import needs
from atf.resources.browser import Page
from atf.resources.filesystem import Tree
from atf.resources.process import Process

MANIFEST = """\
environments:
  local:
    owner: atf
    filesystem: { root: . }
    shell:      { prefix: "", cwd: . }
  theirs:
    from: local
    owner: them
"""

THINGS = '''\
"""A small, ordinary suite: lineage, every span, and something the environment owns.

The `__future__` import is here on purpose: a suite module is an ordinary Python module, and what a
linter or an editor adds to one must not be what stops the suite loading.
"""

from __future__ import annotations

from atf import needs
from atf.resources.filesystem import Directory, File


def a_line(notebook: Notebook) -> str:
    """A resolver that itself takes a thing — the whole power of the pattern, in one function."""
    return f"written in {notebook.path}\\n"


def a_notebook() -> str:
    """Somewhere nobody named. A resolved value, so anything holding one lives for the run."""
    from itertools import count

    a_notebook.n = getattr(a_notebook, "n", count(1))
    return f"notebooks/spare-{next(a_notebook.n)}"


class Notebook(Directory):
    path: Directory.Key[str] = needs(a_notebook)


class Note(File):
    notebook: Notebook = needs()          # this is the edge
    path: File.Key[str]
    text: str = needs(a_line)


class Card(File):
    """A field a scenario moves mid-test, and that is put back when the test ends."""

    path: File.Key[str]
    text: str


class Draft(File, lives="the test"):
    path: File.Key[str]
    text: str


class Sketchbook(Directory, lives="the test"):
    """A directory made for one test, which teardown can only remove once it is empty."""

    path: Directory.Key[str]


class Sketch(File, lives="the test"):
    sketchbook: Sketchbook = needs()
    path: File.Key[str]
    text: str


class Meeting(File, lives="the run"):
    path: File.Key[str]
    text: str


class Archive(File, owner="them"):
    """Somebody else\'s job. ATF names it rather than making one."""

    path: File.Key[str]


work = Notebook(path="notebooks/work")
spare = Notebook(path="notebooks/spare")
todo = Card(path="cards/today.md", text="todo\\n")
standup = Note(notebook=work, path="notebooks/work/standup.md", text="stand up\\n")
retro = Note(notebook=work, path="notebooks/work/retro.md", text="retro\\n")
resolved = Note(notebook=work, path="notebooks/work/resolved.md")
wandering = Notebook()
filed = Note(notebook=wandering, path="notebooks/filed.md", text="filed\\n")
scratch = Draft(path="drafts/scratch.md", text="scratch\\n")
weekly = Meeting(path="meetings/weekly.md", text="weekly\\n")
pad = Sketchbook(path="sketches/pad")
outline = Sketch(sketchbook=pad, path="sketches/pad/outline.md", text="outline\\n")
archived = Archive(path="archive/2025.md")
'''

SPEC = """\
Feature: notes

  Phrase: the notebook is there
    Then the notebook "work" exists

  Phrase: the working notebook holds a note
    Then the notebook is there
    And the note "standup" exists

  Phrase: I tick the card "{name}"
    When the card "{name}" text becomes "done"

  Phrase: a busy notebook
    Given the notebook "work"
    And the note "standup"
    And the note "retro"

  Scenario: a field changes mid-test, with nothing declared for it
    Given the card "todo"
    When the card "todo" text becomes "halfway"
    Then the card "todo" text is "halfway"

  Scenario: a phrase is what gives the change a domain verb
    Given the card "todo"
    When I tick the card "todo"
    Then the card "todo" text is "done"

  Scenario: a named situation stands where a Background would have
    Given a busy notebook
    Then the note "retro" exists

  Scenario: a draft is arranged for one test
    Given the draft "scratch"
    Then the draft "scratch" exists

  Scenario: a sketch is arranged inside a sketchbook made for the same test
    Given the sketch "outline"
    Then the sketch "outline" exists

  Scenario: the field family reads the negative as well as the positive
    Given the note "standup"
    Then the note "standup" text is not "nothing"
    And the note "standup" text does not contain "zzz"
    And the note "standup" nothing is missing

  Scenario: a kind asks for a sort of thing where a value would be wrong
    Given the note "standup"
    Then the note "standup" path is any text
    And the note "standup" text is any markdown
    And the note "standup" nothing is missing

  Scenario: a check this suite taught holds like a shipped one
    Given the note "standup"
    Then the note "standup" reads like a note

  Scenario: what an act produced is read back as `it`
    Given the note "standup"
    When I open the note "standup"
    Then its path is "notebooks/work/standup.md"

  Scenario: the previous is what happened before it
    Given the note "standup"
    When I open the note "standup"
    And I open the note "retro"
    Then its path is "notebooks/work/retro.md"
    And the previous path is "notebooks/work/standup.md"

  Scenario: a phrase says what several sentences say
    Given the note "standup"
    Then the working notebook holds a note

  Scenario: one field is bent for the length of one scenario
    Given the note "standup" with text "varied"
    Then the note "standup" text is "varied"

  Scenario: a continuation names one more field
    Given the note "standup" with text "twice"
    And with path "notebooks/work/twice.md"
    Then the note "standup" path is "notebooks/work/twice.md"

  Scenario: something whose parent was resolved cannot outlive it
    Given the note "filed"
    Then the note "filed" exists

  Scenario: a field nobody gave a value is filled by resolution
    Given the note "resolved"
    Then the note "resolved" text is "written in notebooks/work\\n"
"""

PYTHON_SIDE = '''\
"""The same behaviour as a scenario, written in Python. One resolver behind both.

This is the library, not a second surface. `atf plan` counts it, in the output everyone already
looks at, next to the thing it is a hole in.
"""

from things import Note, Notebook


def test_lineage_comes_along(standup: Note):
    assert standup.path == "notebooks/work/standup.md"


def test_asking_by_kind_gets_the_one_in_scope(work: Notebook, notebook: Notebook):
    assert notebook is work


def test_resolution_is_the_same_object(standup: Note, note: Note):
    """The scenario in `one-resolver-not-two`, as a test. This is the load-bearing one."""
    assert note is standup
'''


WORDS = '''\
"""What the scaffolded suite teaches: a kind, two checks, an act and a report format.

Two decorators. `@act` and `@check` are the whole of what a suite adds to the language, and a
`Phrase:` block is the whole of what it adds without Python.
"""

from atf import act, check, kind, report


@act(\'I open the note "{name}"\')
def _(name, atf):
    """An act whose return value becomes `it`. Nothing names it, and nothing has to."""
    return atf.look_up("note", name)


@kind("markdown")
def _(value):
    return str(value).endswith("\\n"), "it does not end in a newline"


@check(\'the {kind} "{name}" reads like a note\')
def _(kind, name, atf):
    text = (atf.look_up(kind, name) or {}).get("text", "")
    return bool(text.strip()), "it is empty"


@check("every note in this suite lives under a notebook")
def _(atf):
    """A suite convention, as a sentence.

    It used to be a Python registry and a command of its own. It is a scenario now, which means the
    rule a suite holds itself to is readable by the same people who read everything else.
    """
    astray = [
        name
        for name, node in atf.suite.instances.items()
        if type(node).__name__ == "Note" and not str(node.path).startswith("notebooks/")
    ]
    return not astray, f"{\', \'.join(astray)} is not under notebooks/"


@report("tally")
def _(run, path):
    """A line per test, which is the shortest thing a format can be."""
    lines = [f"{one.outcome} {one.test}" for one in run.outcomes]
    path.write_text(f"{run.environment}\\n" + "\\n".join(lines) + "\\n", encoding="utf-8")
'''

CONVENTION = """\
Feature: what this suite holds itself to

  Scenario: every note lives under a notebook
    Then every note in this suite lives under a notebook
"""

BROKEN_THINGS = '''\
"""A suite that is wrong on purpose, one mistake per name."""

from atf.resources.filesystem import Directory


class Notebook(Directory):
    path: Directory.Key[str]


work = Notebook(path="notebooks/work")
spare = Notebook(path="notebooks/spare")
'''

AMBIGUOUS = '''\
"""Two notebooks in scope, and a parameter that cannot say which."""

from things import Notebook


def test_two_of_a_kind(work: Notebook, spare: Notebook, notebook: Notebook):
    raise AssertionError("this body must never run")
'''

MISTYPED_THINGS = '''\
"""One thing setting a field its class never declared.

`txt` is a typo for `text`. Nothing but the class\'s own annotations says so, which is why this is
refused where it is written rather than carried to the system and written down.
"""

from atf.resources.filesystem import File


class Note(File):
    path: File.Key[str]
    text: str


standup = Note(path="notebooks/standup.md", txt="stand up\\n")
'''

ARRANGES_LATE = """\
Feature: a scenario that arranges after it has acted

  Scenario: it goes back for a thing once it has begun
    Given the notebook "work"
    When the notebook "work" path becomes "notebooks/moved"
    Given the notebook "spare"
    Then the notebook "spare" exists
"""

UNKNOWN_SENTENCE = """\
Feature: a sentence nobody taught

  Scenario: it says something ATF was never told
    Given the notebook "work"
    Then it does the thing
"""

A_TABLE = """\
Feature: a table, which is not in this language

  Scenario Outline: every notebook is arranged the same way
    Given the notebook "<which>"
    Then the notebook "<which>" exists

    Examples:
      | which |
      | work  |
"""

A_BACKGROUND = """\
Feature: a Background, which is not in this language

  Background:
    Given the notebook "work"

  Scenario: it inherits what it never asked for
    Then the notebook "work" exists
"""

CONTRARY = """\
Feature: claims that do not hold

  Scenario: a value that is what the claim says it is not
    Given the note "standup"
    Then the note "standup" path is not "notebooks/work/standup.md"

  Scenario: text that does contain what the claim says it does not
    Given the note "standup"
    Then the note "standup" text does not contain "stand"

  Scenario: a field claimed to be a kind it is not
    Given the note "standup"
    Then the note "standup" path is any uuid

  Scenario: text compared with the number that spells it
    Given the note "standup"
    Then the note "standup" path is 0

  Scenario: a number compared with the text that spells it
    When I run "true"
    Then its exit code is "0"
"""

NO_THEN = """\
Feature: a scenario that promises nothing

  Scenario: opening a note says what is in it
    Given the note "standup"
    When I open the note "standup"
"""


class Workspace(Tree, lives="the test"):
    """An ATF suite on disk: a manifest, and the one directory a suite lives in.

    `files` maps a path inside the workspace to that file's contents, and declaring them **makes
    this thing own the tree**. That matters here more than anywhere: the thing under test writes
    into this directory while a scenario runs, and teardown has to take all of it away.

    `lives` is written out because this is exactly the case ATF cannot see: the product mutates it
    behind ATF's back, through a shell command whose effect nothing declares.
    """

    path: Tree.Key[str]
    files: dict[str, str]


scaffolded = Workspace(
    path="suite",
    files={
        "atf.yaml": MANIFEST,
        "atf/things.py": THINGS,
        "atf/words.py": WORDS,
        "atf/notes.feature": SPEC,
        "atf/convention.feature": CONVENTION,
        "atf/test_both_ways.py": PYTHON_SIDE,
    },
)

broken = Workspace(
    path="broken",
    files={
        "atf.yaml": MANIFEST,
        "atf/things.py": BROKEN_THINGS,
        "atf/test_ambiguous.py": AMBIGUOUS,
        "atf/unknown.feature": UNKNOWN_SENTENCE,
        "atf/late.feature": ARRANGES_LATE,
    },
)

# One refusal per workspace: reading stops at the first file that will not parse, so two of them
# in one suite would mean only ever seeing the first message.
refused_table = Workspace(
    path="refused-table",
    files={"atf.yaml": MANIFEST, "atf/things.py": BROKEN_THINGS, "atf/table.feature": A_TABLE},
)

refused_background = Workspace(
    path="refused-background",
    files={"atf.yaml": MANIFEST, "atf/things.py": BROKEN_THINGS, "atf/background.feature": A_BACKGROUND},
)

mistyped = Workspace(
    path="mistyped",
    files={
        "atf.yaml": MANIFEST,
        "atf/things.py": MISTYPED_THINGS,
        "atf/nothing.feature": "Feature: nothing this suite gets far enough to run\n",
    },
)

contrary = Workspace(
    path="contrary",
    files={
        "atf.yaml": MANIFEST,
        "atf/things.py": THINGS,
        "atf/words.py": WORDS,
        "atf/contrary.feature": CONTRARY,
    },
)

drafting = Workspace(
    path="drafting",
    files={
        "atf.yaml": MANIFEST,
        "atf/things.py": THINGS,
        "atf/words.py": WORDS,
        "atf/draft.feature": NO_THEN,
    },
)


class Editor(Process):
    """An `atf edit` process serving one workspace.

    The command is fixed, so it is a plain default on the field. What varies is the workspace, and
    that is a field too — which is where a dependency is declared now.
    """

    command: Process.Key[str] = "uv run atf --config .workspaces/suite/atf.yaml edit --port 8791"
    port: int = 8791
    workspace: Workspace = needs()


class Screen(Page, lives="the test"):
    """A page of that editor.

    This used to be declared `when_absent="observe"`, to say ATF does not *make* a screen. That was
    a workaround: opening a page is exactly what making one is, and the thing the old declaration
    was really asking for — a page that does not answer is a failure with a reason — belongs to the
    scenario asking, which is where it now lives.
    """

    editor: Editor = needs()
    path: Page.Key[str]


editing = Editor(workspace=scaffolded)
catalogue = Screen(editor=editing, path="/catalogue")
spine = Screen(editor=editing, path="/graph")
small_lineage = Screen(editor=editing, path="/graph/outline")
crowded = Screen(editor=editing, path="/graph/work")
faults = Screen(editor=editing, path="/faults")
listing = Screen(editor=editing, path="/tests")
one_test = Screen(
    editor=editing,
    path="/tests/atf%2Fnotes.feature%3A%3Aa%20draft%20is%20arranged%20for%20one%20test",
)
past_runs = Screen(editor=editing, path="/activity")
theirs_screen = Screen(editor=editing, path="/catalogue?env=theirs")
composing = Screen(editor=editing, path='/composer?l=Given%7Cthe%20note%20%22standup%22')
