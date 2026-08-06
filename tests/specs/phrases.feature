@phrase
Scenario: the command succeeded
  Then the result field "exit_code" is "0"

@phrase
Scenario: the command refused, saying "{code}"
  Then the result field "exit_code" is "2"
  And the result field "output" contains "{code}"
