Feature: Running a command

  A command-line program is a class of system, the same way a JSON API is: a command line, a
  working directory, an environment, an exit code and two streams. ATF runs one, and what came back
  is a record like any other — so every claim the framework already makes applies to it, and no
  suite ever writes the subprocess again.

  The command line is written the way a person writes one. Every other feature here says
  `I run "atf status local"`, which is the same step said about the program this suite is testing.

  Rule: What came back is what a scenario can claim about

    Scenario: A command that worked says so
      When I run "echo hello"
      Then the command succeeds
      And the output mentions "hello"

    Scenario: A command that failed says so, and no scenario has to know which code means what
      When I run "false"
      Then the command failed
