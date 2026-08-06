Feature: the editor shows the same graph

  @edit
  Scenario: the catalogue lists what the suite declares
    Given the screen "catalogue"
    Then the heading "Catalogue" is showing
    And the words "Notebook" are showing
    And the words "Note" are showing
