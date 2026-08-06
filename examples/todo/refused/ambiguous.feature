Feature: two of a kind

  Scenario: two owners are arranged and a step asks for the owner
    Given the owner "primary"
    And the owner "secondary"
    When I list the owner's lists
    Then the listing names "groceries"
