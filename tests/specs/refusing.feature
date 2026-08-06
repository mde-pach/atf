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
