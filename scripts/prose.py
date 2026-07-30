"""Check what the docstrings and comments in `src/atf` say, for the two rules ruff cannot express.

A docstring or comment names what a scope **is**, or states what a function **does** — its contract
and its edge cases. It does not argue why the code is this way, name what was considered instead,
narrate what it used to be, or cite prior art. That belongs in a commit message, where it is read by
someone asking why rather than by everyone asking what.

Run beside `ruff check`. Exits 1 with one line per violation, and 0 with nothing to say.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "atf"

# A module docstring says what the module is. Two lines is enough for that, and the second is there
# for the one contract that constrains every caller — "never touches the network".
MODULE_DOC_LINES = 2

# Phrases that always mean rationale. Blunt on purpose: the author rewords one line, and the
# alternative is a rule nobody applies.
RATIONALE = (
    "because",
    "rather than",
    "instead of",
    "the alternative",
    "used to",
    "would have",
    "deliberately",
    "on purpose",
    "which is why",
    "the reason",
)

_WORDS = re.compile("|".join(re.escape(phrase) for phrase in RATIONALE))


def violations(path: Path) -> list[str]:
    """Every line of this file that says why. Empty when it only says what."""
    text = path.read_text(encoding="utf-8")
    where = path.relative_to(SOURCE.parent.parent)
    found = [f"{where}:1: module docstring is longer than {MODULE_DOC_LINES} lines" for _ in _too_long(text)]
    found += [f"{where}:{line}: {kind} says why: {said!r}" for line, kind, said in _rationale(text)]
    return found


def _too_long(text: str) -> list[str]:
    tree = ast.parse(text)
    doc = ast.get_docstring(tree)
    return [doc] if doc and len(doc.strip().splitlines()) > MODULE_DOC_LINES else []


def _rationale(text: str) -> list[tuple[int, str, str]]:
    """Docstring and comment lines carrying one of the phrases, with where and what."""
    said: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        doc = ast.get_docstring(node)
        if doc is None:
            continue
        start = 1 if isinstance(node, ast.Module) else node.body[0].lineno
        said += [(start + offset, "docstring", line.strip()) for offset, line in _carrying(doc)]

    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT and _WORDS.search(token.string.lower()):
            said.append((token.start[0], "comment", token.string.strip()))
    return sorted(said)


def _carrying(doc: str) -> list[tuple[int, str]]:
    return [(offset, line) for offset, line in enumerate(doc.splitlines()) if _WORDS.search(line.lower())]


def main() -> int:
    found = [problem for path in sorted(SOURCE.rglob("*.py")) for problem in violations(path)]
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} lines say why rather than what. A decision that needs recording is a commit message.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
