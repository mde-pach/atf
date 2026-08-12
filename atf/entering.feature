Feature: put me inside this failure

  A red test is where a person is most stuck and least helped. `atf enter` arranges the scenario,
  replays it to the line that stopped, and hands you a prompt that speaks the suite's own language.

  Scenario: entering a scenario replays it and says where it stopped
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml enter 'a field claimed to be a kind it is not' --say done"
    Then the command succeeded
    And it mentions "arranged, replayed to the failing line"
    And it mentions "✓ Given the note \"standup\""
    And it mentions "✗ Then the note \"standup\" path is any uuid"

  Scenario: naming a thing reads it from the environment now
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml enter 'a field claimed to be a kind it is not' --say standup --say done"
    Then the command succeeded
    And it mentions "a note · present"
    And it mentions "lives"

  Scenario: any sentence the suite knows runs for real, including one this scenario never had
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml enter 'a field claimed to be a kind it is not' --say 'the notebook \"work\" exists' --say done"
    Then the command succeeded
    And it does not mention "no step is written"

  Scenario: a sentence nobody taught is answered with the nearest ones ATF does know
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml enter 'a field claimed to be a kind it is not' --say 'it does the thing' --say done"
    Then the command succeeded
    And it mentions "The nearest ATF knows"

  Scenario: next advances one sentence
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml enter 'a field claimed to be a kind it is not' --say next --say done"
    Then the command succeeded
    And it mentions "the scenario is finished"

  Scenario: entering with nothing to enter says so rather than failing
    Given a suite on disk
    When I run "enter --json"
    Then the command refused, saying "usage"
    And it mentions "nothing has failed"

  Scenario: entering the last failure needs no argument
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run"
    Then its exit code is 1
    When I run "--config .workspaces/contrary/atf.yaml enter --say done"
    Then the command succeeded
    And it mentions "arranged, replayed to the failing line"
