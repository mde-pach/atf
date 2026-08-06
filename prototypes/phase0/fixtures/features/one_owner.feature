Feature: asking for one, inside a scenario

  Scenario: one owner in scope
    Given the owner "primary"
    Then the owner in scope is "primary@example.com"

  Scenario: a different owner in scope
    Given the owner "secondary"
    Then the owner in scope is "secondary@example.com"
