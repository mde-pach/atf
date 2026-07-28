Feature: The manifest
  Every entry point reads the manifest first, so a manifest that cannot be trusted stops the
  command before it has touched anything.

  Each scenario below puts exactly one thing wrong with a suite and runs a real `atf` inside it.
  What is wrong is written in the table under `but:` — one row per file, holding that file's whole
  text — rather than in a suite template of its own, because forty templates that differ by three
  lines each is the fixture sprawl this project is trying to be rid of.

  Rule: A manifest is checked as a whole, before anything is touched

    Scenario: A manifest that names its directories, environments and secrets is accepted
      Given the workspace "chained"
      When I run "atf status local"
      Then the command succeeds
      And it lists the owner and the list that depends on it

    Scenario: A manifest missing what every suite needs says everything it is missing
      Given the workspace "bare" but:
        | atf.yaml | {catalog: ./catalog} |
      When I run "atf status local"
      Then it is refused because "default_env"
      And the refusal also mentions "environments"

    Scenario: A default environment with nothing declared under it is refused
      Given the workspace "bare" but:
        | atf.yaml | {default_env: staging, environments: {local: {}}} |
      When I run "atf status local"
      Then it is refused because "no entry under environments"

    Scenario: Letting an environment be changed without declaring it is refused
      Given the workspace "bare" but:
        | atf.yaml | {default_env: local, mutable_envs: [ghost], environments: {local: {}}} |
      When I run "atf status local"
      Then it is refused because "unknown environment(s) ghost"

    Scenario: A manifest that is not readable at all is refused
      Given the workspace "bare" but:
        | atf.yaml | default_env: [ |
      When I run "atf status local"
      Then it is refused because "invalid YAML"

    Scenario: Asking for an environment the manifest never declared lists the ones it did
      Given the workspace "bare"
      When I run "atf status nowhere"
      Then it is refused because "unknown environment"
      And the refusal also mentions "local"

    Scenario: Saying what a tagged scenario needs in any shape but a mapping is refused
      Given the workspace "bare" but:
        | atf.yaml | {default_env: local, environments: {local: {}}, requires: [browser]} |
      When I run "atf status local"
      Then it is refused because "mapping of tag to the system it needs"

  Rule: A secret is named in the manifest, never written in it

    Scenario: A setting pointing at a variable nobody exported names the variable and the setting
      Given the workspace "bare" but:
        | atf.yaml | {default_env: local, environments: {local: {adapters: {rest: {base_url_env: SELFTEST_NOT_EXPORTED}}}}} |
      When I run "atf status local"
      Then it is refused because "SELFTEST_NOT_EXPORTED is not set"
      And the refusal names the setting that wanted it

  Rule: The command finds the suite it is standing in

    Scenario: Run from inside the suite, the command finds it without being told where it is
      Given the workspace "chained"
      When I run "atf status local", letting it find the suite itself
      Then the command succeeds
      And it lists the owner and the list that depends on it

    Scenario: Run nowhere near a suite, the command says how to make one
      When I run "atf status local" outside any suite
      Then it is refused because "atf init"

    Scenario: Pointed at a manifest that is not there, the command says which one
      Given the workspace "bare" but:
        | atf.yaml | #absent |
      When I run "atf status local"
      Then it is refused because "does not exist"

    Scenario: A manifest written in TOML is not supported yet, and says so rather than guessing
      Given the workspace "bare" but:
        | atf.yaml | #absent |
        | atf.toml |         |
      When I run "atf status local", letting it find the suite itself
      Then it is refused because "not supported yet"

    Scenario: With no environment named, the command uses the one the suite calls its default
      Given the workspace "chained"
      When I run "atf run"
      Then the command succeeds
      And the run names the environment it used
