Feature: the sentences a suite can say

  One surface, and one library. What a Python test gets is the same resolution, the same spans and
  the same teardown — and a number in `atf plan`, because it is a hole in the spec.

  Scenario: a scenario and a python test reach the same resolver
    Given a suite on disk
    When I run "run --dry-run"
    Then the command succeeded
    And it lists "notes.feature" before "test_both_ways.py"

  Scenario: a phrase stands for the sentences under it, and phrases nest
    Given a suite on disk
    When I run "run -k phrase"
    Then the command succeeded

  Scenario: a named situation stands where a Background would have
    Given a suite on disk
    When I run "run -k situation"
    Then the command succeeded

  Scenario: giving the resolver an argument bends one declared thing
    Given a suite on disk
    When I run "run -k bent"
    Then the command succeeded

  Scenario: a continuation names one more field
    Given a suite on disk
    When I run "run -k continuation"
    Then the command succeeded

  Scenario: `it` is whatever last happened, and nothing names a result
    Given a suite on disk
    When I run "run -k back"
    Then the command succeeded

  Scenario: a kind asks for a sort of thing where a value would be wrong
    Given a suite on disk
    When I run "run -k kind"
    Then the command succeeded

  Scenario: a scenario that promises nothing has its claims drafted back into it
    Given the workspace "drafting"
    When I run "--config .workspaces/drafting/atf.yaml run --accept"
    Then the command succeeded
    And it mentions "drafted"
    And "atf/draft.feature" in the drafting suite contains "Then its path is"

  Scenario: what --accept drafted runs green when it is run again
    Given the workspace "drafting"
    When I run "--config .workspaces/drafting/atf.yaml run --accept"
    Then its exit code is 0
    When I run "--config .workspaces/drafting/atf.yaml run"
    Then the command succeeded

  Scenario: the contract every system holds is a feature file, run like everything else
    Given a suite on disk
    When I run "run --contract -k contract"
    Then the command succeeded

  Scenario: `Example:` is a plain scenario, spelled the way Example Mapping spells it
    Given a suite on disk
    When I run "run -k example"
    Then the command succeeded
