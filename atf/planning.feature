Feature: is this suite sound, and what will happen

  `atf plan` absorbed status, drift, adopt and check. It is one command because they were one
  question asked four ways, and it holds lint because lint has to be findable by somebody with no
  database on their laptop.

  Scenario: a plan says what is there, what is not, and what will be made
    Given a suite on disk
    When I run "plan local"
    Then the command succeeded
    And it mentions "absent"
    And it mentions "will be made"

  Scenario: applying a plan makes what is missing, parents first
    Given a suite on disk
    When I run "plan local standup --apply"
    Then the command succeeded
    And it lists "work" before "standup"
    And "notebooks/work/standup.md" holds "stand up\n"

  Scenario: applying twice recognises rather than duplicates
    Given a suite on disk
    When I run "plan local standup --apply"
    Then it mentions "created"
    When I run "plan local standup --apply"
    Then it mentions "unchanged"

  Scenario: a thing the environment owns is named, not made
    Given a suite on disk
    When I run "plan local --apply"
    Then it mentions "left alone"
    And "archive/2025.md" is not there

  Scenario: an environment ATF does not own makes nothing
    Given a suite on disk
    When I run "plan theirs --apply --json"
    Then the command refused, saying "environment_not_ours"

  Scenario: drift is reported against the declaration
    Given a suite on disk
    When I run "plan local standup --apply"
    And somebody changes "notebooks/work/standup.md" to "tampered"
    And I run "plan local"
    Then it mentions "drifted"
    And it mentions "text"

  Scenario: applying again writes the declared value back
    Given a suite on disk
    When I run "plan local standup --apply"
    And somebody changes "notebooks/work/standup.md" to "tampered"
    And I run "plan local standup --apply"
    Then the command succeeded
    And "notebooks/work/standup.md" holds "stand up\n"

  Scenario: a field nobody declared is left alone
    Given a suite on disk
    When I run "plan local standup --apply"
    And somebody changes "notebooks/work/untracked.md" to "mine"
    And I run "plan local --apply"
    Then "notebooks/work/untracked.md" holds "mine"

  Scenario: a plan never gates on absence, because absence is information
    Given a suite on disk
    When I run "plan local"
    Then the command succeeded
    And it mentions "absent"

  Scenario: a plan says how long each thing lives, and why
    Given a suite on disk
    When I run "plan local --lives"
    Then the command succeeded
    And it mentions "some scenario changes it"
    And it mentions "it is resolved rather than declared"
    And it mentions "it is declared with fixed values"

  Scenario: the python tests are counted, next to the thing they are a hole in
    Given a suite on disk
    When I run "plan local"
    Then it mentions "python tests using atf resources"
    And it mentions "not in the spec"

  Scenario: a suite with something wrong in it gates, and says every fault at once
    Given a suite that is wrong on purpose
    When I run "--config .workspaces/broken/atf.yaml plan local"
    Then its exit code is 1
    And it mentions "problems in the suite"
    And it mentions "no step is written"
