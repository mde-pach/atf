Feature: taking on a system that is already there

  @adopt
  Scenario: a system that cannot say what it holds is named, and nothing is written
    Given the workspace "scaffolded"
    When I run "adopt --json"
    Then the command refused, saying "usage"
    And the result field "output" contains "can say what it holds"

  @adopt
  Scenario: adopt refuses to overwrite a file that already declares something
    Given the workspace "scaffolded"
    When I run "adopt --out .workspaces/suite/resources.py --json"
    Then the command refused, saying "usage"
    And the result field "output" contains "already declares resources"
    And "resources.py" contains "class Notebook"

  @namespace
  Scenario: a run can be told the token its factories build names from
    Given the workspace "scaffolded"
    When I run "run --namespace pr-1234"
    Then the command succeeded
