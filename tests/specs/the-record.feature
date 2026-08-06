Feature: what a run leaves behind for next time

  @run
  Scenario: a run is recorded and history reads it back
    Given the workspace "scaffolded"
    When I run "run" as "first"
    And I run "history --env local" as "recorded"
    Then the first field "exit_code" is "0"
    And the recorded field "output" contains "passing"

  @run
  Scenario: a report is written where a pipeline will collect it
    Given the workspace "scaffolded"
    When I run "run --report ctrf:.workspaces/suite/out.json"
    Then the command succeeded
    And the result field "output" contains "wrote"
    And "out.json" contains "summary"

  @run
  Scenario: a report written here can be imported as a run from elsewhere
    Given the workspace "scaffolded"
    When I run "run --report ctrf:.workspaces/suite/out.json"
    And I run "import-run staging .workspaces/suite/out.json" as "imported"
    And I run "history --env staging" as "elsewhere"
    Then the imported field "exit_code" is "0"
    And the elsewhere field "output" contains "imported"

  @run
  Scenario: a format the suite registered is a format --report accepts
    Given the workspace "scaffolded"
    When I run "run --report tally:.workspaces/suite/tally.txt"
    Then the command succeeded
    And "tally.txt" contains "local"
    And "tally.txt" contains "passed"

  @run
  Scenario: nothing is recorded when the run never starts
    Given the workspace "scaffolded"
    When I run "run --select +notabene" as "refused"
    And I run "history --env local" as "recorded"
    Then the refused field "exit_code" is "2"
    And the recorded field "output" contains "no runs recorded"
