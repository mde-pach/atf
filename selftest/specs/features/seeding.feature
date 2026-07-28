Feature: Seeding
  Making a catalog real, and what happens when part of it cannot be made real.

  Rule: A developer can ask for part of a catalog rather than all of it

    Scenario: Asking for a type nothing declares lists the ones that are declared
      Given the workspace "chained"
      When the developer seeds only the ghost "nowhere"
      Then it is refused because "unknown resource type 'ghost'"
      And the refusal also mentions "owner"

    Scenario: Naming an instance without saying what kind it is is refused
      Given the workspace "chained"
      When the developer seeds an instance without saying its type
      Then it is refused for not saying what kind of thing that is

  Rule: A failure stops the pass, unless the developer asks to see all of them

    Scenario: Seeding stops at the first thing it could not make, and says how to see the rest
      Given the workspace "unmakeable"
      When I run "atf seed local"
      Then the run fails
      And it stopped at the first failure
      And it says how to attempt the rest

    Scenario: Asked to keep going, it reports every independent failure at once
      Given the workspace "unmakeable"
      When the developer seeds everything it can rather than stopping at the first failure
      Then the run fails
      And the borrowed badge could not be found
      And it did not stop at the first failure

    Scenario: What depended on a failure is reported as never attempted, not as failed
      Given the workspace "unmakeable"
      When the developer seeds everything it can rather than stopping at the first failure
      Then the run fails
      And the label was skipped because of the badge
