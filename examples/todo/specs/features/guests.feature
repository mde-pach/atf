Feature: Guests and labels
  A guest is built fresh for each run and torn down afterwards; a label must already exist.

  Scenario: A guest is ready as soon as it is provisioned
    Given the guest "visitor"
    Then the guest "visitor" is ready

  Scenario: The environment's label is available
    Given the label "urgent"
    Then the label "urgent" exists
    And the label "urgent" is called "Urgent"
