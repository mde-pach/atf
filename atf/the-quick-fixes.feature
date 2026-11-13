Feature: what a gutter action knows before it is invoked

  A hover fact, a second look, and the one action that writes for real — each reached the way a
  scenario reaches anything else the editor answers: through its own JSON, read back and claimed
  on, the same core `atf plan` and the command already read.

  Scenario: hovering a step's own words says which file answers it
    Given the screen "listing"
    When I ask the editor what "Given the note \"standup\"" means
    Then it mentions "vocabulary.py"
    And it mentions "the {kind} \"{name}\""

  Scenario: hovering a phrase call says it is a phrase this suite teaches, not a step
    Given the screen "listing"
    When I ask the editor what "Given a busy notebook" means
    Then it mentions "a phrase this suite teaches"

  Scenario: a sentence nothing answers means nothing, not a guess
    Given the screen "listing"
    When I ask the editor what "Given it does the thing" means
    Then it does not mention "pattern"

  Scenario: a scenario that arranges and acts exactly like an existing one is named, not blocked
    Given the screen "listing"
    When I ask the editor for advisories on "Feature: draft\n\n  Scenario: a lineage read back the same way\n    Given the note \"standup\"\n    When I open the note \"standup\"\n    Then its path is \"notebooks/work/standup.md\"\n"
    Then it mentions "this looks like one that already exists"
    And it mentions "what an act produced is read back as `it`"

  Scenario: a run of raw steps that already says a phrase is offered its rewrite, values and all
    Given the screen "listing"
    When I ask the editor for advisories on "Feature: draft\n\n  Scenario: a busy notebook, spelled out longhand\n    Given the notebook \"work\"\n    And the note \"standup\"\n    And the note \"retro\"\n    Then the note \"retro\" exists\n"
    Then it mentions "that's already a phrase you have"
    And it mentions "Given a busy notebook"

  Scenario: the draft-claim quick fix writes a real claim, the same way --accept does
    Given the screen "listing"
    When somebody changes "atf/promiseless.feature" to "Feature: draft\n\n  Scenario: opening a note says what is in it\n    Given the note \"standup\"\n    When I open the note \"standup\"\n"
    And I ask the editor to draft the claim for "atf/promiseless.feature::opening a note says what is in it"
    Then it mentions "drafted"
