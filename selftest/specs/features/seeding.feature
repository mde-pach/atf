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
      And nothing that depended on the label was attempted either

    Scenario: What did not depend on the failure is made anyway
      # The whole reason to keep going: one unmakeable resource must not decide the fate of a
      # resource that has nothing to do with it.
      Given the workspace "unmakeable"
      When the developer seeds everything it can rather than stopping at the first failure
      Then the run fails
      And the owner was still made

  Rule: A run leaves behind what the catalog calls persistent, and nothing it calls ephemeral

    Scenario: The guest a run built is gone afterwards, and what it hung off is not
      Given the workspace "ephemeral"
      When I run "atf seed local"
      And I run "atf run"
      Then the command succeeds
      And the guest it built is gone and the owner it needed is not

  Rule: A spec that names something the catalog does not is a failure a reader can act on

    Scenario: A misspelled resource type says which types there are
      Given the workspace "chained" but:
        | specs/features/lists.feature | Feature: Typos\n  Scenario: A typo\n    Given the acount "primary"\n |
      When I run "atf run"
      Then the run fails
      And the run says the catalog declares no such type

    Scenario: A precondition nobody has met names the resource that is missing
      # `mode: reference` is the one thing a spec cannot make for itself, so the failure has to say
      # which resource the environment was supposed to already have.
      Given the workspace "chained" but:
        | catalog/badges.yaml          | {imported: {resource: badge}}                                                            |
        | catalog/resources.yaml       | {owner: {system: rest, path: /owners, natural_key: email}, todo_list: {system: rest, path: /lists, natural_key: [owner_id, slug]}, badge: {system: rest, mode: reference, path: /guests, natural_key: nickname}} |
        | specs/features/lists.feature | Feature: Borrowed\n  Scenario: It must already be here\n    Given the badge "imported"\n |
      When I run "atf run"
      Then the run fails
      And the run names the resource nobody has provided

  Rule: Every row of an outline is its own scenario, with its own resources

    Scenario: Two rows provision two resources, not one twice
      Given the workspace "chained" but:
        | catalog/owners.yaml          | {primary: {resource: owner, body: {email: primary@selftest.example}}, second: {resource: owner, body: {email: second@selftest.example}}} |
        | specs/features/lists.feature | Feature: Rows\n\n  Scenario Outline: An owner is provisioned per row\n    Given the owner "<who>"\n\n    Examples:\n      \| who \|\n      \| primary \|\n      \| second \|\n |
      When I run "atf run"
      Then the command succeeds
      And both rows ran
      And the environment has 2 owner

  Rule: What is built for a run is torn down even when nothing named it directly

    Scenario: An ephemeral resource reached through a dependency is still taken away
      # Nothing else would ever delete it: an ephemeral resource is never looked up, so every pass
      # creates another one. Reaching it through a dependency is the case that is easy to miss.
      Given the workspace "ephemeral" but:
        | catalog/lists.yaml           | {groceries: {resource: todo_list, depends_on: [guests.visitor], body: {slug: groceries, owner_id: '@{guests.visitor.id}'}}} |
        | specs/features/guests.feature | Feature: Hanging off\n\n  Scenario: A list under a guest\n    Given the todo_list "groceries"\n |
      When I run "atf run"
      Then the command succeeds
      And the badge it hung off survives
