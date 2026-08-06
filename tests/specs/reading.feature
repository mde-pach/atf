Feature: reading a suite without running it

  @impact
  Scenario: impact answers what breaks, off the graph and not off history
    Given the workspace "scaffolded"
    When I run "impact work"
    Then the command succeeded
    And the result field "output" contains "standup"
    And the result field "output" contains "retro"

  @impact
  Scenario: impact on a resource nothing depends on is an answer, not a failure
    Given the workspace "scaffolded"
    When I run "impact archived"
    Then the command succeeded

  @impact
  Scenario: impact naming a resource the suite does not declare never starts
    Given the workspace "scaffolded"
    When I run "impact nosuchthing --json"
    Then the command refused, saying "usage"

  @unused
  Scenario: unused reports by default and gates only when asked
    Given the workspace "scaffolded"
    When I run "unused" as "reporting"
    And I run "unused --strict" as "gating"
    Then the reporting field "exit_code" is "0"
    And the gating field "exit_code" is "1"

  @check
  Scenario: check finds nothing wrong with a suite that is well formed
    Given the workspace "scaffolded"
    When I run "check"
    Then the command succeeded
    And the result field "output" contains "no faults"

  @docs
  Scenario: docs renders the specs and labels what nobody has run
    Given the workspace "scaffolded"
    When I run "docs --out .workspaces/suite/rendered"
    Then the command succeeded
    And "rendered/notes.md" contains "never run"
    And "rendered/notes.md" contains "Given"

  @docs
  Scenario: docs carries the verdict of the last run
    Given the workspace "scaffolded"
    When I run "run"
    And I run "docs --out .workspaces/suite/rendered" as "rendering"
    Then the rendering field "exit_code" is "0"
    And "rendered/notes.md" contains "passing"

  @check
  Scenario: check exits 1 on its findings, because they are its answer
    Given the workspace "broken"
    When I run "--config .workspaces/broken/atf.yaml check"
    Then the result field "exit_code" is "1"
    And the result field "output" contains "it is not called work"

  @docs
  Scenario: docs can render the specs alone, reading no history
    Given the workspace "scaffolded"
    When I run "run"
    And I run "docs --out .workspaces/suite/plain --no-verdicts" as "plain"
    Then the plain field "exit_code" is "0"
    And "plain/notes.md" contains "Given"

  @status
  Scenario: the same field family reads a slot a test produced
    Given the workspace "scaffolded"
    When I run "status local" as "reading"
    Then the reading field "output" is not empty
    And the reading field "output" does not contain "unreachable"
    And the reading field "exit_code" is not "1"
    And the reading field "nothing" is empty

  @status
  Scenario: status can be asked for only what is not there
    Given the workspace "scaffolded"
    When I run "make local standup"
    And I run "status local --absent-only" as "missing"
    Then the missing field "output" does not contain "standup"
    And the missing field "output" contains "absent"

  @check
  Scenario: check gates on what nothing asks for only when told to
    Given the workspace "scaffolded"
    When I run "--config .workspaces/suite/atf.yaml check" as "quiet"
    And I run "--config .workspaces/suite/atf.yaml check --strict" as "gating"
    Then the quiet field "exit_code" is "0"
    And the gating field "exit_code" is "1"
    And the gating field "output" contains "nothing asks for it"
