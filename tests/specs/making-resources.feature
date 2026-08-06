Feature: making what a suite declares

  @make
  Scenario: a dependency is made before the resource that names it
    Given the workspace "scaffolded"
    When I run "make local standup"
    Then the command succeeded
    And the result lists "work" before "standup"

  @make
  Scenario: making twice recognises rather than duplicates
    Given the workspace "scaffolded"
    When I run "make local standup" as "first"
    And I run "make local standup" as "second"
    Then the first field "output" contains "created"
    And the second field "output" contains "unchanged"

  @make
  Scenario: a resource the environment owns is named, not made
    Given the workspace "scaffolded"
    When I run "make local archived"
    Then the result field "exit_code" is "1"
    And the result field "output" contains "require"
    And "archive/2025.md" is not there

  @make
  Scenario: an environment that may not be changed makes nothing
    Given the workspace "scaffolded"
    When I run "make readonly standup --json"
    Then the command refused, saying "environment_immutable"

  @make
  Scenario: drift is reported against the declaration
    Given the workspace "scaffolded"
    When I run "make local standup"
    And somebody changes "notebooks/work/standup.md" to "tampered"
    And I run "status local standup" as "after"
    Then the after field "output" contains "updated"
    And the after field "output" contains "text"

  @make
  Scenario: reconciliation writes the declared value back
    Given the workspace "scaffolded"
    When I run "make local standup"
    And somebody changes "notebooks/work/standup.md" to "tampered"
    And I run "make local standup" as "repair"
    Then the repair field "exit_code" is "0"
    And "notebooks/work/standup.md" holds "stand up\n"

  @make
  Scenario: a field nobody declared is left alone
    Given the workspace "scaffolded"
    When I run "make local standup"
    And somebody changes "notebooks/work/untracked.md" to "mine"
    And I run "make local" as "again"
    Then "notebooks/work/untracked.md" holds "mine"

  @status
  Scenario: status reports absence as information and never gates
    Given the workspace "scaffolded"
    When I run "status local"
    Then the command succeeded
    And the result field "output" contains "absent"
