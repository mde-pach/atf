Feature: The catalog
  A catalog is validated when it loads, whole, before a single resource is looked at — so a typo
  in it costs a command that refuses, not a half-provisioned environment.

  Where a scenario below only claims that the command succeeded, that is the claim: a catalog with
  anything wrong with it is a refusal, so "it ran" means "there is nothing wrong with this". What
  each catalog holds is in the table under `but:`, one row per file — see `selftest_adapters.py`
  for why a variation is written there rather than as a suite template of its own.

  Rule: A catalog is read as a whole, and every problem in it is reported at once

    Scenario: A catalog directory that is not there is reported, not read as an empty one
      Given the workspace "bare" but:
        | catalog | #absent |
      When I run "atf status local"
      Then it is refused because "does not exist"

    Scenario: A catalog with no registry of resource types is refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | #absent                        |
        | catalog/accounts.yaml  | {primary: {resource: account}} |
      When I run "atf status local"
      Then it is refused because "resources.yaml is missing"

    Scenario: A resource whose type the registry never declared is refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}}    |
        | catalog/ghosts.yaml    | {spooky: {resource: ghost}}  |
      When I run "atf status local"
      Then it is refused because "unknown resource type 'ghost'"

    Scenario: A type naming a system nothing knows how to talk to is refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: quantum}} |
      When I run "atf status local"
      Then it is refused because "no registered adapter"
      And the refusal also mentions "rest"

    Scenario: A type whose name is already something else's is refused, once per name
      Given the workspace "bare" but:
        | catalog/resources.yaml | {context: {system: rest}, api: {system: rest}} |
      When I run "atf status local"
      Then it is refused because "reserved fixture name"
      And the refusal also mentions "api"

    Scenario: Two resources of one type sharing a name are refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}}      |
        | catalog/a.yaml         | {primary: {resource: account}} |
        | catalog/b.yaml         | {primary: {resource: account}} |
      When I run "atf status local"
      Then it is refused because "duplicate name 'primary'"

    Scenario: Two resources of different types may share a name
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}, project: {system: rest}} |
        | catalog/a.yaml         | {shared: {resource: account}}                     |
        | catalog/b.yaml         | {shared: {resource: project}}                     |
      When I run "atf status local"
      Then the command succeeds

    Scenario: Everything wrong with one catalog is said at once, not one problem per run
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: quantum}, context: {system: rest}}                                 |
        | catalog/accounts.yaml  | {primary: {resource: account, depends_on: [accounts.missing]}, other: {resource: nope}} |
      When I run "atf status local"
      Then it is refused because "no registered adapter"
      And the refusal also mentions "reserved fixture name"
      And the refusal also mentions "not a known node"
      And the refusal also mentions "unknown resource type"

  Rule: A dependency has to be one that can be met

    # A dependency on a resource nobody declared is `safety.feature`'s first refusal, made against
    # the `broken` template, and it is left there: it is the example of validation happening at
    # load rather than at provision time, which is a safety claim before it is a catalog one.

    Scenario: A resource that depends on itself is refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}}                                  |
        | catalog/accounts.yaml  | {loop: {resource: account, depends_on: [accounts.loop]}}   |
      When I run "atf status local"
      Then it is refused because "dependency cycle"

    Scenario: A ring of dependencies is refused, and the whole ring is named
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}}                                                                                       |
        | catalog/accounts.yaml  | {a: {resource: account, depends_on: [accounts.b]}, b: {resource: account, depends_on: [accounts.c]}, c: {resource: account, depends_on: [accounts.a]}} |
      When I run "atf status local"
      Then it is refused because "dependency cycle"
      And the refusal also mentions "accounts.c"

  Rule: What one resource says about another is checked before anything runs

    Scenario: A resource referring to one that does not exist is caught at load
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}, project: {system: rest}}                                                       |
        | catalog/accounts.yaml  | {primary: {resource: account}}                                                                          |
        | catalog/projects.yaml  | {alpha: {resource: project, depends_on: [accounts.primary], body: {account_id: '@{accounts.typo.id}'}}}  |
      When I run "atf status local"
      Then it is refused because "not a known node"

    Scenario: A resource referring to one it never declared a dependency on is caught at load
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest}, project: {system: rest}}                        |
        | catalog/accounts.yaml  | {primary: {resource: account}}                                           |
        | catalog/projects.yaml  | {alpha: {resource: project, body: {account_id: '@{accounts.primary.id}'}}} |
      When I run "atf status local"
      Then it is refused because "does not list it in depends_on"

  Rule: A value that is new every run may not be what a resource is recognised by

    Scenario: A generated value in what a resource is found by is refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest, natural_key: email}}                     |
        | catalog/accounts.yaml  | {primary: {resource: account, body: {email: '@{fake:email}'}}}    |
      When I run "atf status local"
      Then it is refused because "part of the natural key and is generated"
      And the refusal also mentions "make the type ephemeral"

    Scenario: The same generated value is fine where the resource is never looked up again
      Given the workspace "bare" but:
        | catalog/resources.yaml | {visitor: {system: rest, lifecycle: ephemeral, natural_key: email}} |
        | catalog/visitors.yaml  | {walkin: {resource: visitor, body: {email: '@{fake:email}'}}}       |
      When I run "atf status local"
      Then the command succeeds

    Scenario: A generated value outside what it is found by is fine — it is written once
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest, natural_key: email}}                                                            |
        | catalog/accounts.yaml  | {primary: {resource: account, body: {email: primary@selftest.example, nickname: '@{fake:first_name}'}}}  |
      When I run "atf status local"
      Then the command succeeds

    Scenario: A reference to another resource is not a generated value, and belongs in the key
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest, natural_key: email}, note: {system: rest, natural_key: [account_id, slug]}}         |
        | catalog/accounts.yaml  | {primary: {resource: account, body: {email: primary@selftest.example}}}                                      |
        | catalog/notes.yaml     | {first: {resource: note, depends_on: [accounts.primary], body: {slug: first, account_id: '@{accounts.primary.id}'}}} |
      When I run "atf status local"
      Then the command succeeds

  Rule: What ATF is being asked to do about a resource is one of three things

    Scenario: Making one, borrowing one and only watching one are all a catalog may ask for
      Given the workspace "bare" but:
        | catalog/resources.yaml | {made: {system: rest}, borrowed: {system: rest, mode: reference}, watched: {system: rest, mode: data}} |
        | catalog/things.yaml    | {a: {resource: made}, b: {resource: borrowed}, c: {resource: watched}}                                |
      When I run "atf status local"
      Then the command succeeds

    Scenario: A fourth thing to do about a resource, or a fourth lifetime, is refused
      Given the workspace "bare" but:
        | catalog/resources.yaml | {account: {system: rest, mode: destroy, lifecycle: forever}} |
      When I run "atf status local"
      Then it is refused because "mode 'destroy'"
      And the refusal also mentions "lifecycle 'forever'"
