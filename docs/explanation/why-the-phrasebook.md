# About the phrasebook

Keeping technical vocabulary out of spec text is one design goal, enforced two ways: a lint rule
that catches the mechanical cases, and a [phrasebook](../reference/phrasebook.md) that gives a spec
author somewhere to say the value instead of the field. This page is why both exist and where each
one stops.

## Why it exists {#why}

The generic claims read fine while a scenario is only saying whether something is there:
`Then the owner "primary" exists` needs no translation. The moment a *value* is involved they stop.
`Then the result field "exit_code" is "2"` is a struct field access spelled in English, so making a
suite generic used to mean making its specs *less* readable exactly where it mattered.

A phrase is the layer between the two. The technical vocabulary lives in one file — which is also
the only place to edit when `mutable_envs` is renamed — and the spec says what a person means.

## Why it does not rewrite the feature {#not-a-rewrite}

Expanding before pytest-bdd parses would be less code, and the run report would then show four
primitive steps where the file shows one sentence — the reader reading one thing and the cockpit
reporting another. So a phrase is a real step definition that runs its steps inside itself. One
line in the file, one line in the report.

## What the linter does not check, and why {#lint-not}

**The words.** An earlier version of [`atf lint`](../reference/cli.md#atf-lint) reported a spec line
naming a field, a status code, a path, a flag or a selector, on the grounds that the layer below had
leaked into the layer above. That rule is real — it is the reason the phrasebook exists — but it is
not checkable, because it infers *meaning* from *syntax*.

A quoted `/products/42` is a route escaping an adapter in one suite and the domain's own value in
another: a redirect target, a CMS slug, a router rule. `503` is an implementation detail here and
the entire subject matter of a monitoring product. Nothing separates the two but knowing what the
system under test *is*, which a linter does not. What the rule produced was false positives on
correct specs, a waiver comment per line, and a check that meant nothing.

Keeping technical vocabulary out of spec text is still the point — it is a judgement, and it belongs
to a reviewer. What `atf lint` checks instead is the narrower, syntactic version of the same rule:
see [the vocabulary rules](../reference/cli.md#lint-vocabulary-rules).

## Where to go next

- [Phrasebook reference](../reference/phrasebook.md) — the file, its rules, and what a failure says.
- [CLI reference](../reference/cli.md#atf-lint) — `atf lint` and the rules it does check.
- [About the model](the-model.md) — the framework/domain line this page is one instance of.
