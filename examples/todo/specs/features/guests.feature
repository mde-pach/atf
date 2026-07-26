Feature: Guests and labels
  A guest is built fresh for each run and torn down afterwards; a label must already exist.

  Scenario: A guest is ready as soon as it is provisioned
    Given the guest "visitor"
    When I read the guest
    Then the guest is ready

  Scenario: The environment's label is available
    Given the label "urgent"
    Then the label "urgent" is found
