# Writing in the editor

*The same suite, the same graph and the same sentences, on a page — with the editor telling you as
you type what a line means and what would fit next.*

`atf edit` serves the page on `http://127.0.0.1:8765`.

`--env` picks the environment the page answers for, and every link carries it, so a pasted link
answers the same for whoever opens it. `--port` moves the page; `--mcp` serves the same operations
to an agent; `--write` writes the pages out as files.

## Five views

**Overview**
:   Runs the checks `atf plan` runs, and folds the two vocabularies: ATF's own sentences and the
    ones this suite teaches.

**Resources**
:   Everything the suite declares. A row expands to show what it is made of and what would be sent
    to create it, and can make one for real from there. A resource the environment owns says so.

**Graph**
:   What needs what. Each node carries its own lineage sentence, its run action, and what breaks
    if it does.

**Tests**
:   Every scenario and every pytest function, grouped under the file that holds it. Opening one
    opens its whole file in the editor; **write a new test** opens the same editor, blank.

**Activity**
:   Past runs, opened item by item, and exported in any format a system registers.

## Typing

Enter keeps the indent of the line you left, and goes one level deeper after `Feature:`,
`Scenario:`, `Example:` or `Phrase:`. Tab and Shift+Tab indent or dedent the line, or every line
the selection touches. Tab inside a quoted value steps past the closing quote.

On a pause in typing, the draft is checked the way `atf plan` checks the suite. A line with a
problem is marked, and the first problem shows under the editor. Problems never block a save.

## Completion

Completion offers only what fits where the caret is:

- A partial name narrows the resources offered to the ones that share it.
- Once a scenario has arranged something, the claims offered are the claims about that thing.
- An `And` completes as whatever keyword it continues.
- What an earlier scenario in the same file arranged is not offered in this one.
- A blank shows a value the suite actually declared, never an invented one.

## Hover

Hovering a sentence says which file answers it and the pattern it matched, as in
`vocabulary.py · the {kind} "{name}"`. A phrase call says it is a phrase this suite teaches. A
sentence nothing answers shows nothing.

## The gutter

A 💡 in the gutter is a suggestion, never a fault. Clicking it says what it noticed and offers one
action.

| Marker | What it noticed | The action |
|---|---|---|
| 💡 on a scenario with no `Then` | it makes no claim | **draft it from the real answer** runs the scenario and writes the claims into the file, the same way `atf run --accept` does |
| 💡 on a scenario | another scenario arranges and acts exactly like it | **open it** opens the existing one |
| ▾ 💡 on a run of steps | the steps spell out a phrase this suite already teaches | ▾ folds them to the phrase call for reading; **use it** replaces them with the phrase call in the editor, values filled in, ready to save |

## Running from the page

**▶ Try it** runs what is in the editor without saving it, and says whether it passed.
**▶ Run this scenario** runs the saved scenario as a real run, recorded like any other.
**Save** writes the file.
