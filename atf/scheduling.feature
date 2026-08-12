Feature: laying a run out, and what the layout is read from

  A run parallelises itself, and that is an interface decision rather than an optimisation. Two
  scenarios that share nothing permanent cannot interfere, and the graph knows it — so there is no
  flag, no annotation and no marker on a test.

  Scenario: explaining a run says what can go beside what, and runs nothing
    Given a suite on disk
    When I run "run --explain"
    Then the command succeeded
    And it mentions "can run beside something else"
    And it mentions "run alone"

  Scenario: a sentence whose effect nothing declares is named as what forced a test to go alone
    Given a suite on disk
    When I run "run --explain"
    Then the command succeeded
    And it mentions "has an effect nothing declares"

  Scenario: a shard is a slice of the same layout every other shard is slicing
    Given a suite on disk
    When I run "run --shard 1/2 --dry-run"
    Then its exit code is 0
    When I run "run --shard 2/2 --dry-run"
    Then its exit code is 0

  Scenario: a shard index outside the run never starts
    Given a suite on disk
    When I run "run --shard 5/2 --json"
    Then the command refused, saying "usage"

  Scenario: a shuffled run records the seed it ran in
    Given a suite on disk
    When I run "run --shuffle"
    Then the command succeeded
    And it mentions "seed"

  Scenario: naming the seed runs the same order again
    Given a suite on disk
    When I run "run --seed 7"
    Then its exit code is 0
    When I run "run --seed 7"
    Then its exit code is 0

  Scenario: a run with nothing said about it runs concurrently
    Given a suite on disk
    When I run "run"
    Then the command succeeded
