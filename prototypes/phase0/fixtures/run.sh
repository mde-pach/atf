#!/usr/bin/env bash
# Two runs, because the ambiguous half is meant to stop the run before anything executes and would
# otherwise hide the half that passes.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

echo "=== must pass: every resolution arrange.md#asking-for-one promises ==="
uv run pytest test_python.py test_scenarios.py -v -p no:cacheprovider 2>&1 |
  grep -vE "PytestRemovedIn10|_fixturemanager|FixtureDef\(|^  /Users|^$"
ok=$?

echo
echo "=== must not start: two of a kind, and a kind with no factory ==="
uv run pytest ambiguous/ -p no:cacheprovider 2>&1 | sed -n '/^ERROR/,/^====/p'
uv run pytest ambiguous/ -p no:cacheprovider >/dev/null 2>&1
echo "exit code: $?  (4 = pytest USAGE_ERROR, which atf reports as 2 'the run never started')"
exit $ok
