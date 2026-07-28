Feature: What a claim says when it does not hold
  A claim is worth what its failure message is worth. A reader who has never opened the framework
  has to be able to act on it: which resource, which field, what was there instead, and what the
  catalog does offer.

  Every scenario below writes a spec that makes a false claim, runs it, and reads the sentence back.

  Rule: A claim about a resource says which resource, and what was found

    Scenario: Requiring something the environment does not have
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                             |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: It is not there\n    Then the owner "primary" exists\n |
      When I run "atf run"
      Then the run fails
      And it says nothing in the environment matches

    Scenario: Requiring something the environment still has
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                                     |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: It is still there\n    Given the owner "primary"\n    Then the owner "primary" is gone\n |
      When I run "atf run"
      Then the run fails
      And it says the resource is still there

    Scenario: Comparing a field with the wrong value
      Given the workspace "chained" but:
        | catalog/owners.yaml          | primary:\n  resource: owner\n  represents: An owner on a plan.\n  body:\n    email: primary@atf.test\n    plan: standard\n |
        | specs/steps/test_lists.py    | #absent                                                                     |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: The wrong value\n    Given the owner "primary"\n    Then the owner "primary" field "plan" is "enterprise"\n |
      When I run "atf run"
      Then the run fails
      And it says what the field holds instead

    Scenario: Naming a field the record does not carry
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                                     |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: No such field\n    Given the owner "primary"\n    Then the owner "primary" field "tier" is "gold"\n |
      When I run "atf run"
      Then the run fails
      And it lists the fields the record does carry

  Rule: A claim about something the catalog never declared says what it does declare

    Scenario: A misspelled resource type
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                     |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: A typo\n    Then the acount "primary" exists\n |
      When I run "atf run"
      Then the run fails
      And it lists the types the catalog does declare

    Scenario: A misspelled instance name
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                      |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: A typo\n    Then the owner "primry" exists\n |
      When I run "atf run"
      Then the run fails
      And it lists the instances of that type

  Rule: A claim ATF cannot decide refuses rather than answering wrongly

    Scenario: Asking whether an ephemeral resource is gone
      # It is never looked up — that is what ephemeral means — so "is it gone" has no answer, and
      # passing vacuously would be worse than refusing.
      Given the workspace "ephemeral" but:
        | specs/steps/test_guests.py    | #absent                                                          |
        | specs/features/guests.feature | Feature: Claims\n\n  Scenario: No answer to give\n    Given the guest "visitor"\n    Then the guest "visitor" is gone\n |
      When I run "atf run"
      Then the run fails
      And it says an ephemeral resource is never looked up

  Rule: A claim about a slot says what the scenario is actually holding

    Scenario: Naming a slot nothing put there
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                                    |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: A mistyped slot\n    Given the owner "primary"\n    Then the reslt field "x" is "1"\n |
      When I run "atf run"
      Then the run fails
      And it says what the scenario is holding instead

  Rule: A whole-shape claim reports every field that disagrees, not the first

    Scenario: Two fields wrong at once
      Given the workspace "chained" but:
        | catalog/owners.yaml          | primary:\n  resource: owner\n  represents: An owner on a plan.\n  body:\n    email: primary@atf.test\n    plan: standard\n |
        | specs/steps/test_lists.py    | #absent                                                                    |
        | specs/features/lists.feature | Feature: Claims\n\n  Scenario: Both wrong\n    Given the owner "primary"\n    Then the owner "primary" is:\n      \| plan  \| enterprise \|\n      \| email \| someone@else.test \|\n |
      When I run "atf run"
      Then the run fails
      And it lists every field that disagrees
