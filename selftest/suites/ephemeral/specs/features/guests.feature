Feature: Guests
  A guest exists only for the run that needed it.

  Scenario: A guest is provisioned with an identity
    Given the guest "visitor"
    Then the guest has an identity
