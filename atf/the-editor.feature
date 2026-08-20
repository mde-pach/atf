Feature: the editor shows the same graph

  Scenario: resources lists what the suite declares
    Given the screen "resources"
    Then the heading "Resources" is showing
    And the words "Notebook" are showing
    And the words "Note" are showing

  Scenario: writing a test is an action on the Tests page, not a standing nav destination
    Given the screen "listing"
    Then the link "Create test" is showing
    And the link "New test" is not showing

  Scenario: the overview folds the two vocabularies and nothing else
    Given the screen "resources"
    When I read "/api/overview" from the editor
    Then it mentions "absent"
    And it mentions "sentence"

  Scenario: resources is what the suite declares, read from the same core
    Given the screen "resources"
    When I read "/api/resources" from the editor
    Then it mentions "Notebook"
    And it mentions "directory"

  Scenario: opening a resource shows what would be sent to create it
    Given the screen "resources"
    When I read "/api/resource/standup" from the editor
    Then it mentions "would_create"
    And it mentions "recognised_by"
    And it mentions "notebooks/work/standup.md"

  Scenario: a resource the environment owns says why it cannot be made
    Given the screen "resources"
    When I read "/api/resource/archived" from the editor
    Then it mentions "only looks"

  Scenario: the tools an agent is offered are the operations the command has
    Given the screen "resources"
    When I read "/api/tools" from the editor
    Then it mentions "plan"
    And it mentions "explain"
    And it mentions "run"

  Scenario: a resource row expands to show what it is made of, and can be made from there
    Given the screen "notes_kind"
    When I click the button "standup"
    Then the words "needs" are showing
    And the button "make standup" is showing

  Scenario: a resource the environment owns cannot be made from its row either
    Given the screen "resources"
    When I click the button "archived"
    Then the words "only looks" are showing

  Scenario: every resource in the graph is a link in its sidebar, so nothing is found only by searching
    Given the screen "spine"
    Then the heading "The graph" is showing
    And the link "work" is showing
    And the link "pad" is showing
    And the link "what nothing asks for" is showing

  Scenario: a resource's own lineage sentence and its run action are on its node
    Given the screen "small_lineage"
    Then the words "outline needs pad" are showing
    And the link "run tests using outline" is showing

  Scenario: what breaks if a resource does is on the resource, not in a separate report
    Given the screen "small_lineage"
    When I read "/api/graph/pad" from the editor
    Then it mentions "Sketch outline"

  Scenario: a resource with many dependants still shows its own lineage sentence
    Given the screen "crowded"
    Then the words "needs nothing" are showing

  Scenario: every link carries the environment, so a pasted one answers the same
    Given the screen "resources"
    Then the link "Graph" is showing
    And the words "environment:" are showing

  Scenario: the environment in the URL is the one the page answers for
    Given the screen "theirs_screen"
    Then the heading "Resources" is showing
    And the words "Notebook" are showing

  Scenario: the environment survives moving to another view
    Given the screen "theirs_screen"
    When I click the link "Overview"
    Then the words "theirs is" are showing

  Scenario: the overview runs the checks rather than assuming the suite is well formed
    Given the screen "faults"
    When I read "/api/overview" from the editor
    Then it mentions "faults"

  Scenario: writing a new test opens the same editor, blank and ready to type
    Given the screen "new_test_screen"
    Then the words "new test" are showing
    And the button "Save" is showing
    And the button "▶ Try it" is showing

  Scenario: a scenario and a pytest function are listed the same way
    Given the screen "listing"
    Then the heading "Tests" is showing
    And the words "scenario" are showing
    And the words "function" are showing

  Scenario: a test's row is compact — a title and its tags, not its free text
    Given the screen "listing"
    Then the words "nothing carries it further" are not showing

  Scenario: opening a test shows the same real, editable text surface as writing one
    Given the screen "one_test"
    Then the words "Given the draft" are showing
    And the words "nothing carries it further" are showing
    And the link "scratch" is showing
    And the button "Save" is showing
    And the button "▶ Try it" is showing

  Scenario: a run is opened item by item, and can be exported as a registered format
    Given the screen "past_runs"
    Then the heading "Activity" is showing
