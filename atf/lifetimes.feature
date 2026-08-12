Feature: how long a thing lives, and what a run leaves behind

  Nobody picks a span. Each rule gives the weakest lifetime that is still safe, and these scenarios
  are what holds the reading honest.

  Scenario: something a scenario changes is gone when the test ends
    Given a suite on disk
    When I run "plan local standup --apply"
    Then the command succeeded
    When I run "run"
    Then the command succeeded
    When I run "plan local standup"
    Then it mentions "will be made"

  Scenario: something resolved rather than declared is gone when the run ends
    Given a suite on disk
    When I run "run"
    Then the command succeeded
    When I run "plan local resolved"
    Then it mentions "will be resolved when asked for"

  Scenario: something declared with fixed values is still there afterwards
    Given a suite on disk
    When I run "plan local retro --apply"
    And I run "run"
    Then "notebooks/work/retro.md" holds "retro\n"

  Scenario: teardown removes a child before the parent it hangs off
    Given a suite on disk
    When I run "run"
    Then the command succeeded
    And "sketches/pad" is not there

  Scenario: a copy varied on a recognised field leaves nothing behind
    Given a suite on disk
    When I run "run"
    Then the command succeeded
    And "notebooks/work/twice.md" is not there

  Scenario: nothing outlives what it depends on, and says which one
    Given a suite on disk
    When I run "plan local --lives"
    Then the command succeeded
    And it mentions "it cannot outlive wandering"
