Feature: Lists
  A list belongs to exactly one owner, and carries the tasks created under it.

  Scenario: An owner reports their plan
    Given the owner "primary"
    Then the owner "primary" is on the "standard" plan

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
    Then the task "laundry" is done

  Scenario: An overdue task is still an ordinary task
    # One catalog node, varied where the variation matters. The alternative is a second `task`
    # entry per due date anyone ever wants to test — a global set of named factories, which is the
    # Object Mother pattern and the reason catalogs sprawl.
    Given the task "milk" but:
      | due_at | ${now-1d 09:00} |
    Then the task "milk" is:
      | title  | Buy milk  |
      | done   | false     |
      | uuid   | #notnull  |
      | due_at | #notnull  |

  Scenario Outline: Owners report their own plan
    Given the owner "<who>"
    Then the owner "<who>" is on the "<plan>" plan

    Examples:
      | who       | plan     |
      | primary   | standard |
      | secondary | trial    |
