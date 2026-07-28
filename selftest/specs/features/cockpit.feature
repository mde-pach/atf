# atf-lint: ignore field-claim, status-code
# The flagship "no step code at all" feature, and the clearest evidence that generic vocabulary is
# not the same as readable vocabulary: zero step code was bought by pushing `field "status" is "200"`
# up into the layer a product person reads. These lines go once the UI half lands — a page's status
# becomes something said about the page, and an element's `count` becomes what is on it.
Feature: The cockpit
  ATF's own interface, read as resources: a page is a resource, an element on it is a resource,
  and the server showing them is a resource that gets started and torn down. Not one line of step
  code below — every assertion is one ATF gives every suite.

  Scenario: A cockpit comes up over a real suite
    Given the page "overview"
    Then the page "overview" field "status" is "200"
    And the page "overview" field "title" is "Overview · ATF"

  Scenario: A type page lists its instances and the environment's records in one table
    Given the element "instances_table"
    Then the element "instances_table" exists
    And the element "instance_rows" field "count" is "1"

  Scenario: The list that duplicated the nav and the table is gone
    Given the page "owner_type"
    Then the element "declared_heading" is gone

  Scenario: A resource that depends on something is drawn as well as described
    Given the page "groceries_node"
    Then the element "lineage_graph" exists
    And the element "lineage_boxes" field "count" is "2"
    And the element "node_payload" exists

  Scenario: A resource that depends on nothing has no lineage to draw
    Given the page "primary_node"
    Then the element "standalone_lineage_graph" is gone

  Scenario: A payload shows the placeholder that resolves at provisioning time
    Given the element "node_payload"
    Then the element "node_payload" field "count" is "1"

  Scenario: A scenario is rendered as the Gherkin it was written in
    Given the page "scenarios"
    Then the element "scenario_gherkin_steps" field "count" is "3"

  Scenario: The composer offers the steps ATF provides as well as the suite's own
    Given the page "compose"
    Then the element "compose_step_options" exists

  Scenario: Writing a scenario is a button, never a badge
    Given the page "compose"
    Then the element "compose_write_button" field "text" is "Save"
    And the element "compose_write_chip" is gone

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
