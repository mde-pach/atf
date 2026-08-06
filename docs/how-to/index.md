# Guides

Task-shaped. Each answers one question and links to [reference](../reference/index.md) for the
definitions.

## Getting going

[Install ATF](install-atf.md) is the command, what it needs, and the browser dependency you only
install if a suite uses one. [Adopt ATF in an existing suite](adopt-atf-in-an-existing-suite.md) is
the route in for a repository that already has hundreds of pytest tests: one directory, its shared
setup turned into resources, and every existing test still working.

## Arrange

[Add a resource](add-a-resource.md) takes something your tests need from not existing at all to being
provisioned. [Give a resource a factory](give-a-resource-a-factory.md) is for when the identity does
not matter and ATF should build one. [Depend on another resource](depend-on-another-resource.md) is
the typed field that makes one resource bring another with it.

Then the awkward resources. [Vary a resource for one test](vary-a-resource-for-one-test.md) changes
one field for one scenario and nothing else.
[Require something you cannot create](require-something-you-cannot-create.md) is for the plans, flags
and regions the environment owns.
[Make something fresh for each test](make-something-fresh-for-each-test.md) covers scope, teardown,
and proving the teardown happened.

## Act and assert

[Write a scenario](write-a-scenario.md) is Gherkin as ATF reads it, and the sentences you get before
teaching it anything. [Teach ATF a sentence](teach-atf-a-sentence.md) turns your team's vocabulary
into phrases, in Gherkin, with no Python.
[Write a step in Python](write-a-step-in-python.md) is for what that vocabulary cannot say.

Three guides are about claiming. [Assert a record field by field](assert-a-record-field-by-field.md)
covers claims, markers, and compressing a set of them.
[Test a web interface](test-a-web-interface.md) drives a browser by role and accessible name, never a
selector. [Test a command line](test-a-command-line.md) runs the tool and reads what came back.

## Environments and runs

[Configure an environment](configure-an-environment.md) covers systems, secrets, and keeping
production unwritable. [Run ATF in CI](run-atf-in-ci.md) covers exit codes, reports, and bringing the
results back. [Run only what a change touched](run-only-what-a-change-touched.md) uses the graph for
selection and impact.

[Share an environment](share-an-environment.md) is for one staging environment and several people in
it, including the race it does not solve. [Keep a large suite fast](keep-a-large-suite-fast.md) is
what to spend and what to stop spending once the suite is large enough to notice.

When it is red, [Work out why it is red](work-out-why-it-is-red.md) is the diagnosis path end to end.
When ATF has no word for a system you use, [Teach ATF a new system](teach-atf-a-new-system.md) shows
the adapter that has been arranging your records since the first page.

New to ATF? Start with the [tutorial](../tutorial/index.md) instead — these assume you know roughly
what you are doing.
