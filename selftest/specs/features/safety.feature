Feature: Safety rails
  ATF refuses what it should refuse, and says why, before touching an environment.

  Scenario: Seeding an environment outside mutable_envs is refused
    Given the workspace "chained"
    When I run "atf seed locked"
    Then it exits 2
    And the output mentions "mutable_envs"
    And the backend has 0 owners

  Scenario: A dangling dependency is reported at load, not at provision time
    Given the workspace "broken"
    When I run "atf status local"
    Then it exits 2
    And the output mentions "not a known node"
    And the backend has 0 owners

  Scenario: A failing spec exits nonzero, so a run can guard a deployment
    Given the workspace "failing"
    When I run "atf run"
    Then it exits 1
    And the output mentions "failed"
