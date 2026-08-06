Feature: choosing what runs

  @run
  Scenario: a selection naming nothing the suite declares never starts
    Given the workspace "scaffolded"
    When I run "run --select +notebok --json"
    Then the command refused, saying "usage"

  @run
  Scenario: a selection naming a real resource nothing reaches is an answer
    Given the workspace "scaffolded"
    When I run "run --select +archived"
    Then the command succeeded

  @run
  Scenario: a tag nothing carries selects nothing and passes
    Given the workspace "scaffolded"
    When I run "run --tag nosuchtag"
    Then the command succeeded

  @run
  Scenario: a dry run says what it would run and runs none of it
    Given the workspace "scaffolded"
    When I run "run --dry-run" as "planned"
    And I run "status local scratch" as "afterwards"
    Then the planned field "exit_code" is "0"
    And the planned field "output" contains "tests selected"
    And the afterwards field "output" contains "absent"
