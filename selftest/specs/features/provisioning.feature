Feature: Provisioning
  A resource declared in a catalog is made to exist, dependencies first, exactly once.

  Scenario: Seeding creates a dependency chain in order
    Given the workspace "chained"
    When I run "atf seed local"
    Then it exits 0
    And the backend has 1 owners
    And the backend has 1 lists
    And the list points at the owner

  Scenario: Seeding twice creates nothing the second time
    Given the workspace "chained"
    When I run "atf seed local"
    And I run "atf seed local"
    Then it exits 0
    And the output mentions "exists"
    And the backend has 1 owners
    And the backend has 1 lists

  Scenario: A spec provisions what it declares, without seeding first
    Given the workspace "chained"
    When I run "atf run"
    Then it exits 0
    And the output mentions "1 passed"
    And the backend has 1 owners
    And the backend has 1 lists

  Scenario: Status reports absent before seeding and present after
    Given the workspace "chained"
    When I run "atf status local"
    Then it exits 0
    And the output mentions "absent"
    When I run "atf seed local"
    And I run "atf status local"
    Then the output mentions "present"
    And the output does not mention "absent"

  Scenario: An ephemeral resource is built for the run and torn down afterwards
    Given the workspace "ephemeral"
    When I run "atf run"
    Then it exits 0
    And the output mentions "1 passed"
    And the backend has 0 guests
