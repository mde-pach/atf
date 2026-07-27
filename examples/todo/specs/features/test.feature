Feature: test

  Scenario: test
    Given the guest "visitor"
    When I list the owner's lists
    Then the result contains the guest "visitor"
