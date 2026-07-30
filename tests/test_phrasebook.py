"""The layer between a domain sentence and a primitive claim.

Two halves, tested separately. Reading a phrasebook is pure and is tested directly; running one is
only meaningful inside a real suite, so those tests write a phrasebook into the sample project and
run it in its own process — exactly as a consumer would.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atf.spec.phrasebook import MARKER, Line, Phrase, PhrasebookError, load, make_step, path_for
from tests.sample_project import run_pytest, write_spec


def book(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "phrasebook.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ---- reading one -----------------------------------------------------------


def test_a_phrase_is_a_sentence_and_the_steps_it_stands_for(tmp_path):
    phrases = load(
        book(
            tmp_path,
            """
'it is refused because "{reason}"':
  - the result field "exit_code" is "2"
  - the result field "output" contains "{reason}"
""",
        )
    )
    assert phrases == [
        Phrase(
            pattern='it is refused because "{reason}"',
            expands_to=(
                Line('the result field "exit_code" is "2"'),
                Line('the result field "output" contains "{reason}"'),
            ),
            captures=("reason",),
        )
    ]


def test_one_step_may_be_written_without_a_list(tmp_path):
    phrases = load(book(tmp_path, "'the command succeeds': the result field \"exit_code\" is \"0\"\n"))
    assert phrases[0].expands_to == (Line('the result field "exit_code" is "0"'),)


def test_no_phrasebook_is_no_phrases_rather_than_an_error(tmp_path):
    assert load(tmp_path / "nothing.yaml") == []
    assert load(book(tmp_path, "")) == []


def test_a_phrase_that_stands_for_another_phrase_is_refused_by_name(tmp_path):
    """Flat, one level, no recursion — the guard against a badly designed programming language."""
    with pytest.raises(PhrasebookError) as caught:
        load(
            book(
                tmp_path,
                """
'the run is clean':
  - it went well
'it went well':
  - the result field "exit_code" is "0"
""",
            )
        )
    assert "is the phrase 'it went well'" in str(caught.value)
    assert "write out the steps here instead" in str(caught.value)


def test_a_phrase_standing_for_itself_is_refused_too(tmp_path):
    with pytest.raises(PhrasebookError) as caught:
        load(book(tmp_path, "'it went well':\n  - it went well\n"))
    assert "never for another phrase" in str(caught.value)


def test_a_step_using_a_capture_the_phrase_does_not_take_is_refused(tmp_path):
    with pytest.raises(PhrasebookError) as caught:
        load(book(tmp_path, "'it is refused because \"{reason}\"':\n  - the result field \"{code}\" is \"2\"\n"))
    assert "uses {code}, which the phrase does not capture" in str(caught.value)
    assert "it captures: reason" in str(caught.value)


def test_a_step_is_read_as_the_line_it_was_written_as(tmp_path):
    """YAML would rather a step were something else, and a step is a line of English.

    A colon and a space start a mapping, so `contains "registered: env, now"` loads as a dict;
    `true` loads as a boolean. Both are sentences. Reading them from the document tree rather than
    from loaded values takes the footgun away instead of asking every author to know about it.
    """
    phrases = load(
        book(
            tmp_path,
            '''
'it lists them':
  - the result field "output" contains "registered: env, now"
  - the result field "flag" is "true"
  - 'quoting still works: and still means what it means'
''',
        )
    )
    assert phrases[0].expands_to == (
        Line('the result field "output" contains "registered: env, now"'),
        Line('the result field "flag" is "true"'),
        Line("quoting still works: and still means what it means"),
    )


def test_a_comment_after_a_step_is_not_part_of_it(tmp_path):
    """A node's end mark runs on to the next token, past the blank lines and the comment."""
    phrases = load(
        book(
            tmp_path,
            '''
'it lists them':
  - the result field "output" contains "registered: env, now"

# something else entirely
'and this':
  - the owner "primary" exists
''',
        )
    )
    assert phrases[0].expands_to == (Line('the result field "output" contains "registered: env, now"'),)


# ---- a step that takes a table ----------------------------------------------


def test_a_step_that_takes_a_table_carries_its_rows(tmp_path):
    """Written the way YAML writes a mapping, because a step that takes a table ends with a colon
    and so does a mapping key. No new format: an ordinary one-key mapping.
    """
    phrases = load(
        book(
            tmp_path,
            """
'the account is set up the way a new customer should be':
  - the account "primary" is:
      plan: free
      seats: 1
      trial_ends_at: "#datetime"
""",
        )
    )
    assert phrases[0].expands_to == (
        Line(
            text='the account "primary" is:',
            rows=(("plan", "free"), ("seats", "1"), ("trial_ends_at", "#datetime")),
        ),
    )


def test_a_line_with_rows_hands_them_over_the_way_a_table_arrives():
    line = Line(text='the account "primary" is:', rows=(("plan", "free"),))
    assert line.datatable == [["plan", "free"]]
    assert Line(text="the account is there").datatable is None


def test_a_step_that_merely_contains_a_colon_is_still_a_line(tmp_path):
    """The distinction that matters: a table step's value is a *mapping*, and a sentence YAML found
    structure in has a scalar. Both are one-key mappings to YAML; only one of them is a table.
    """
    written = 'the result field "output" contains "registered: env, now"'
    phrases = load(book(tmp_path, f"'it lists them':\n  - {written}\n"))
    assert phrases[0].expands_to[0].rows == ()
    assert phrases[0].expands_to[0].text == written


def test_an_unquoted_marker_is_a_comment_and_is_refused_by_name(tmp_path):
    """`plan: #str` is a key with a comment after it. The claim would otherwise pass for the wrong
    reason, which is the failure mode a checker exists for.
    """
    with pytest.raises(PhrasebookError) as caught:
        load(
            book(
                tmp_path,
                """
'the account is set up right':
  - the account "primary" is:
      plan: #str
""",
            )
        )
    assert "holds nothing" in str(caught.value)
    assert 'plan: "#str"' in str(caught.value)


def test_a_row_using_a_capture_the_phrase_does_not_take_is_refused(tmp_path):
    """Checked in the rows as well as in the line: a cell reaching for a capture the sentence never
    took would otherwise run with a brace still in it.
    """
    with pytest.raises(PhrasebookError) as caught:
        load(
            book(
                tmp_path,
                """
'the account is on the "{plan}" plan':
  - the account "primary" is:
      plan: "{tier}"
""",
            )
        )
    assert "uses {tier}, which the phrase does not capture" in str(caught.value)


def test_a_phrase_standing_for_nothing_is_refused(tmp_path):
    with pytest.raises(PhrasebookError) as caught:
        load(book(tmp_path, "'it went well': []\n"))
    assert "stands for nothing" in str(caught.value)


def test_every_problem_is_reported_not_only_the_first(tmp_path):
    with pytest.raises(PhrasebookError) as caught:
        load(
            book(
                tmp_path,
                """
'first "{a}"':
  - the result field "{b}" is "1"
'second':
  - the result field "{c}" is "2"
""",
            )
        )
    assert len(caught.value.problems) == 2


def test_something_that_is_not_a_mapping_is_refused(tmp_path):
    with pytest.raises(PhrasebookError) as caught:
        load(book(tmp_path, "- one\n- two\n"))
    assert "must be a mapping" in str(caught.value)


def test_yaml_that_will_not_parse_says_so(tmp_path):
    with pytest.raises(PhrasebookError) as caught:
        load(book(tmp_path, "'unbalanced: [\n"))
    assert "could not be read as YAML" in str(caught.value)


def test_the_phrasebook_lives_beside_the_features_it_is_written_for():
    assert path_for(Path("/suite/specs")).name == "phrasebook.yaml"
    assert path_for(Path("/suite/specs")).parent.name == "specs"


# ---- what it registers -----------------------------------------------------


def test_a_registered_phrase_declares_the_captures_it_takes():
    """pytest-bdd hands a step only the parameters its signature names."""
    from inspect import signature

    phrase = Phrase(
        'it is refused because "{reason}"', (Line('the result field "output" contains "{reason}"'),), ("reason",)
    )
    function = make_step(phrase, Path("/suite/specs/phrasebook.yaml"))
    assert list(signature(function).parameters) == ["request", "reason"]


def test_a_registered_phrase_says_where_it_came_from_and_what_it_stands_for():
    """Discovery reads this to tell a phrase from a step, and to work out what it needs."""
    phrase = Phrase("the command succeeds", (Line('the result field "exit_code" is "0"'),))
    marked = getattr(make_step(phrase, Path("/suite/specs/phrasebook.yaml")), MARKER)
    assert marked["file"].endswith("phrasebook.yaml")
    assert marked["expands_to"] == ['the result field "exit_code" is "0"']


def test_a_phrase_describes_itself_by_what_it_stands_for():
    phrase = Phrase(
        "the command succeeds",
        (Line('the result field "exit_code" is "0"'), Line('the account "primary" exists')),
    )
    assert phrase.summary == (
        'Says in one line: the result field "exit_code" is "0"; the account "primary" exists'
    )


# ---- running one -----------------------------------------------------------


def with_phrasebook(project: Path, text: str) -> None:
    (project / "specs" / "phrasebook.yaml").write_text(text, encoding="utf-8")


def test_a_phrase_runs_every_step_it_stands_for(project):
    with_phrasebook(
        project,
        """
'the account is on the standard plan':
  - the account "primary" exists
  - the account "primary" field "plan" is "standard"
""",
    )
    write_spec(
        project,
        "phrased",
        """Feature: Phrases
  Scenario: A sentence stands for two claims
    Given the account "primary"
    Then the account is on the standard plan
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_phrased.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_what_a_phrase_captures_reaches_the_steps_it_stands_for(project):
    with_phrasebook(
        project,
        '''
'the account is on the "{plan}" plan':
  - the account "primary" field "plan" is "{plan}"
''',
    )
    write_spec(
        project,
        "captured",
        """Feature: Phrases
  Scenario: The value written in the sentence reaches the claim
    Given the account "primary"
    Then the account is on the "standard" plan
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_captured.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_failing_step_names_the_phrase_and_the_step_inside_it(project):
    """A reader who wrote a sentence must not be handed a stack trace about a field."""
    with_phrasebook(project, "'the account is free':\n  - the account \"primary\" field \"plan\" is \"free\"\n")
    write_spec(
        project,
        "wrong_phrase",
        """Feature: Phrases
  Scenario: The sentence does not hold
    Given the account "primary"
    Then the account is free
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_wrong_phrase.py")
    assert result.returncode != 0
    assert "'the account is free' says 'the account \"primary\" field \"plan\" is \"free\"'" in result.stdout
    assert 'is "standard", not "free"' in result.stdout


def test_a_phrase_standing_for_a_step_nothing_defines_says_so(project):
    with_phrasebook(project, "'the account is fine':\n  - the account \"primary\" smells right\n")
    write_spec(
        project,
        "unknown_step",
        """Feature: Phrases
  Scenario: The phrase names something no step is worded as
    Given the account "primary"
    Then the account is fine
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_unknown_step.py")
    assert result.returncode != 0
    assert "no then step this feature can reach is worded that way" in result.stdout


def test_a_phrase_runs_its_steps_as_the_kind_of_step_it_was_said_as(project):
    """`When the developer …` stands for actions; the same sentence under `Then` would stand for claims."""
    with_phrasebook(project, "'the plan is read twice':\n  - I read its plan\n  - I read its plan\n")
    write_spec(
        project,
        "as_a_when",
        """Feature: Phrases
  Scenario: A phrase used as a When runs When steps
    Given the account "primary"
    When the plan is read twice
    Then the result field "plan" is "standard"
""",
        '''

from pytest_bdd import when


@when("I read its plan")
def _(context):
    context.result = {"plan": context.account["plan"]}
''',
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_as_a_when.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_placeholder_inside_a_phrase_resolves_like_any_other(project):
    """A step inside a phrase never reaches pytest-bdd's hook, so the phrase resolves them itself."""
    with_phrasebook(
        project,
        '''
'the project belongs to the account':
  - the project "alpha" field "account_id" is "${accounts.primary.id}"
''',
    )
    write_spec(
        project,
        "placeheld",
        """Feature: Phrases
  Scenario: A node reference inside a phrase still resolves
    Given the project "alpha"
    Then the project belongs to the account
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_placeheld.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_broken_phrasebook_stops_the_suite_rather_than_being_ignored(project):
    with_phrasebook(project, "'a':\n  - b\n'b':\n  - the account \"primary\" exists\n")
    write_spec(
        project,
        "broken_book",
        """Feature: Phrases
  Scenario: Nothing should run
    Given the account "primary"
""",
    )
    result = run_pytest(project, "-q", "-p", "no:randomly", "specs/steps/test_broken_book.py")
    assert result.returncode != 0
    assert "invalid phrasebook" in result.stdout + result.stderr
