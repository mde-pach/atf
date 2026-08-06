Feature: what the command line promises

  @run
  Scenario: a run told not to make anything fails on what is missing
    Given the workspace "scaffolded"
    When I run "run --no-make"
    Then the result field "exit_code" is "1"
    And the result field "output" contains "told not to make anything"

  @run
  Scenario: failed reselects what failed, and nothing once it passes
    Given the workspace "scaffolded"
    When I run "run --no-make" as "broken"
    And I run "run --failed --dry-run" as "still"
    And I run "run" as "repaired"
    And I run "run --failed --dry-run" as "nothing"
    Then the broken field "exit_code" is "1"
    And the still field "output" contains "tests selected"
    And the repaired field "exit_code" is "0"
    And the nothing field "output" contains "0 tests selected"

  @run
  Scenario: failed on an empty history selects nothing and passes
    Given the workspace "scaffolded"
    When I run "run --failed"
    Then the command succeeded

  @impact
  Scenario: depth follows lineage only as far as it is told
    Given the workspace "scaffolded"
    When I run "impact work --depth 1 --resources-only" as "near"
    And I run "impact work --resources-only" as "far"
    Then the near field "output" contains "standup"
    And the far field "output" contains "standup"

  @init
  Scenario: init scaffolds a suite that immediately answers
    Given the workspace "scaffolded"
    When I run "init" in an empty directory
    Then the command succeeded
    And the result field "output" contains "atf.yaml"
    And "fresh/atf.yaml" contains "mutable: true"
    And "fresh/resources.py" contains "depends_on"

  @init
  Scenario: init refuses to overwrite what is already there
    Given the workspace "scaffolded"
    When I run "init" in an empty directory
    And I run "init" in an empty directory
    Then the result field "exit_code" is "1"
    And the result field "output" contains "already exists"

  @init
  Scenario: the scaffolded suite answers straight away
    Given the workspace "scaffolded"
    When I run "init" in an empty directory
    And I run "status" in an empty directory
    Then the command succeeded
