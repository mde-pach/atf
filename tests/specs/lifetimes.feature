Feature: what a run leaves behind

  @run
  Scenario: a resource scoped to one test is gone when the run ends
    Given the workspace "scaffolded"
    When I run "run" as "testing"
    And I run "status local scratch" as "afterwards"
    Then the testing field "exit_code" is "0"
    And the afterwards field "output" contains "absent"
