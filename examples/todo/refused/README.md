# Suites ATF refuses

Nothing here is meant to pass. Each file is a mistake ATF catches **at collection**, before a single
test body runs, and it is kept so the message can be read.

```bash
cd examples/todo
uv run pytest refused/
```

```text
ERROR: this suite cannot be run as written:

refused/ambiguous.feature::test_two_owners_are_arranged_and_a_step_asks_for_the_owner
    'owner' is ambiguous: 2 of that kind are in scope — primary, secondary.
    Ask for the one you mean by name.

refused/test_ambiguous.py::test_two_owners_in_scope
    'owner' is ambiguous: 2 of that kind are in scope — primary, secondary.
    Ask for the one you mean by name.

refused/test_ambiguous.py::test_a_kind_with_no_factory
    'plan' asks for a Plan, nothing is in scope, and it has no factory.
    Name the one you mean, or give it a factory.
```

The scenario is the interesting one. Pytest cannot answer it: a scenario's fixture closure is only
`['request']` and its steps' parameters are never in it. ATF answers it from its own step registry —
`When I list the owner's lists` is written `def _(shell, owner)`, so the sentence asks for an
`owner`, and the two `Given` lines say two are in scope.
