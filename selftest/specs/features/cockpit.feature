Feature: The cockpit
  ATF's own interface, read as resources: a page is a resource, an element on it is a resource,
  and the server showing them is a resource that gets started and torn down. Not one line of step
  code below — every assertion is one ATF gives every suite.

  This feature used to carry a lint waiver for twelve field claims and a status code, and it was
  the target document's own evidence that generic vocabulary is not the same as readable
  vocabulary. The waiver is gone: what those lines said now lives in `specs/phrasebook.yaml`, and
  the sentences below say what a person would say about a page.

  Scenario: A cockpit comes up over a real suite
    Given the page "overview"
    Then the page "overview" was served
    And the page "overview" is titled "Overview · ATF"

  Scenario: A type page lists its instances and the environment's records in one table
    Given the element "instances_table"
    Then the element "instances_table" exists
    And the table lists 1 instance

  Scenario: The list that duplicated the nav and the table is gone
    Given the page "owner_type"
    Then the element "declared_heading" is gone

  Scenario: A resource that depends on something is drawn as well as described
    Given the page "groceries_node"
    Then the lineage is drawn as well as described
    And the element "node_payload" exists

  Scenario: A resource that depends on nothing has no lineage to draw
    Given the page "primary_node"
    Then the element "standalone_lineage_graph" is gone

  Scenario: A payload shows the placeholder that resolves at provisioning time
    Given the element "node_payload"
    Then the payload is shown once

  Scenario: A scenario is rendered as the Gherkin it was written in
    Given the page "scenarios"
    Then all three of its steps are shown as Gherkin

  Scenario: The composer offers the steps ATF provides as well as the suite's own
    Given the page "compose"
    Then the element "compose_step_options" exists

  Scenario: Writing a scenario is a button, never a badge
    Given the page "compose"
    Then writing it is offered as a button
    And writing it is not offered as a badge

  # Everything below needs the page to have *run*, not merely been served, so it needs a real
  # browser. Without one these skip and the rest of the suite still passes — see the README.
  #
  # Not one selector between them. A control is named by what it *is* and what it is *called*,
  # which is what a screen reader announces and what an accessibility tree exposes — so a scenario
  # about the interface is a scenario about what a person can perceive.

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
