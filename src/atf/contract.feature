Feature: a system holds the contract every system holds

  The contract is not a command. It ships with ATF as this file, and `atf run --contract` puts it
  in front of your own scenarios — so the thing ATF asks of an extension is written in the language
  ATF asks you to write in.

  Scenario: every kind can be made, read back, changed and removed
    When I put every kind ATF may make through the contract
    Then every system held it
