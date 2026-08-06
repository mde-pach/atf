Feature: two of a kind, arranged by a scenario

  Scenario: two owners are arranged and a step asks for the owner
    Given the owner "primary"
    And the owner "secondary"
    Then the owner in scope is "primary@example.com"
