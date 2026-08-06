Feature: what a run leaves behind

  @run
  Scenario: a resource scoped to one test is gone when the run ends
    Given the workspace "scaffolded"
    When I run "run" as "testing"
    And I run "status local scratch" as "afterwards"
    Then the testing field "exit_code" is "0"
    And the afterwards field "output" contains "absent"

  @run
  Scenario: a resource scoped to the run is gone when the run ends
    Given the workspace "scaffolded"
    When I run "run" as "testing"
    And I run "status local weekly" as "afterwards"
    Then the afterwards field "output" contains "absent"

  @make
  Scenario: a persistent resource is still there afterwards
    Given the workspace "scaffolded"
    When I run "make local standup"
    And I run "run" as "testing"
    Then "notebooks/work/standup.md" holds "stand up\n"

  @run
  Scenario: teardown removes a child before the parent it hangs off
    Given the workspace "scaffolded"
    When I run "run" as "testing"
    Then the testing field "exit_code" is "0"
    And "sketches/pad" is not there
