Feature: what a run leaves behind for next time

  A report is a flag on the command that produced the run, not a concept beside history.

  Scenario: a run is recorded and explaining a scenario reads it back
    Given a suite on disk
    When I run "run"
    Then its exit code is 0
    When I run "explain 'a draft is arranged for one test'"
    Then it mentions "passed"

  Scenario: a report is written where a pipeline will collect it
    Given a suite on disk
    When I run "run --report ctrf:.workspaces/suite/out.json"
    Then the command succeeded
    And it mentions "wrote"
    And "out.json" contains "summary"

  Scenario: a report written here can be brought back as a run from elsewhere
    Given a suite on disk
    When I run "run --report ctrf:.workspaces/suite/out.json"
    Then the command succeeded
    When I run "run --env theirs --import .workspaces/suite/out.json"
    Then its exit code is 0
    And it mentions "imported"

  Scenario: a format the suite taught is a format --report accepts
    Given a suite on disk
    When I run "run --report tally:.workspaces/suite/tally.txt"
    Then the command succeeded
    And "tally.txt" contains "local"
    And "tally.txt" contains "passed"

  Scenario: nothing is recorded when the run never starts
    Given a suite on disk
    When I run "run --select notabene --json"
    Then its exit code is 2
    When I run "explain"
    Then the command succeeded
