Feature: the editor shows the same graph

  Scenario: the catalogue lists what the suite declares
    Given the screen "catalogue"
    Then the heading "Catalogue" is showing
    And the words "Notebook" are showing
    And the words "Note" are showing

  Scenario: the overview folds the two vocabularies and nothing else
    Given the screen "catalogue"
    When I read "/api/overview" from the editor
    Then it mentions "absent"
    And it mentions "sentence"

  Scenario: the catalogue is what the suite declares, read from the same core
    Given the screen "catalogue"
    When I read "/api/catalogue" from the editor
    Then it mentions "Notebook"
    And it mentions "directory"

  Scenario: opening a resource shows what would be sent to create it
    Given the screen "catalogue"
    When I read "/api/resource/standup" from the editor
    Then it mentions "would_create"
    And it mentions "recognised_by"
    And it mentions "notebooks/work/standup.md"

  Scenario: a resource the environment owns says why it cannot be made
    Given the screen "catalogue"
    When I read "/api/resource/archived" from the editor
    Then it mentions "only looks"

  Scenario: the tools an agent is offered are the operations the command has
    Given the screen "catalogue"
    When I read "/api/tools" from the editor
    Then it mentions "plan"
    And it mentions "explain"
    And it mentions "run"

  Scenario: every node of the spine is a link, so nothing is found only by searching
    Given the screen "spine"
    Then the heading "The graph" is showing
    And the link "Notebook work" is showing
    And the link "what nothing asks for" is showing

  Scenario: small lineage is said in words rather than drawn
    Given the screen "small_lineage"
    Then the words "outline needs pad" are showing
    And the img "Lineage" is not showing

  Scenario: a node many things stand on is drawn, and the sentence becomes the caption
    Given the screen "crowded"
    Then the img "Lineage" is showing
    And the words "needs nothing" are showing

  Scenario: what breaks if a resource does is on the resource, not in a separate report
    Given the screen "small_lineage"
    When I read "/api/graph/pad" from the editor
    Then it mentions "Sketch outline"

  Scenario: every link carries the environment, so a pasted one answers the same
    Given the screen "catalogue"
    Then the link "Graph" is showing
    And the words "environment:" are showing

  Scenario: the environment in the URL is the one the page answers for
    Given the screen "theirs_screen"
    Then the heading "Catalogue" is showing
    And the words "Notebook" are showing

  Scenario: the environment survives moving to another view
    Given the screen "theirs_screen"
    When I click the link "Overview"
    Then the words "theirs is" are showing

  Scenario: the overview runs the checks rather than assuming the suite is well formed
    Given the screen "faults"
    When I read "/api/overview" from the editor
    Then it mentions "faults"

  Scenario: taking a step in the composer re-answers what can be said next
    Given the screen "composing"
    Then the words "so far" are showing
    And the words "exists" are showing

  Scenario: a scenario and a pytest function are listed the same way
    Given the screen "listing"
    Then the heading "Tests" is showing
    And the words "scenario" are showing
    And the words "function" are showing

  Scenario: opening a test shows what it says and what it asks for
    Given the screen "one_test"
    Then the words "Given the draft" are showing
    And the link "scratch" is showing
    And the button "Run this test" is showing

  Scenario: a run is opened item by item, and can be exported as a registered format
    Given the screen "past_runs"
    Then the heading "Activity" is showing
