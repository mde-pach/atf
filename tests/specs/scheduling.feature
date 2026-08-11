Feature: laying a run out, and what the layout is read from

  @run @explain
  Scenario: explain says what can run beside what, and runs nothing
    Given the workspace "scaffolded"
    When I run "run --explain"
    Then the command succeeded
    And the result field "output" contains "can run beside something else"
    And the result field "output" contains "run alone"

  @run @explain
  Scenario: a sentence whose effect nothing declares is named as what forced a test to go alone
    Given the workspace "scaffolded"
    When I run "run --explain --json"
    Then the command succeeded
    And the result field "output" contains "has an effect nothing declares"

  @run @shard
  Scenario: a shard is a slice of the same layout every other shard is slicing
    Given the workspace "scaffolded"
    When I run "run --shard 1/2 --dry-run" as "first"
    And I run "run --shard 2/2 --dry-run" as "second"
    Then the first field "exit_code" is "0"
    And the second field "exit_code" is "0"

  @run @shard
  Scenario: a shard index outside the run never starts
    Given the workspace "scaffolded"
    When I run "run --shard 5/2 --json"
    Then the command refused, saying "usage"

  @run @seed
  Scenario: a shuffled run records the seed it ran in
    Given the workspace "scaffolded"
    When I run "run --shuffle"
    Then the command succeeded
    And the result field "output" contains "seed"

  @run @seed
  Scenario: naming the seed runs the same order again
    Given the workspace "scaffolded"
    When I run "run --seed 7" as "once"
    And I run "run --seed 7" as "again"
    Then the once field "exit_code" is "0"
    And the again field "exit_code" is "0"
