"""Generate the sentence reference from the registrations, so nobody maintains one.

Most of a reference stops being written once a system registers its own sentences. It cannot go
stale, it covers a team's own words the day they write them, and the page a team reads is *their*
vocabulary rather than ATF's plus a note about extending.

Run in CI beside the prose check. Writing it into the tree rather than generating at build time is
deliberate: a diff on this file is how a change to the language becomes visible in review.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import atf  # noqa: E402  # the registrations are the source
from atf import (  # noqa: E402, F401
    conformance,  # imported so the contract's own words are registered
    kinds,
    steps,
    vocabulary,  # imported so the sentences about a thing are registered
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "reference" / "sentences.md"

#: Which module a sentence is registered in, as the heading a reader looks under. A system's words
#: belong to that system: they are met the first time you use it, and not before.
WHERE = {
    "atf.vocabulary": ("Things", "About a declared thing, and about whatever last happened."),
    "atf.systems.command": ("The shell system", "Running something on this machine."),
    "atf.systems.browser": ("The browser system", "Using an interface, by role and accessible name."),
    "atf.conformance": ("The contract", "What every system is held to. Run it with `atf run --contract`."),
}

HEAD = """\
# Sentences

Every sentence a suite can say, generated from the registrations. **Nothing here is hand-written**,
so it cannot go stale, and a team's own words appear the day they write them —
`atf edit` serves this page for the suite in front of you.

A sentence is `Given` (arrange), `When` (act) or `Then` (check). `And` and `But` continue whichever
came before them.
"""

VALUES = """\
## Values

Quoting carries the type, and nothing else does.

| Written | What it is |
| --- | --- |
| `"0"` | the text |
| `0` | the number |
| `true`, `false` | the boolean |
| `nothing` | not there at all |

Text between quotes reads its escapes: `\\n`, `\\t`, `\\\\`, `\\"`.

## Kinds

Where the value is not the point, say what sort of thing must be there.

{kinds}

A team registers its own with `@kind("iban")`. **ATF ships none that know a domain** — an `iban` is
your vocabulary, and a framework that learned it would spend its life maintaining a validation
library nobody wanted from it.
"""


def band(keyword: str) -> str:
    return {"given": "Given", "when": "When", "then": "Then"}[keyword]


def rows(module: str) -> list[str]:
    """One table per module, in the order a reader meets the words."""
    mine = [one for one in steps.REGISTRY if one.module == module]
    if not mine:
        return []
    out = ["", "| Sentence | What it does |", "| --- | --- |"]
    for one in sorted(mine, key=lambda step: (step.keyword, step.pattern)):
        said = (one.function.__doc__ or "").strip().splitlines()
        first = said[0] if said else ""
        out.append(f"| `{band(one.keyword)} {one.pattern}` | {first} |")
    return out


def write() -> int:
    out = [HEAD]
    seen: set[str] = set()
    for module, (title, why) in WHERE.items():
        table = rows(module)
        if not table:
            continue
        seen.add(module)
        out += [f"\n## {title}\n", why, *table]

    rest = sorted({one.module for one in steps.REGISTRY} - seen)
    for module in rest:
        out += [f"\n## {module}\n", *rows(module)]

    said = "\n".join(f"- `{one}`" for one in kinds.offered())
    out.append("\n" + VALUES.format(kinds=said))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    written = "\n".join(out).rstrip() + "\n"
    if OUT.exists() and OUT.read_text(encoding="utf-8") == written:
        return 0
    OUT.write_text(written, encoding="utf-8")
    return 0


if __name__ == "__main__":
    assert atf.__version__  # the package is what registered everything above
    sys.exit(write())
