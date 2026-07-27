Feature: Lists
  A list belongs to exactly one owner, and carries the tasks created under it.

  Scenario: An owner reports their plan
    Given the owner "primary"
    Then the owner "primary" field "plan" is "standard"

  Scenario: A list belongs to its owner
    Given the owner "primary"
    And the todo_list "groceries"
    When I list the owner's lists
    Then the result contains the todo_list "groceries"

  Scenario: A list carries only open tasks
    Given the todo_list "groceries"
    And the task "milk"
    When I read the tasks on the list
    Then the tasks that came back are all open

  Scenario: Completing a task marks it done
    Given the task "laundry"
    When I complete the task
    Then the task "laundry" field "done" is "true"

  Scenario Outline: Owners report their own plan
    Given the owner "<who>"
    Then the owner "<who>" field "plan" is "<plan>"

    Examples:
      | who       | plan     |
      | primary   | standard |
      | secondary | trial    |
