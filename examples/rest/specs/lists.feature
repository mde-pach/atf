Feature: an API owns the resources

  Scenario: a list is made under its owner, and recognised the next time
    Given the todo_list "groceries"
    Then the todo_list "groceries" exists
    And the todo_list "groceries" field "slug" is "groceries"
    And the todo_list "groceries" field "id" is #int

  Scenario: the owner comes along, because depends_on says so
    Given the todo_list "groceries"
    Then the owner "primary" exists
    And the owner "primary" field "email" is "primary@example.com"

  Scenario: the environment can be counted
    Given the owner "primary"
    Then the environment has 1 owner
