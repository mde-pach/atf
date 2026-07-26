Feature: Lists
  Scenario: A list belongs to its owner
    Given the owner "primary"
    And the todo_list "groceries"
    Then the list belongs to a different owner
