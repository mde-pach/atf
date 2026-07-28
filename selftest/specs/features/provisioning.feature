# atf-lint: ignore field-claim
# A waypoint, deliberately: every claim below is one ATF makes for any suite, which was the point
# of getting here — but `the result field "exit_code" is "0"` is still a struct field access spelled
# in English. `safety.feature` is the same suite one step further on, with a phrasebook behind it.
# This feature is left as it is so the two can be read side by side.
Feature: Provisioning
  A resource declared in a catalog is made to exist, dependencies first, exactly once.

  What a suite-under-test leaves in the backend is declared in this suite's own catalog, so every
  claim below is one ATF makes for any suite. Nothing in `steps/` asserts anything: the only Python
  this feature needs is the one step that runs a command, because running a command is the kind of
  thing a framework has no generic way to do.

  The `Rule:` lines below are the rules a discovery workshop would have written on the middle row
  of cards, and each scenario under one is an example of it.

  Rule: What is declared is made to exist, dependencies first

    Scenario: Seeding creates a dependency chain in order
      Given the workspace "chained"
      When I run "atf seed local"
      Then the result field "exit_code" is "0"
      And the owner "primary" exists
      And the todo_list "groceries" field "owner_id" is "${owners.primary.id}"

    Scenario: A spec provisions what it declares, without seeding first
      Given the workspace "chained"
      When I run "atf run"
      Then the result field "exit_code" is "0"
      And the result field "output" contains "1 passed"
      And the environment has 1 owner
      And the environment has 1 todo_list

  Rule: Making something exist twice makes it once

    Scenario: Seeding twice creates nothing the second time
      Given the workspace "chained"
      When I run "atf seed local"
      And I run "atf seed local"
      Then the result field "exit_code" is "0"
      And the result field "output" contains "exists"
      And the environment has 1 owner
      And the environment has 1 todo_list

    Scenario: Status reports absent before seeding and present after
      Given the workspace "chained"
      When I run "atf status local"
      Then the result field "exit_code" is "0"
      And the result field "output" contains "absent"
      And the owner "primary" is gone
      When I run "atf seed local"
      And I run "atf status local"
      Then the result field "output" contains "present"
      And the result field "output" does not contain "absent"
      And the owner "primary" exists

  Rule: What is built for a run does not outlive it

    Scenario: An ephemeral resource is built for the run and torn down afterwards
      Given the workspace "ephemeral"
      When I run "atf run"
      Then the result field "exit_code" is "0"
      And the result field "output" contains "1 passed"
      And the guest "visitor" is gone
