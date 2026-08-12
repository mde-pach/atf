"""Reading a value out of a sentence, where quoting carries the type and nothing else does."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import kinds
from .model import compare

MISSING = compare.MISSING

#: What a scenario writes for a value that is not there at all.
NOTHING = "nothing"

#: What a backslash means inside quotes. Every language a QA author has already used reads these,
#: and reading them is the same promise as reading the quotes: text says what it looks like.
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


def unescape(text: str) -> str:
    """Text between quotes, with its escapes read. An unknown escape is left exactly as written."""
    if "\\" not in text:
        return text
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            following = text[index + 1]
            if following in ESCAPES:
                out.append(ESCAPES[following])
                index += 2
                continue
        out.append(char)
        index += 1
    return "".join(out)


class LiteralError(Exception):
    """Raised when a written value cannot be read as one. Always a message about the sentence."""


@dataclass(frozen=True)
class Written:
    """One value as a scenario wrote it, read into what it means."""

    #: The value, where it is one. `None` both for `nothing` and where a kind was said instead.
    value: Any = None
    #: The kind, where one was said. Exclusive with a value.
    kind: str = ""
    #: What the author typed, for a message.
    text: str = ""

    @property
    def says_a_kind(self) -> bool:
        return bool(self.kind)


def read(written: str) -> Written:
    """Read a written value, or say what it could have been.

    Five things a value may be: text in quotes, a number, `true`/`false`, `nothing`, or a kind.
    A bare word that is none of them raises, naming all five.
    """
    text = written.strip()
    if not text:
        raise LiteralError("nothing was written where a value goes")

    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return Written(value=unescape(text[1:-1]), text=text)

    lowered = text.lower()
    if lowered == "true":
        return Written(value=True, text=text)
    if lowered == "false":
        return Written(value=False, text=text)
    if lowered == NOTHING:
        return Written(value=None, text=text)

    number = _number(text)
    if number is not None:
        return Written(value=number, text=text)

    if kinds.says_a_kind(text):
        return Written(kind=text, text=text)

    raise LiteralError(
        f"{text!r} is not a value.\n"
        f"  A value is text in quotes, a number, true, false, {NOTHING}, or a kind "
        f"({', '.join(kinds.offered())}).\n"
        f'  Did you mean "{text}"?'
    )


def _number(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def describe(value: Any) -> str:
    """A value as a message should name it: what it was, and what kind of thing that is."""
    return "not there" if value is MISSING else compare.describe(value)


def is_(actual: Any, written: str) -> tuple[bool, str]:
    """Whether a value is what a sentence said it is, and what to say when it is not.

    Types are compared, not coerced. A number against quoted text does not hold, and says so.
    """
    said = read(written)
    if said.says_a_kind:
        return kinds.holds(actual, said.kind, present=actual is not MISSING)

    if actual is MISSING:
        return False, f"the field is not there at all, and this wants {said.text}"

    if _same(actual, said.value):
        return True, ""
    return False, _mismatch(actual, said)


def _same(actual: Any, wanted: Any) -> bool:
    """Equal, and of the same sort.

    One exception, and it is about systems and not about types: a system with no boolean of its own
    stores one as `0` or `1`, so a declared `true` read back from SQLite is still `true`. Text is
    never a number, which is the comparison this module exists to keep honest.
    """
    if isinstance(wanted, bool):
        if isinstance(actual, bool):
            return actual == wanted
        return actual in (1, 0) and bool(actual) == wanted
    if isinstance(actual, bool):
        return False
    if wanted is None:
        return actual is None
    if isinstance(wanted, int | float) and isinstance(actual, int | float):
        return float(actual) == float(wanted)
    if isinstance(wanted, str) and isinstance(actual, str):
        return actual == wanted or compare.same_instant(actual, wanted)
    return False


def _mismatch(actual: Any, said: Written) -> str:
    """Why it did not hold — and, where the types are what differ, the two words that fix it."""
    if isinstance(said.value, str) and not isinstance(actual, str) and str(actual) == said.value:
        return (
            f"it is {describe(actual)}, and this compared it with the text {said.text} — "
            f"drop the quotes"
        )
    if not isinstance(said.value, str) and isinstance(actual, str) and actual == str(said.value):
        return (
            f"it is {describe(actual)}, and this compared it with {said.text} — "
            f'write it as "{said.value}"'
        )
    return f"it is {describe(actual)}, and this wants {said.text}"


def contains(actual: Any, written: str) -> tuple[bool, str]:
    """Whether a value holds what a sentence said, with the same typing rule."""
    said = read(written)
    if said.says_a_kind:
        raise LiteralError(f"`contains` takes a value, and {said.text} is a kind")
    if actual is MISSING:
        return False, f"the field is not there at all, and this wants it to hold {said.text}"
    wanted = said.value
    if isinstance(actual, str):
        return (str(wanted) in actual, f"it is {describe(actual)}, which does not hold {said.text}")
    if isinstance(actual, list | tuple):
        return (
            any(_same(item, wanted) for item in actual),
            f"it holds {len(actual)} things, and {said.text} is not one of them",
        )
    if isinstance(actual, dict):
        raise LiteralError(
            f"{describe(actual)} — a record holds keys and values both, so `contains` cannot say "
            f"which was meant. Name the field inside it instead."
        )
    return (str(wanted) in str(actual), f"it is {describe(actual)}, which does not hold {said.text}")


def field_name(written: str) -> str:
    """The field a sentence names, whether it was quoted or written as prose.

    `its exit code` and `its "exit_code"` reach the same field. Prose is the readable form and the
    quotes are there for a field whose name is not English — a header, a column with a dot in it.
    """
    text = written.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return "_".join(text.split())
