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

  Scenario: A small lineage is a sentence, not a diagram
    Given the page "groceries_node"
    Then the element "lineage_graph" is gone
    And the element "node_payload" exists

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
    Then the element "compose_write_button" field "text" is "Write this scenario"
    And the element "compose_write_chip" is gone

  # Everything below needs the page to have *run*, not merely been served, so it needs a real
  # browser. Without one these skip and the rest of the suite still passes — see the README.
  @browser
  Scenario: A step picker keeps its options hidden until it is opened
    Given the view "then_picker_at_rest"
    Then the view "then_picker_at_rest" field "visible" is "0"

  @browser
  Scenario: Focusing a step picker shows what it offers
    Given the view "then_picker_opened"
    Then the view "then_picker_opened" field "visible" is not "0"

  @browser
  Scenario: Typing narrows a step picker to what matches
    Given the view "then_picker_filtered"
    Then the view "then_picker_filtered" field "visible" is "1"
    And the view "then_picker_filtered" field "data-value" is "the list belongs to the owner"

  @browser
  Scenario: A small lineage reads as a sentence a person can follow
    Given the view "catalog_lineage_sentence"
    Then the view "catalog_lineage_sentence" field "text" is "A list under the primary owner."
