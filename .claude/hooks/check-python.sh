#!/usr/bin/env bash
# Runs after a Python file in this repo is edited: ruff (fixing what it can), then ty.
#
# Exit 2 is what makes this useful — Claude Code feeds the output back to the model as a blocking
# error, so a lint or type failure is seen and fixed in the same turn instead of surfacing later.
# Anything outside this repo, or not Python, exits 0 without running a thing.
set -uo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
file="$(jq -r '.tool_response.filePath // .tool_input.file_path // empty')"

[[ "$file" == *.py ]] || exit 0
[[ "$file" == "$repo"/* ]] || exit 0
cd "$repo" || exit 0

# Repo-wide rather than per-file: import ordering and unused imports are only decidable across the
# whole tree, and both tools take about a second on this codebase.
if ! out="$(uv run ruff check --fix 2>&1)"; then
  printf 'ruff:\n%s\n' "$out"
  exit 2
fi
if ! out="$(uv run ty check 2>&1)"; then
  printf 'ty:\n%s\n' "$out"
  exit 2
fi
exit 0
