Feature: Lists
  A list belongs to the owner it was created under.

  Scenario: A list belongs to its owner
    Given the owner "primary"
    And the todo_list "groceries"
    Then the list belongs to the owner
