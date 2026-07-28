Feature: The command
  What `atf` does before a suite exists, and what it does when pointed at one that already does.

  `init` is the only command with no suite to stand in, so its scenarios start from `the workspace
  "empty"` — a directory holding nothing. Everything they then observe was written by the command
  itself, which is the only honest way to check a scaffold.

  Rule: A new suite is something the command writes, not something a person assembles

    Scenario: A suite is scaffolded where there was nothing
      Given the workspace "empty"
      When I run "atf init"
      Then the command succeeds
      And the output says a suite was scaffolded

    Scenario: What is scaffolded passes before anyone edits it
      # The first thing a newcomer does after `atf init` is run it. If that is red, the scaffold has
      # taught them that a red suite is normal, and nothing after that lands.
      Given the workspace "empty"
      When I run "atf init"
      And the developer runs the scaffolded suite
      Then the command succeeds
      And the scaffolded suite passes

    Scenario: Run a second time, it writes nothing and says so
      # `init` never overwrites a file that is already there. Run twice, the second run finds
      # everything present and has nothing to do — and what the first run wrote still passes,
      # which is what says it was left alone rather than merely not reported.
      Given the workspace "empty"
      When I run "atf init"
      And I run "atf init"
      Then the command succeeds
      And the output says the directory already holds one
      When the developer runs the scaffolded suite
      Then the command succeeds
      And the scaffolded suite passes

  Rule: Status is a reading of the whole catalog, resource by resource

    Scenario: Every resource is listed, with what this environment has to say about it
      # Three states, and none of them is a failure: two resources nothing has made yet, and one
      # that is never looked for at all because it is built per run.
      Given the workspace "ephemeral"
      When I run "atf status local"
      Then the command succeeds
      And it says nothing is there yet
      And it says the guest is built for each run rather than found
      And it tallies how many of them are there

  Rule: Which environment a command uses is a question with one answer

    Scenario: An environment named on the command line beats one the developer exported
      Given the workspace "chained"
      When I run "atf status local" with ATF_ENV exported as "locked"
      Then the command succeeds
      And it says it looked in "local"

  Rule: An environment that cannot reach a resource says so rather than failing

    Scenario: A resource whose system this environment configures no adapter for is reported
      # Not an error: the catalog is a description of everything, and an environment is allowed to
      # be a place where some of it does not apply.
      Given the workspace "bare" but:
        | atf.yaml               | {default_env: local, environments: {local: {}}} |
        | catalog/resources.yaml | {account: {system: rest, natural_key: email}}   |
        | catalog/accounts.yaml  | {primary: {resource: account, body: {email: a@b.test}}} |
      When I run "atf status local"
      Then the command succeeds
      And it says the resource is one this environment cannot reach

  Rule: A secret the manifest names but nobody exported stops the command, saying which

    Scenario: A client setting pointing at a variable nobody exported names the client
      Given the workspace "bare" but:
        | atf.yaml | {default_env: local, environments: {local: {clients: {api: {auth: {value_env: SELFTEST_NOT_EXPORTED}}}}}} |
      When I run "atf status local"
      Then it is refused because "SELFTEST_NOT_EXPORTED is not set"
      And the refusal names the client that wanted it
