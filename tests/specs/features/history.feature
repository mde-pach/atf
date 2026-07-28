Feature: What a run leaves behind
  A verdict that only exists in a terminal is a verdict nobody can act on tomorrow. Every run is
  written under `.atf/runs/`, so the cockpit can say what happened last time and whether a scenario
  has been flipping — and so a run that happened in CI can be brought back to the machine that
  needs to know about it.

  Rule: A report from elsewhere becomes a run like any other

    Scenario: A CI report is read and kept
      Given the workspace "chained" but:
        | ci.json | {"tests": [{"nodeid": "specs/steps/test_lists.py::test_one", "outcome": "passed", "duration": 0.1}, {"nodeid": "specs/steps/test_lists.py::test_two", "outcome": "failed", "duration": 0.2}]} |
      When I run "atf import-run local ci.json"
      Then the command succeeds
      And it reports what CI saw
      And it keeps the run where the cockpit will find it

    Scenario: Something that is not a report is refused
      Given the workspace "chained" but:
        | ci.json | {"nothing": "useful"} |
      When I run "atf import-run local ci.json"
      Then it refuses what is not a report

    Scenario: A report for an environment the manifest never declared is refused
      Given the workspace "chained" but:
        | ci.json | {"tests": []} |
      When I run "atf import-run nowhere ci.json"
      Then it is refused because "unknown environment"

    Scenario: A report that is not there at all says which one
      Given the workspace "chained"
      When I run "atf import-run local nowhere.json"
      Then it is refused because "no such file"
