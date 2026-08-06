# Tutorial

Four chapters, in order. Each ends with something running.

The first three use a 25-line command-line app over SQLite, printed in chapter 1. Nothing to
install. Chapter 4 replaces it with your own system.

1. **[Run a suite](1-run-a-suite.md)** — run a suite you were handed, read a failure, fix it.
2. **[Write a test](2-write-a-test.md)** — the same behaviour as a pytest function and as a scenario.
3. **[Declare what it needs](3-declare-what-it-needs.md)** — declare resources and watch the
   dependency follow.
4. **[Point it at your own system](4-point-it-at-your-own-system.md)** — throw the app away and
   connect ATF to yours.

A term arrives when a chapter needs it. [The glossary](../orientation/glossary.md) defines all 27,
for when you meet a word and want its meaning before the chapter gets to it.

If you already use pytest, factory_boy, Cucumber, Terraform or dbt, read
[Coming from another tool](../orientation/coming-from-another-tool.md) first — it maps what you have onto
what ATF calls it.
