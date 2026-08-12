Feature: what this suite says about a command

  A `Phrase:` block is vocabulary rather than a test, and it says so in the word itself — a reader
  scanning this file does not have to notice a tag to know these are not scenarios.

  `the command succeeded` is not here: it is the shell system's own word, met by anybody testing a
  command line and by nobody else.

  Phrase: the command refused, saying "{code}"
    Then its exit code is 2
    And it mentions "{code}"

  Phrase: a suite on disk
    Given the workspace "scaffolded"

  Phrase: a suite that is wrong on purpose
    Given the workspace "broken"
