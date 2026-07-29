Feature: Importing a catalog from a schema
  A team adopting ATF hand-writes its whole catalog: every resource type, where it lives, and the
  field a record of it is recognised by. That is the blank page, and it is the first hour of using
  the tool — spent restating what the service already publishes. `atf import openapi` reads the
  schema and writes that hour.

  Everything it infers is a guess, so every scenario below is about how a guess behaves: it says
  what it was guessed from, it declines rather than picks when nothing is clearly ahead, and it
  never touches a line somebody has since corrected.

  Rule: The first import fills a registry nobody has written yet

    Scenario: What the schema says about a collection is written as a resource type
      # The whole of the blank page, removed: where the accounts are, what identifies one, and the
      # reason that field was chosen — none of it typed by anyone.
      Given the workspace "bare" but:
        | api.json | {"paths":{"/accounts":{"get":{"parameters":[{"name":"email","in":"query"}]},"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["email","name"],"properties":{"email":{"type":"string","format":"email"},"name":{"type":"string"},"created_at":{"type":"string","format":"date-time"}}}}}}}}}} |
      When the developer imports the schema they were handed
      Then the command succeeds
      When the developer reads the resource types
      Then it says where an account lives
      And an account is recognised by its email address

    Scenario: The guess says what it was guessed from, where a reader will meet it
      # A guess whose reason lives somewhere else is a guess nobody checks. The one thing a person
      # has to look at is beside the answer, in the file they are about to keep.
      Given the workspace "bare" but:
        | api.json | {"paths":{"/accounts":{"get":{"parameters":[{"name":"email","in":"query"}]},"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["email","name"],"properties":{"email":{"type":"string","format":"email"},"name":{"type":"string"},"created_at":{"type":"string","format":"date-time"}}}}}}}}}} |
      When the developer imports the schema they were handed
      And the developer reads the resource types
      Then the guess says it was made from what the service lets you search by

    Scenario: What a schema cannot say is said, rather than guessed
      # Whether ATF may create a resource, whether it survives the run, and what needs what: three
      # things a schema has no opinion about, and three things a wrong guess would be expensive.
      Given the workspace "bare" but:
        | api.json | {"paths":{"/accounts":{"get":{"parameters":[{"name":"email","in":"query"}]},"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["email","name"],"properties":{"email":{"type":"string","format":"email"},"name":{"type":"string"},"created_at":{"type":"string","format":"date-time"}}}}}}}}}} |
      When the developer imports the schema they were handed
      Then the command succeeds
      And it says what a schema could not tell it

    Scenario: A collection nested under another is recognised within its parent, and says so
      # A project is only unique inside the account it belongs to, and the path is what says so —
      # which makes this the one dependency an import can honestly infer.
      Given the workspace "bare" but:
        | api.json | {"paths":{"/accounts/{account_id}/projects":{"get":{"parameters":[{"name":"slug","in":"query"}]},"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["slug"],"properties":{"slug":{"type":"string"}}}}}}}}}} |
      When the developer imports the schema they were handed
      Then the command succeeds
      When the developer reads the resource types
      Then a project is recognised by its own name within its account
      And it says which account a project hangs off

  Rule: Where nothing is clearly ahead, nothing is chosen

    Scenario: Two equally likely fields leave no key, and name what was considered
      # The worst failure available here is a wrong key, because it is silent: nothing matches, so
      # every run makes another record and nobody finds out until they look at the environment.
      # A type that will not provision until somebody chooses costs an afternoon instead.
      Given the workspace "bare" but:
        | api.json | {"paths":{"/labels":{"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["name","slug"],"properties":{"name":{"type":"string"},"slug":{"type":"string"}}}}}}}}}} |
      When the developer imports the schema they were handed
      Then the command succeeds
      When the developer reads the resource types
      Then nothing says how one label is told from another
      And both of the fields it weighed up are named

  Rule: A registry somebody has since edited belongs to them

    Scenario: A second import proposes what is missing and writes nothing
      Given the workspace "bare" but:
        | catalog/resources.yaml | owner:\n  system: rest\n  path: /owners\n  natural_key: slug\n |
        | api.json               | {"paths":{"/owners":{"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["name","slug"],"properties":{"name":{"type":"string"},"slug":{"type":"string"}}}}}}}},"/accounts":{"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["name","slug"],"properties":{"name":{"type":"string"},"slug":{"type":"string"}}}}}}}}}} |
      When the developer imports the schema they were handed
      Then the command succeeds
      And it says nothing was written
      When the developer reads the resource types
      Then the owner is still recognised the way somebody wrote it
      And nothing about accounts is in the file

    Scenario: A field this catalog already matches on decides the next close call
      # The point of the whole design: correcting one guess by hand is what makes the next one
      # right. Nothing about `name` or `slug` in the schema separates them — the catalog does.
      Given the workspace "bare" but:
        | catalog/resources.yaml | owner:\n  system: rest\n  path: /owners\n  natural_key: slug\n |
        | api.json               | {"paths":{"/owners":{"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["name","slug"],"properties":{"name":{"type":"string"},"slug":{"type":"string"}}}}}}}},"/accounts":{"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["name","slug"],"properties":{"name":{"type":"string"},"slug":{"type":"string"}}}}}}}}}} |
      When the developer applies what the import proposed
      Then the command succeeds
      When the developer reads the resource types
      Then an account is recognised the way this project already recognises everything else
      And the guess says the project's own catalog is where it learned that

  Rule: The schema is somewhere the manifest names, so re-importing takes no arguments

    Scenario: With the schema named in the manifest, the import needs nothing said
      Given the workspace "bare" but:
        | atf.yaml | {default_env: local, environments: {local: {}}, schemas: {api: {path: ./api.json}}} |
        | api.json | {"paths":{"/accounts":{"get":{"parameters":[{"name":"email","in":"query"}]},"post":{"requestBody":{"content":{"application/json":{"schema":{"type":"object","required":["email","name"],"properties":{"email":{"type":"string","format":"email"},"name":{"type":"string"},"created_at":{"type":"string","format":"date-time"}}}}}}}}}} |
      When the developer imports the schema the manifest names
      Then the command succeeds
      When the developer reads the resource types
      Then it says where an account lives

    Scenario: With no schema anywhere, it says where one is named
      Given the workspace "bare"
      When the developer imports the schema the manifest names
      Then it is refused because "no schema to import"
      And it says where to name one so this never has to be said again

    Scenario: A document that is not a schema is refused, saying what was expected
      Given the workspace "bare" but:
        | api.json | {"swagger": "a page about our API"} |
      When the developer imports the schema they were handed
      Then it is refused because "not an OpenAPI schema"
