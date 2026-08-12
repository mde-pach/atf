Feature: showing a person's lists

  Phrase: I complete the task "{name}"
    When the task "{name}" done becomes true

  Phrase: I reopen the task "{name}"
    When the task "{name}" done becomes false

  Phrase: the output names "{words}"
    Then its exit code is 0
    And it mentions "{words}"

  Phrase: showing "{slug}" under its owner
    Given the todo_list "{slug}"
    When I run "show primary@example.com"
    Then it mentions "{slug}"

  Scenario: a list shows under its owner
    Given the todo_list "groceries"
    When I run "show primary@example.com"
    Then its exit code is 0
    And it mentions "groceries"

  Scenario: the list is recognised rather than made twice
    Given the todo_list "groceries"
    Then the todo_list "groceries" exists
    And the todo_list "groceries" slug is "groceries"
    And the todo_list "groceries" id is any whole number

  Scenario: a report needs an owner, and says so at the field
    Given the report "quarterly"
    Then the report "quarterly" exists
    And the owner "primary" exists

  Scenario: giving the resolver an argument bends one declared thing
    Given the todo_list "groceries" with slug "weekly"
    Then the todo_list "groceries" slug is "weekly"

  Scenario: a continuation names one more field, and without removes it
    Given the todo_list "groceries" with slug "solo"
    And without the owner
    Then the todo_list "groceries" slug is "solo"
    And the todo_list "groceries" owner_id is nothing

  Scenario: a step this suite wrote reads the owner the scenario arranged
    Given the todo_list "groceries"
    When I list the owner's lists
    Then the listing names "groceries"

  Scenario: something a scenario changes is made for the test and taken away after
    Given the guest "visitor"
    Then the guest "visitor" exists

  Scenario: two things differ only in the second half of their key
    Given the tenant "acme"
    And the tenant "acme_us"
    Then the tenant "acme" region is "eu"
    And the tenant "acme_us" region is "us"

  Scenario: a domain verb is a phrase over a field change, and its effect lasts
    Given the task "laundry"
    When I complete the task "laundry"
    Then the task "laundry" done is true
    When I reopen the task "laundry"
    Then the task "laundry" done is false

  Scenario: the environment can be counted
    Given the report "quarterly"
    Then there are 1 reports

  Scenario: a phrase stands for the sentences under it
    Given the todo_list "groceries"
    When I run "show primary@example.com"
    Then the output names "groceries"

  Scenario: a phrase runs one shape over several inputs
    Given showing "groceries" under its owner

  Scenario: a field nobody gave a value is filled by resolution
    Given the owner "anyone"
    Then the owner "anyone" email contains "generated-"
