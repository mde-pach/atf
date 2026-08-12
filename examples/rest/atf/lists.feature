Feature: an API owns the things

  Scenario: a list is made under its owner, and recognised the next time
    Given the todo_list "groceries"
    Then the todo_list "groceries" exists
    And the todo_list "groceries" slug is "groceries"
    And the todo_list "groceries" id is any whole number

  Scenario: the owner comes along, because the field says needs()
    Given the todo_list "groceries"
    Then the owner "primary" exists
    And the owner "primary" email is "primary@example.com"

  Scenario: the environment can be counted
    Given the owner "primary"
    Then there are 1 owners
