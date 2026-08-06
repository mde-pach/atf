Feature: showing a person's lists

  Scenario: a list shows under its owner
    Given the todo_list "groceries"
    When I run "show primary@example.com"
    Then the result field "exit_code" is "0"
    And the result field "output" contains "groceries"

  Scenario: the list is recognised rather than made twice
    Given the todo_list "groceries"
    Then the todo_list "groceries" exists
    And the todo_list "groceries" field "slug" is "groceries"
    And the todo_list "groceries" field "id" is #int

  Scenario: a report needs an owner it has no field for
    Given the report "quarterly"
    Then the report "quarterly" exists
    And the owner "primary" exists

  Scenario: a variation changes one field for the length of one scenario
    Given the todo_list "groceries" but "slug" is "weekly"
    Then the todo_list "groceries" field "slug" is "weekly"

  Scenario: a continuation names one more field, and null removes it
    Given the todo_list "groceries" but "slug" is "solo"
    And "owner" is "null"
    Then the todo_list "groceries" field "slug" is "solo"
    And the todo_list "groceries" field "owner_id" is ""

  Scenario: a step this suite wrote reads the owner the scenario arranged
    Given the todo_list "groceries"
    When I list the owner's lists
    Then the listing names "groceries"

  Scenario: a function-scoped resource is made for this test and taken away after
    Given the guest "visitor"
    Then the guest "visitor" exists

  Scenario: a session-scoped resource lasts the run and no longer
    Given the tenant "acme"
    Then the tenant "acme" exists

  Scenario: two resources differ only in the second half of their key
    Given the tenant "acme"
    And the tenant "acme_us"
    Then the tenant "acme" field "region" is "eu"
    And the tenant "acme_us" field "region" is "us"

  Scenario: a domain verb is performed by the adapter
    Given the task "laundry"
    Then the task "laundry" field "done" is "0"
    When I complete the task "laundry"
    Then the task "laundry" field "done" is "1"

  Scenario: the environment can be counted
    Given the report "quarterly"
    Then the environment has 1 report

  @phrase
  Scenario: the output names "{words}"
    Then the result field "exit_code" is "0"
    And the result field "output" contains "{words}"

  Scenario: a phrase stands for the sentences under it
    Given the todo_list "groceries"
    When I run "show primary@example.com"
    Then the output names "groceries"

  Scenario Outline: every declared list shows under its owner
    Given the todo_list "<list>"
    When I run "show primary@example.com"
    Then the output names "<list>"

    Examples:
      | list      |
      | groceries |
