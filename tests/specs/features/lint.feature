Feature: Keeping the layers apart
  A spec is what a product owner or a tester reads. The moment a field name, a selector, a status
  code, a path or a CLI flag appears in one, the layer below has leaked into it — and the reader now
  needs to know the shape of a record to understand what the test claims.

  That is the one rule of the model that can be checked by machine, so it ships as a check rather
  than as advice. Every scenario below writes a `.feature` into a suite and runs `atf lint` over it.

  Rule: Technical vocabulary in a spec line is reported

    Scenario: Naming a field of a record
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Then the task "milk" field "done" is "false"\n |
      When I run "atf lint"
      Then it objects, naming the rule "field-claim"
      And it says how to answer the objection

    Scenario: Quoting a status code
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Then the page "overview" is "200"\n |
      When I run "atf lint"
      Then it objects, naming the rule "status-code"

    Scenario: Naming a route into a system
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    When I call "/tasks"\n |
      When I run "atf lint"
      Then it objects, naming the rule "path"

    Scenario: Spelling a command-line flag
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    When I run "atf run --json"\n |
      When I run "atf lint"
      Then it objects, naming the rule "cli-flag"

    Scenario: Writing a selector
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Then the element "#compose-form li[role=option]" exists\n |
      When I run "atf lint"
      Then it objects, naming the rule "selector"

    Scenario: One line saying two technical things is reported for both
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Then the page "overview" field "status" is "200"\n |
      When I run "atf lint"
      Then it objects, naming the rule "field-claim"
      And it objects, naming the rule "status-code"

  Rule: What a reader is allowed to be specific about is left alone

    Scenario: The narrative explains, and explaining may be specific
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: Seeding\n  It POSTs to /tasks and expects a 201, and `--keep-going` carries on.\n\n  Scenario: S\n    Then the owner "primary" exists\n |
      When I run "atf lint"
      Then the specs say nothing only the layer below should know

    Scenario: A table is data, and says what a whole record must be
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Then the task "milk" is:\n      \| title \| Buy milk \|\n |
      When I run "atf lint"
      Then the specs say nothing only the layer below should know

    Scenario: The claims that already read as domain language
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    Given the workspace "chained"\n    Then the owner "primary" exists\n    And the environment has 1 owner\n |
      When I run "atf lint"
      Then the specs say nothing only the layer below should know

  Rule: A rule can be waived by name, above the line it excuses

    Scenario: A waiver above a line excuses that line
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    # atf-lint: ignore field-claim\n    Then the task "milk" field "done" is "false"\n |
      When I run "atf lint"
      Then the specs say nothing only the layer below should know

    Scenario: And no further than that line
      Given the workspace "bare" but:
        | specs/features/a.feature | Feature: F\n  Scenario: S\n    # atf-lint: ignore field-claim\n    Then the task "milk" field "done" is "false"\n    And the task "bread" field "done" is "true"\n |
      When I run "atf lint"
      Then it objects, naming the rule "field-claim"

    Scenario: A waiver before the feature excuses the whole file
      Given the workspace "bare" but:
        | specs/features/a.feature | # atf-lint: ignore field-claim\nFeature: F\n  Scenario: S\n    Then the task "milk" field "done" is "false"\n    And the task "bread" field "done" is "true"\n |
      When I run "atf lint"
      Then the specs say nothing only the layer below should know

    Scenario: A waiver excuses the rules it names and no others
      Given the workspace "bare" but:
        | specs/features/a.feature | # atf-lint: ignore field-claim\nFeature: F\n  Scenario: S\n    Then the page "overview" field "status" is "200"\n |
      When I run "atf lint"
      Then it objects, naming the rule "status-code"

    Scenario: A waiver naming nothing ATF knows excuses everything rather than nothing
      # Better obviously too broad than looking like a waiver and doing nothing at all.
      Given the workspace "bare" but:
        | specs/features/a.feature | # atf-lint: ignore whatever-that-is\nFeature: F\n  Scenario: S\n    Then the task "milk" field "done" is "false"\n |
      When I run "atf lint"
      Then the specs say nothing only the layer below should know
