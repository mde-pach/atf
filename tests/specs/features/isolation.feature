Feature: Having one to yourself
  A scenario can ask for its own instance of a resource the catalog shares.

  Shared-or-isolated is normally a choice a whole suite makes once. ATF gives every node its own
  lifecycle, so the expensive scaffolding can be seeded once and shared while the volatile parts are
  built per scenario — and this is the line that lets one scenario take the other side of that
  choice for a node, without the catalog changing and without any other scenario noticing.

  Every scenario below writes a real suite to disk, runs the real command against it, and then looks
  in the backend at what is left.

  Rule: What a scenario had to itself goes when the scenario does

    Scenario: The instance it made is taken away, and what it hung off is not
      Given the workspace "chained" but:
        | specs/features/lists.feature | Feature: Mine\n\n  Scenario: A list of my own\n    Given a fresh todo_list "groceries"\n    Then the todo_list "groceries" exists\n |
      When I run "atf run"
      Then the command succeeds
      And the list it made is gone and the owner it hung off is not

    Scenario: The shared resource is left exactly as seeding made it
      # The promise that makes this usable at all: a scenario having its own must be invisible to
      # every scenario that just says `Given the todo_list "groceries"`.
      Given the workspace "chained" but:
        | specs/features/lists.feature | Feature: Mine\n\n  Scenario: A list of my own\n    Given a fresh todo_list "groceries"\n    Then the todo_list "groceries" exists\n |
      When I run "atf seed local"
      And I run "atf run"
      Then the command succeeds
      And the shared list is the only one left

    Scenario: Two of them at once are two different resources
      # Said from inside the suite under test, because it is the only place that can see both of
      # them alive at the same time. If a copy did not get a name of its own, this counts one.
      Given the workspace "chained" but:
        | specs/features/lists.feature | Feature: Mine\n\n  Scenario: Two of my own at once\n    Given a fresh todo_list "groceries"\n    And a fresh todo_list "groceries"\n    Then the environment has 2 todo_list\n |
      When I run "atf run"
      Then the command succeeds
      And the list it made is gone and the owner it hung off is not

  Rule: A scenario that says what makes its copy different is taken at its word

    Scenario: An instance named by the scenario rather than by ATF
      # Appending to a written key is how ATF tells two apart on its own, and there are keys that
      # will not survive being appended to. Saying the key is the answer, and it is the same table
      # any other resource is varied with.
      Given the workspace "chained" but:
        | specs/features/lists.feature | Feature: Mine\n\n  Scenario: An owner of my own, named by me\n    Given a fresh owner "primary" but:\n      \| email \| mine@atf.test \|\n    Then the owner "primary" field "email" is "mine@atf.test"\n |
      When I run "atf seed local"
      And I run "atf run"
      Then the command succeeds
      And the owner it made is gone and the seeded one is not

  Rule: Where there can be no copy, the refusal says what to do instead

    Scenario: A resource that is already built per scenario
      Given the workspace "ephemeral" but:
        | specs/features/guests.feature | Feature: Mine\n\n  Scenario: A guest is one already\n    Given a fresh guest "visitor"\n |
      When I run "atf run"
      Then the run fails
      And it says this one is built for each run already
      And it says to ask for it the ordinary way

    Scenario: A resource ATF is not the one that makes
      Given the workspace "chained" but:
        | catalog/badges.yaml          | {imported: {resource: badge}}                                                            |
        | catalog/resources.yaml       | {owner: {system: rest, path: /owners, natural_key: email}, todo_list: {system: rest, path: /lists, natural_key: [owner_id, slug]}, badge: {system: rest, mode: reference, path: /guests, natural_key: nickname}} |
        | specs/features/lists.feature | Feature: Mine\n\n  Scenario: A badge of my own\n    Given a fresh badge "imported"\n |
      When I run "atf run"
      Then the run fails
      And it says this one is never made here
      And it says to ask for it the ordinary way

    Scenario: A resource nothing would tell the copy from
      # Every field this type is known by is the link to its parent, so a copy would carry the same
      # one and the two would be the same resource as far as anything can tell.
      Given the workspace "chained" but:
        | catalog/resources.yaml       | {owner: {system: rest, path: /owners, natural_key: email}, todo_list: {system: rest, path: /lists, natural_key: owner_id}} |
        | specs/features/lists.feature | Feature: Mine\n\n  Scenario: A list of my own\n    Given a fresh todo_list "groceries"\n |
      When I run "atf run"
      Then the run fails
      And it says nothing would tell the copy from the shared one
      And it says how to say what makes the copy different
