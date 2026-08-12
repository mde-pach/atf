Feature: choosing what runs

  Selection reads the sentences rather than a label. A scenario saying `When I run "atf plan"` has
  already said which subcommand it exercises, so a convention stops needing enforcement.

  Scenario: selecting a thing runs the scenarios that reach it
    Given a suite on disk
    When I run "run --select standup --dry-run"
    Then the command succeeded
    And it mentions "tests selected"

  Scenario: selecting a kind runs every scenario that reaches one of them
    Given a suite on disk
    When I run "run --select note --dry-run"
    Then the command succeeded

  Scenario: selecting a phrase runs every scenario that says it
    Given a suite on disk
    When I run "run --select 'the notebook is there' --dry-run"
    Then the command succeeded

  Scenario: a selection naming nothing the suite declares never starts
    Given a suite on disk
    When I run "run --select notebok --json"
    Then the command refused, saying "usage"

  Scenario: a selection naming something nothing reaches is an answer
    Given a suite on disk
    When I run "run --select archived"
    Then the command succeeded

  Scenario: a tag survives for what is genuinely not derivable
    Given a suite on disk
    When I run "run --tag nosuchtag"
    Then the command succeeded

  Scenario: a dry run says what it would run and runs none of it
    Given a suite on disk
    When I run "run --dry-run"
    Then its exit code is 0
    And it mentions "tests selected"
    When I run "plan local scratch"
    Then it mentions "will be made"
