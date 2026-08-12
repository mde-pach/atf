Feature: what the command line promises

  Six commands, because fifteen was fifteen things to know exist.

  Scenario: the whole command surface is six things
    Given a suite on disk
    When I run "--help"
    Then the command succeeded
    And it mentions "init"
    And it mentions "plan"
    And it mentions "run"
    And it mentions "enter"
    And it mentions "explain"
    And it mentions "edit"

  Scenario: a run told not to make anything fails on what is missing
    Given a suite on disk
    When I run "run --no-make"
    Then its exit code is 1
    And it mentions "told not to make anything"

  Scenario: failed reselects what failed, and nothing once it passes
    Given a suite on disk
    When I run "run --no-make"
    Then its exit code is 1
    When I run "run --failed --dry-run"
    Then it mentions "tests selected"
    When I run "run"
    Then its exit code is 0
    When I run "run --failed --dry-run"
    Then it mentions "0 tests selected"

  Scenario: failed on an empty history selects nothing and passes
    Given a suite on disk
    When I run "run --failed"
    Then the command succeeded

  Scenario: init looks around, and says what it found
    Given a suite on disk
    When I run "init --no-run" in an empty directory
    Then the command succeeded
    And it mentions "found"
    And it mentions "atf.yaml"

  Scenario: init writes one directory, and nothing points at it
    Given a suite on disk
    When I run "init --no-run" in an empty directory
    Then the command succeeded
    And "fresh/atf.yaml" contains "owner: atf"
    And "fresh/atf/things.py" contains "needs()"
    And "fresh/atf/hello.feature" contains "Scenario:"

  Scenario: init writes no conftest, because there is nothing to enable
    Given a suite on disk
    When I run "init --no-run" in an empty directory
    Then the command succeeded
    And it does not mention "conftest"
    And "fresh/conftest.py" is not there

  Scenario: the scaffold it writes ends green against the real system
    Given a suite on disk
    When I run "init" in an empty directory
    Then the command succeeded
    And it mentions "green"

  Scenario: init refuses to overwrite what is already there
    Given a suite on disk
    When I run "init --no-run" in an empty directory
    Then its exit code is 0
    When I run "init --no-run" in an empty directory
    Then its exit code is 1
    And it mentions "already exists"
