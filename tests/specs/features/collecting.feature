Feature: Collecting a feature
  A `.feature` is normally handed to pytest by a module that calls `scenarios(…)`. For a feature
  that needs step code, that module is where the code lives. For one written entirely in the
  vocabulary ATF provides, it is a file whose whole content is an import and a call.

  So ATF collects a feature nobody bound. What such a feature can reach is pytest's fixture rule and
  nothing new — and these say it out loud rather than leaving anyone to find out.

  Rule: A feature needing no code needs no file beside it

    Scenario: A feature with no module of its own still runs
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                                                                        |
        | specs/features/lists.feature | Feature: Unbound\n\n  Scenario: It runs\n    Given the owner "primary"\n\n  Scenario: So does this one\n    Given the owner "primary"\n |
      When I run "atf run"
      Then the command succeeds
      And both its scenarios ran

    Scenario: Its scenarios are named the way a bound feature's are
      # The nodeid is what a run report, the cockpit and `-k` all key on, so a feature ATF collects
      # itself has to be indistinguishable from one somebody bound by hand.
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                          |
        | specs/features/lists.feature | Feature: Unbound\n\n  Scenario: A list belongs somewhere\n    Given the owner "primary"\n |
      When I run "atf run"
      Then the command succeeds
      And the run names it "test_a_list_belongs_somewhere"

    Scenario: A feature a module already binds is not collected a second time
      # Both would run every scenario, and the module is the one that can see its steps.
      Given the workspace "chained"
      When I run "atf run"
      Then the command succeeds
      And the scenario ran once, not twice

  Rule: What an unbound feature can reach is what a conftest declares, and no more

    Scenario: A phrase is reachable, because the plugin registers it everywhere
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                                     |
        | specs/phrasebook.yaml        | 'the owner is there':\n  - the owner "primary" exists\n                     |
        | specs/features/lists.feature | Feature: Unbound\n\n  Scenario: A phrase needs no module either\n    Given the owner "primary"\n    Then the owner is there\n |
      When I run "atf run"
      Then the command succeeds

    Scenario: A step only some other module declares is not
      Given the workspace "chained" but:
        | specs/steps/test_lists.py    | #absent                                                                    |
        | specs/features/lists.feature | Feature: Unbound\n\n  Scenario: It wants a When of its own\n    Given the owner "primary"\n    When I do something nobody defined\n |
      When I run "atf run"
      Then the run fails
      And the run says no step is worded that way
