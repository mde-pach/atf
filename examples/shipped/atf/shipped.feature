Feature: the systems ATF ships

  Scenario: a file is made inside the directory it needs
    Given the draft "today"
    Then the draft "today" exists
    And the draft "today" text is "written by ATF\n"
    And the workspace "scratch" exists

  Scenario: a scenario that changes a thing gets one made for the test
    Given the draft "today" with text "changed"
    Then the draft "today" text is "changed"

  Scenario: a process is recognised by the command line it was started as
    Given the sleeper "waiter"
    Then the sleeper "waiter" exists
