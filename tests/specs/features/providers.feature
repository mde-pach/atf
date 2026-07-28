Feature: Generated values
  Gherkin has no way to say "a fresh company name", so a value written between quotes is the only
  place a generated one can come from. `${uuid}`, `${now+1d 09:00}`, `${env:TOKEN}` and
  `${fake:email}` are calls to a registered provider, resolved when a resource is provisioned.

  Everything below runs a real suite and looks at what reached the backend, because what a provider
  produced is only interesting where it landed.

  Rule: A value generated once in a scenario is the same value everywhere in it

    Scenario: A body and the claim that checks it see the same generated value
      # Without this, an expression written twice would generate twice and no assertion about a
      # generated value could ever pass.
      Given the workspace "chained" but:
        | catalog/lists.yaml           | groceries:\n  resource: todo_list\n  represents: A list with a generated title.\n  depends_on: [owners.primary]\n  body:\n    slug: groceries\n    title: '@{uuid}'\n    owner_id: '@{owners.primary.id}'\n |
        | specs/steps/test_lists.py    | #absent |
        | specs/features/lists.feature | Feature: Generated\n\n  Scenario: The same value twice\n    Given the todo_list "groceries"\n    Then the todo_list "groceries" field "title" is "@{uuid}"\n |
      When I run "atf run"
      Then the command succeeds

    Scenario: Asking for a second one gives a different one
      Given the workspace "chained" but:
        | catalog/lists.yaml           | groceries:\n  resource: todo_list\n  represents: A list with two generated values.\n  depends_on: [owners.primary]\n  body:\n    slug: groceries\n    title: '@{uuid}'\n    note: '@{uuid#other}'\n    owner_id: '@{owners.primary.id}'\n |
        | specs/steps/test_lists.py    | #absent |
        | specs/features/lists.feature | Feature: Generated\n\n  Scenario: Two of them differ\n    Given the todo_list "groceries"\n    Then the todo_list "groceries" field "note" is not "@{uuid}"\n |
      When I run "atf run"
      Then the command succeeds

  Rule: A generated value reaches the backend, whatever shape the body is

    Scenario: A timestamp relative to now lands on the record
      Given the workspace "chained" but:
        | catalog/lists.yaml           | groceries:\n  resource: todo_list\n  represents: A list due tomorrow.\n  depends_on: [owners.primary]\n  body:\n    slug: groceries\n    due_at: '@{now+1d 09:00}'\n    owner_id: '@{owners.primary.id}'\n |
        | specs/steps/test_lists.py    | #absent |
        | specs/features/lists.feature | Feature: Generated\n\n  Scenario: It is there\n    Given the todo_list "groceries"\n    Then the todo_list "groceries" is:\n      \| slug   \| groceries \|\n      \| due_at \| #notnull  \|\n |
      When I run "atf run"
      Then the command succeeds

  Rule: A provider that cannot answer stops the run and says why

    Scenario: Reading a variable nobody exported
      Given the workspace "chained" but:
        | catalog/lists.yaml | groceries:\n  resource: todo_list\n  represents: A list named from the environment.\n  depends_on: [owners.primary]\n  body:\n    slug: groceries\n    title: '@{env:ATF_TESTS_NOT_EXPORTED}'\n    owner_id: '@{owners.primary.id}'\n |
      When I run "atf seed local"
      Then the run fails
      And the refusal names the variable nobody exported

    Scenario: An offset nobody can read
      Given the workspace "chained" but:
        | catalog/lists.yaml | groceries:\n  resource: todo_list\n  represents: A list due at a time nobody can parse.\n  depends_on: [owners.primary]\n  body:\n    slug: groceries\n    due_at: '@{now+banana}'\n    owner_id: '@{owners.primary.id}'\n |
      When I run "atf seed local"
      Then the run fails
      And it refuses the offset, showing the form it wanted

    Scenario: A name no provider answers to
      Given the workspace "chained" but:
        | catalog/lists.yaml | groceries:\n  resource: todo_list\n  represents: A list naming something that does not exist.\n  depends_on: [owners.primary]\n  body:\n    slug: groceries\n    title: '@{nonsense}'\n    owner_id: '@{owners.primary.id}'\n |
      When I run "atf seed local"
      Then the run fails
      And it says which providers there are
