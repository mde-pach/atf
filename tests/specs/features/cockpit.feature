Feature: The cockpit
  ATF's own interface, read as resources: a page is a resource and the server showing it is a
  resource that gets started and torn down. Not one line of step code below — every assertion is
  one ATF gives every suite.

  Every claim names a control by what it *is* and what it is *called*, which is what a screen
  reader announces. There is no selector in this file and none in the catalog behind it: a selector
  describes today's markup, and a rename would make a scenario wrong about a page that still works.

  The scenarios above the line read the HTML the cockpit sent, which costs nothing and runs on any
  checkout. The ones below need the page to have *run*. They are the same sentences.

  Scenario: A cockpit comes up over a real suite
    Given the page "overview"
    Then the page "overview" was served
    And the page "overview" is titled "Overview · ATF"
    And the heading "Can I ship?" is showing

  Scenario Outline: Every vertical is a whole page with the same way around it
    Given the page "<page>"
    Then the page "<page>" was served
    And the navigation "Sections" is showing

    Examples:
      | page      |
      | overview  |
      | scenarios |
      | catalog   |

  Scenario: The rail offers three verticals, and nothing the interface used to have
    Given the page "overview"
    Then the link "Overview" is showing
    And the link "Scenarios 1" is showing
    And the link "Resources 2" is showing
    And the words "Fixtures" are not showing

  Scenario: A path the interface used to answer on is not quietly served as something else
    Given the page "retired_path"
    Then the page "retired_path" was not found

  Scenario: A resource nobody declared is a refusal, not an empty page
    Given the page "unknown_node"
    Then the page "unknown_node" was not found

  Scenario: The catalog is navigated by resource type, with how many of each are there
    Given the page "catalog"
    Then the link "owner 0/1 present" is showing
    And the link "todo_list 0/1 present" is showing

  Scenario: A resource ATF can never make says so, rather than offering a button that will not work
    Given the page "badge_node"
    Then the words "looks it up but never creates it" are showing

  Scenario: A type page lists its instances and what the environment holds, in one table
    Given the page "owner_type"
    Then the cell "primary" is showing
    And the cell "The owner the list hangs off." is showing

  Scenario: The list that duplicated the nav and the table is gone
    Given the page "owner_type"
    Then the heading "Declared in the catalog" is not showing

  Scenario: A resource that depends on something is drawn as well as described
    Given the page "groceries_node"
    Then the heading "Lineage" is showing
    And the heading "Payload" is showing

  Scenario: A resource that depends on nothing has no lineage to draw
    Given the page "primary_node"
    Then the heading "Lineage" is not showing

  Scenario: A payload shows the reference it will resolve at provisioning time
    Given the page "groceries_node"
    Then the payload shows the reference rather than a value

  Scenario: A scenario is rendered as the Gherkin it was written in
    Given the page "scenarios"
    Then its steps read as the lines they were written as

  Scenario: A scenario is named by what it describes, never by its pytest identifier
    Given the page "scenarios"
    Then the heading "A list belongs to its owner" is showing
    And the words "test_a_list_belongs_to_its_owner" are not showing

  Scenario: A scenario links every resource it names to the catalog entry that declares it
    Given the page "scenario_detail"
    Then the link "primary" is showing
    And the link "groceries" is showing

  Scenario: A scenario says what running it would create, and where it is written
    Given the page "scenario_detail"
    Then the words "Running this will create" are showing
    And the words "lists.feature" are showing

  Scenario: Scenarios can be narrowed to the ones in a state worth acting on
    Given the page "scenarios"
    Then the button "Never run (1)" is showing
    And the button "Failing (0)" is showing

  Scenario: The composer offers the steps ATF provides as well as the suite's own
    Given the page "compose"
    Then the steps ATF gives every suite are offered

  Scenario: Writing a scenario is offered as something you press
    Given the page "compose"
    Then the button "Save" is showing

  Scenario: The composer is reachable from the page that lists what there is to compose
    Given the page "scenarios"
    Then the link "Compose a scenario ＋" is showing

  Scenario: A scenario offers writing another one beside it, in the same feature
    Given the page "scenario_detail"
    Then the link "Add another to Lists ＋" is showing

  # Everything below needs the page to have *run*, not merely been served, so it needs a real
  # browser. Without one these skip and the rest of the suite still passes — see the README.
  #
  # They say nothing different from the ones above. `the option "groceries" is not showing` is one
  # claim, and a combobox that hides its options until it is opened is the reason it can only be
  # answered here: nothing in the HTML says which of them a person can currently see.

  @browser
  Scenario: A step picker keeps its options hidden until it is opened
    Given the screen "compose"
    Then the option "groceries" is not showing

  @browser
  Scenario: Focusing a step picker shows what it offers
    Given the screen "compose"
    When I click the combobox "what is this about…"
    Then the option "groceries" is showing

  @browser
  Scenario: Typing narrows a step picker to what matches
    Given the screen "compose"
    When I click the combobox "what is this about…"
    And I type "groceries" into the combobox "what is this about…"
    Then the option "groceries" is showing
    And the option "every owner" is not showing

  @browser
  Scenario: A small lineage reads as a sentence a person can follow
    Given the screen "groceries_node"
    Then the words "A list under the primary owner." are showing

  # Running a scenario from the interface is a *mutation*, and reading a page can never be one: the
  # `html` system only ever GETs, deliberately, so nothing that reads the cockpit can change it. So
  # the one place a scenario can press a button is here, through a real browser.

  @browser
  Scenario: A scenario can be run from the interface that describes it
    Given the screen "scenarios"
    When I click the link "A list belongs to its owner"
    And I click the button "Run this scenario against local"
    Then the words "passed" are showing

  @browser
  Scenario: An environment nobody opened for writing will not run anything
    Given the screen "locked_scenarios"
    When I click the link "A list belongs to its owner"
    Then the words "locked is read-only" are showing
    And the button "Run this scenario against locked" is disabled
