Feature: a person's lists

  Phrase: I complete the task "{name}"
    When the task "{name}" done becomes true

  Phrase: I reopen the task "{name}"
    When the task "{name}" done becomes false

  Scenario: a list shows under its owner
    Given the todo_list "groceries"
    When I ask for the lists of "primary"
    Then the answer names "groceries"

  Scenario: the list is recognised the next time rather than made twice
    Given the todo_list "groceries"
    Then the todo_list "groceries" exists
    And the todo_list "groceries" slug is "groceries"
    And the todo_list "groceries" id is any whole number
    And the todo_list "groceries" slug is any slug

  Scenario: the owner comes along, because the field says needs()
    Given the todo_list "groceries"
    Then the owner "primary" exists
    And the owner "primary" email is "primary@example.com"

  Scenario: a row the API has no endpoint for is declared over the database
    Given the task "laundry"
    Then the task "laundry" exists
    And the task "laundry" done is false

  Scenario: a domain verb is a phrase over a field change, and its effect lasts
    Given the task "laundry"
    When I complete the task "laundry"
    Then the task "laundry" done is true
    When I reopen the task "laundry"
    Then the task "laundry" done is false

  Scenario: giving the resolver an argument bends one declared thing
    Given the todo_list "groceries" with slug "weekly"
    Then the todo_list "groceries" slug is "weekly"

  Scenario: a field nobody gave a value is filled by resolution
    Given the owner "anyone"
    Then the owner "anyone" email contains "generated-"

  Scenario: the environment can be counted
    Given the todo_list "groceries"
    Then there are 1 todo_lists
