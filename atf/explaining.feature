Feature: tell me everything about this

  Four commands used to ask four questions about one object — what breaks if it changes, whether
  anything asks for it, why it is red, and what it has done before. Point at a thing; get its file.

  Scenario: explaining a thing says what it needs and what breaks with it
    Given a suite on disk
    When I run "explain work"
    Then the command succeeded
    And it mentions "needed by"
    And it mentions "if it changes"
    And it mentions "a phrase says what several sentences say"

  Scenario: explaining a thing says how long it lives, and why
    Given a suite on disk
    When I run "explain standup"
    Then it mentions "lives"
    And it mentions "some scenario changes it"

  Scenario: explaining a thing unfolds what resolution will call to produce one
    Given a suite on disk
    When I run "explain resolved"
    Then it mentions "to produce one"
    And it mentions "a_line"

  Scenario: explaining a thing nothing else needs is an answer, not a failure
    Given a suite on disk
    When I run "explain archived"
    Then the command succeeded

  Scenario: explaining a kind says what it resolves and who owns one
    Given a suite on disk
    When I run "explain note"
    Then the command succeeded
    And it mentions "resolves"
    And it mentions "owner"

  Scenario: explaining a system says the words it brings
    Given a suite on disk
    When I run "explain filesystem.file"
    Then the command succeeded
    And it mentions "kinds"

  Scenario: explaining a scenario folds its history into a sentence
    Given a suite on disk
    When I run "run"
    Then the command succeeded
    When I run "explain 'a draft is arranged for one test'"
    Then the command succeeded
    And it mentions "passed"

  Scenario: explaining a scenario that has never run says so
    Given a suite on disk
    When I run "explain 'a draft is arranged for one test'"
    Then it mentions "never run"

  Scenario: explaining a phrase says what it stands for and who reaches it
    Given a suite on disk
    When I run "explain 'the notebook is there'"
    Then the command succeeded
    And it mentions "it stands for"
    And it mentions "a phrase says what several sentences say"

  Scenario: explaining nothing says the shape of the suite and where to point next
    Given a suite on disk
    When I run "explain"
    Then the command succeeded
    And it mentions "scenarios"
    And it mentions "point at any of them"

  Scenario: explaining nothing lists what nothing asks for
    Given a suite on disk
    When I run "explain"
    Then it mentions "nothing asks for"

  Scenario: pointing at something that is not there names what was nearly meant
    Given a suite on disk
    When I run "explain standp --json"
    Then the command refused, saying "usage"
    And it mentions "Did you mean"
