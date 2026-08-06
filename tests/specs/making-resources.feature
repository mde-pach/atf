Feature: making what a suite declares

  @make
  Scenario: a dependency is made before the resource that names it
    Given the workspace "scaffolded"
    When I run "make local"
    Then the command succeeded
    And the result lists "work" before "standup"

  @make
  Scenario: an environment that may not be changed makes nothing
    Given the workspace "scaffolded"
    When I run "make readonly --json"
    Then the command refused, saying "environment_immutable"

  @status
  Scenario: status reports absence as information and never gates
    Given the workspace "scaffolded"
    When I run "status local"
    Then the command succeeded
    And the result field "output" contains "absent"
