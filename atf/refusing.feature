Feature: what a suite cannot be written as

  Every refusal here names what covers it. An unanswered question is where people invent their own
  thing, so the message is the answer.

  Scenario: two of a kind in scope is refused before any test body runs
    Given a suite that is wrong on purpose
    When I run "--config .workspaces/broken/atf.yaml run"
    Then its exit code is 2
    And it mentions "is ambiguous"
    And it mentions "spare, work"

  Scenario: a sentence nobody taught names the nearest ones ATF does know
    Given a suite that is wrong on purpose
    When I run "--config .workspaces/broken/atf.yaml run"
    Then it mentions "no step is written"
    And it mentions "The nearest ATF knows"

  Scenario: a scenario that arranges after it has acted is refused before anything runs
    Given a suite that is wrong on purpose
    When I run "--config .workspaces/broken/atf.yaml run"
    Then its exit code is 2
    And it mentions "has already acted"
    And it mentions "Every Given comes first"

  Scenario: every fault is reported at once, not the first one
    Given a suite that is wrong on purpose
    When I run "--config .workspaces/broken/atf.yaml run"
    Then it mentions "this suite cannot be run as written"
    And it mentions "is ambiguous"
    And it mentions "no step is written"

  Scenario: a field the class never declared is refused where it is written
    Given the workspace "mistyped"
    When I run "--config .workspaces/mistyped/atf.yaml plan local"
    Then its exit code is 2
    And it mentions "txt"
    And it mentions "declares path, text"

  Scenario: an Examples table is refused, and the phrase that covers it is written out
    Given the workspace "refused_table"
    When I run "--config .workspaces/refused-table/atf.yaml plan local"
    Then its exit code is 2
    And it mentions "not in this language"
    And it mentions "Phrase: rejecting the address"

  Scenario: a Background is refused, and the named situation that covers it is written out
    Given the workspace "refused_background"
    When I run "--config .workspaces/refused-background/atf.yaml plan local"
    Then it mentions "It degrades the graph"
    And it mentions "Phrase: a busy account"

  Scenario: a claim that does not hold says which side is which
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run"
    Then its exit code is 1
    And it mentions "is not a UUID"

  Scenario: text is never the number that spells it
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run"
    Then it mentions "and this wants 0"

  Scenario: a number compared with quoted text says which two words fix it
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run"
    Then it mentions "drop the quotes"

  Scenario: a failure prints the chain that put the thing under it there
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run"
    Then it mentions "standup"
    And it mentions "present"

  Scenario: every failure ends with the command that investigates it, by name
    Given the workspace "contrary"
    When I run "--config .workspaces/contrary/atf.yaml run"
    Then it mentions "atf enter \"a field claimed to be a kind it is not\""
