Feature: what a suite cannot be run as written

  @run
  Scenario: two of a kind in scope is refused before any test body runs
    Given the workspace "broken"
    When I run "--config .workspaces/broken/atf.yaml run"
    Then the result field "exit_code" is "2"
    And the result field "output" contains "is ambiguous"
    And the result field "output" contains "spare, work"

  @run
  Scenario: a sentence nobody taught names the nearest ones ATF does know
    Given the workspace "broken"
    When I run "--config .workspaces/broken/atf.yaml run"
    Then the result field "output" contains "no step is written"
    And the result field "output" contains "The nearest ATF knows"

  @run
  Scenario: every fault is reported at once, not the first one
    Given the workspace "broken"
    When I run "--config .workspaces/broken/atf.yaml run"
    Then the result field "output" contains "this suite cannot be run as written"
    And the result field "output" contains "is ambiguous"
    And the result field "output" contains "no step is written"

  @run
  Scenario: a claim that does not hold turns the run red and says what it wanted
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run" as "red"
    Then the red field "exit_code" is "1"
    And the red field "output" contains "and the claim wants anything else"
    And the red field "output" contains "which contains"
    And the red field "output" contains "and the claim wants it empty"
    And the red field "output" contains "and the claim wants something in it"
