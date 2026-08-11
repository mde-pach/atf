Feature: what an environment holds, against what the declarations say

  @drift
  Scenario: an environment matching every declaration has no drift
    Given the workspace "scaffolded"
    When I run "make"
    And I run "drift" as "asking"
    Then the asking field "exit_code" is "0"
    And the asking field "output" contains "matches every declaration"

  @drift
  Scenario: a record changed by hand is reported against its declaration
    Given the workspace "scaffolded"
    When I run "make"
    And somebody changes "notebooks/work/standup.md" to "moved by hand"
    And I run "drift" as "asking"
    Then the asking field "exit_code" is "0"
    And the asking field "output" contains "standup"
    And the asking field "output" contains "text"

  @drift
  Scenario: drift gates only when it is asked to
    Given the workspace "scaffolded"
    When I run "make"
    And somebody changes "notebooks/work/standup.md" to "moved by hand"
    And I run "drift --strict" as "gating"
    Then the gating field "exit_code" is "1"

  @verify-adapter
  Scenario: an adapter is put through the contract against a copy it marks and removes
    Given the workspace "scaffolded"
    When I run "verify-adapter standup"
    Then the command succeeded
    And the result field "output" contains "`create` answers with the record it wrote"
    And the result field "output" contains "`delete` takes the resource away"

  @verify-adapter
  Scenario: what the contract wrote is gone, and the resource it stood in for is untouched
    Given the workspace "scaffolded"
    When I run "make"
    And I run "verify-adapter standup" as "contract"
    Then the contract field "exit_code" is "0"
    And "notebooks/work/standup.md-atf-verify" is not there
    And "notebooks/work/standup.md" contains "stand up"
