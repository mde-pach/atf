Feature: Guests and labels
  A guest is built fresh for each run and torn down afterwards; a label must already exist.

  There is no `.py` beside this feature and it needs none: every claim below is one ATF makes for
  any suite, said in this suite's own words through `specs/phrasebook.yaml`. ATF collects a
  `.feature` nobody bound, so the module that used to hold nothing but an import is simply gone.

  Scenario: A guest is ready as soon as it is provisioned
    Given the guest "visitor"
    Then the guest "visitor" is ready

  Scenario: The environment's label is available
    Given the label "urgent"
    Then the label "urgent" exists
    And the label "urgent" is called "Urgent"
