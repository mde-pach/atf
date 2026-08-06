Feature: the sentences a suite can say

  @run
  Scenario: a scenario and a pytest function reach the same engine
    Given the workspace "scaffolded"
    When I run "run"
    Then the command succeeded
    And the result lists "notes.feature" before "test_both_surfaces.py"

  @run
  Scenario: a phrase stands for the sentences under it, and phrases nest
    Given the workspace "scaffolded"
    When I run "run -k phrase"
    Then the command succeeded

  @run
  Scenario: a variation changes one field, and a continuation adds another
    Given the workspace "scaffolded"
    When I run "run -k field"
    Then the command succeeded

  @run
  Scenario: an outline runs one test per row of its examples
    Given the workspace "scaffolded"
    When I run "run --dry-run"
    Then the result field "output" contains "every notebook is arranged the same way"
