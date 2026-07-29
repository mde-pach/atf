Feature: Feature files that are what they claim to be
  `atf lint` reads the `.feature` files and answers one question: is this file well formed? Not
  whether its words are the right words — that is a judgement about a domain, and a machine that
  makes it produces false positives on correct specs and a check that means nothing.

  Everything below is a fact about a file that is wrong in every domain, and each is something a
  run would otherwise do quietly: a step nothing will execute, an outline that runs zero times, a
  row that loses its last value, two scenarios that become one test.

  Every scenario writes a `.feature` into a suite and runs `atf lint` over it.

  Rule: A file that is not a feature is not silently collected

    Scenario: A feature file with no Feature in it
      Given the workspace "bare" but:
        | specs/features/a.feature | Scenario: S\n  Given the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "no-feature"

    Scenario: Two features in one file, where everything after the first is ignored
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: One\n  Scenario: S\n    Given the owner "primary"\nFeature: Two\n  Scenario: T\n    Given the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "two-features"

    Scenario: A keyword with nothing after the colon
      # The title is what the cockpit lists, what a run reports, and what a person searches for.
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario:\n    Given the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "untitled"

  Rule: A step nothing will run is reported rather than left to be noticed

    Scenario: A step above every scenario
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Given the owner "primary"\n\n  Scenario: S\n    Given the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "stray-step"

    Scenario: An And with nothing above it to continue
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    And the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "dangling-and"

    Scenario: A scenario with no steps at all, which passes without claiming anything
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n\n  Scenario: T\n    Given the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "empty-scenario"

  Rule: An outline that cannot run, or runs with a hole in it, is reported

    Scenario: An outline with no rows to run
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario Outline: S\n    Given the owner "<who>"\n |
      When I run "atf lint"
      Then it objects, naming the rule "outline-without-examples"

    Scenario: A placeholder no column supplies
      # It reaches the step with its angle brackets still on, and the failure names a resource
      # called `<who>` — which is a long way from the typo that caused it.
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario Outline: S\n    Given the owner "<who>"\n\n    Examples:\n      \| name \|\n      \| primary \|\n |
      When I run "atf lint"
      Then it objects, naming the rule "unknown-placeholder"

    Scenario: A row with the wrong number of cells
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Given the owner "primary" but:\n      \| email \| a@b.test \|\n      \| plan \|\n |
      When I run "atf lint"
      Then it objects, naming the rule "ragged-table"

  Rule: Two scenarios that become one test are reported

    Scenario: The same title twice in one feature
      # pytest generates the test name from the title, so the second silently replaces the first.
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: The same name\n    Given the owner "primary"\n\n  Scenario: The same name\n    Given the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "duplicate-scenario"

  Rule: What it does not check is as important as what it does

    Scenario: A spec may say whatever its domain says
      # The words in a spec are a judgement about a domain, and the linter has no opinion. A path,
      # a status code and a flag are all somebody's domain values.
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    When I follow "/products/42"\n    Then the check "api" reports "503"\n    And it was run with "--keep-going"\n |
      When I run "atf lint"
      Then the specs are well formed

    Scenario: A cell may hold a pipe, because Gherkin lets it
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Given the owner "primary" but:\n      \| note \| one \\\| two \|\n |
      When I run "atf lint"
      Then the specs are well formed

    Scenario: A suite that is well formed says so rather than saying nothing
      Given the workspace "chained"
      When I run "atf lint"
      Then the specs are well formed

  Rule: Every problem in the file, not the first

    Scenario: Two things wrong are two findings
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario:\n    And the owner "primary"\n |
      When I run "atf lint"
      Then it objects, naming the rule "untitled"
      And the refusal also mentions "dangling-and"
