Feature: Safety rails
  ATF refuses what it should refuse, and says why, before touching an environment.

  Nothing below names a field, an exit code or a flag — `atf lint` holds it to that. What each
  sentence stands for is in `specs/phrasebook.yaml`, which is data, so the vocabulary a reader
  needs is the vocabulary the product already has, and there is one place to edit when a refusal
  changes shape.

  Scenario: Seeding an environment outside mutable_envs is refused
    Given the workspace "chained"
    When I run "atf seed locked"
    Then it is refused because "mutable_envs"
    And nothing was created

  Scenario: A dangling dependency is reported at load, not at provision time
    Given the workspace "broken"
    When I run "atf status local"
    Then it is refused because "not a known node"
    And nothing was created

  Scenario: The same command is refused in one environment and accepted in the other
    Given the workspace "chained"
    When I run "atf seed locked", holding it as locked_env
    And I run "atf seed local", holding it as open_env
    Then seeding the locked environment was refused
    And seeding the open environment worked
    And the owner "primary" exists

  Scenario: A failing spec exits nonzero, so a run can guard a deployment
    Given the workspace "failing"
    When I run "atf run"
    Then the run fails
