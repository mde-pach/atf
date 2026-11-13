Feature: the Tests page offers what actually fits

  The same offers the composer answers with, narrowed to what is reachable from what is already
  written, and a blank's own example read from a value the suite actually declared — never one
  invented for the occasion.

  Scenario: typing part of a resource's name rules out the ones that do not share it
    Given the screen "new_test_screen"
    When I type "Scenario: x\n    Given the wor" into the textbox "scenario text"
    And I wait for the editor to catch up
    Then the words "the notebook \"work\"" are showing
    And the words "the archive \"archived\"" are not showing

  Scenario: finishing a resource's whole name does surface it
    Given the screen "new_test_screen"
    When I type "Scenario: x\n    Given the work" into the textbox "scenario text"
    And I wait for the editor to catch up
    Then the words "the notebook \"work\"" are showing

  Scenario: once something is arranged, the offered vocabulary narrows to claims about it
    Given the screen "new_test_screen"
    When I type "Scenario: x\n    Given the note \"standup\"\n    Then the note \"standup\" e" into the textbox "scenario text"
    And I wait for the editor to catch up
    Then the words "the note \"standup\" exists" are showing

  Scenario: an offered blank shows a real declared value, never an invented one
    Given the screen "new_test_screen"
    When I type "Scenario: x\n    Given the note \"standup\"\n    Then the note \"standup\" tex" into the textbox "scenario text"
    And I wait for the editor to catch up
    Then the words "stand up" are showing

  Scenario: an "And" carries its keyword's own arrangement into what completion offers
    Given the screen "new_test_screen"
    When I type "Scenario: x\n    Given the notebook \"work\"\n    And the note \"standup\"\n    Then " into the textbox "scenario text"
    And I wait for the editor to catch up
    Then the words "the note \"standup\" exists" are showing

  Scenario: an earlier scenario in the same file does not leak into this one's completions
    Given the screen "new_test_screen"
    When I type "Feature: x\n\n  Scenario: first\n    Given the card \"todo\"\n    When the card \"todo\" text becomes \"halfway\"\n    Then the card \"todo\" text is \"halfway\"\n\n  Scenario: second\n    Given " into the textbox "scenario text"
    And I wait for the editor to catch up
    Then the words "the draft \"scratch\"" are showing
