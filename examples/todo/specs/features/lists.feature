Feature: Lists
  A list belongs to exactly one owner, and carries the tasks created under it.

  Scenario: An owner reports their plan
    Given the owner "primary"
    Then the plan is "standard"

  Scenario: A list belongs to its owner
    Given the owner "primary"
    And the todo_list "groceries"
    When I list the owner's lists
    Then the list "groceries" is among them

  Scenario: A task lands on its list
    Given the todo_list "groceries"
    And the task "milk"
    When I read the tasks on the list
    Then the task "Buy milk" is open

  Scenario: Completing a task marks it done
    Given the task "laundry"
    When I complete the task
    Then the task is done

  Scenario Outline: Owners report their own plan
    Given the owner "<who>"
    Then the plan is "<plan>"

    Examples:
      | who       | plan     |
      | primary   | standard |
      | secondary | trial    |
