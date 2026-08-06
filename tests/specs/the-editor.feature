Feature: the editor shows the same graph

  @edit
  Scenario: the catalogue lists what the suite declares
    Given the screen "catalogue"
    Then the heading "Catalogue" is showing
    And the words "Notebook" are showing
    And the words "Note" are showing

  @edit
  Scenario: the overview folds the two vocabularies and nothing else
    Given the screen "catalogue"
    When I read "/api/overview" from the editor
    Then the answer contains "absent"
    And the answer contains "sentence"

  @edit
  Scenario: the catalogue is what the suite declares, read from the same core
    Given the screen "catalogue"
    When I read "/api/catalogue" from the editor
    Then the answer contains "Notebook"
    And the answer contains "filesystem"

  @edit
  Scenario: opening a resource shows what would be sent to create it
    Given the screen "catalogue"
    When I read "/api/resource/standup" from the editor
    Then the answer contains "would_create"
    And the answer contains "recognised_by"
    And the answer contains "notebooks/work/standup.md"

  @edit
  Scenario: a resource the environment owns says why it cannot be made
    Given the screen "catalogue"
    When I read "/api/resource/archived" from the editor
    Then the answer contains "require"

  @edit
  Scenario: the tools an agent is offered are the operations the command has
    Given the screen "catalogue"
    When I read "/api/tools" from the editor
    Then the answer contains "impact"
    And the answer contains "unused"
    And the answer contains "make"
