# Sentences

Every sentence a suite can say, generated from the registrations. **Nothing here is hand-written**,
so it cannot go stale, and a team's own words appear the day they write them —
`atf edit` serves this page for the suite in front of you.

A sentence is `Given` (arrange), `When` (act) or `Then` (check). `And` and `But` continue whichever
came before them.


## Things

About a declared thing, and about whatever last happened.

| Sentence | What it does |
| --- | --- |
| `Given a {kind}` | `Given a list` — any one; resolution builds it when the scenario named none. |
| `Given a {kind} with {field} {value}` | `Given a list with slug "produce"` — give the resolver an argument; it resolves the rest. |
| `Given the {kind} "{name}"` | `Given the list "groceries"` — that one, and everything its lineage needs. |
| `Given the {kind} "{name}" with {field} {value}` | `Given the list "groceries" with slug "produce"` — that one, bent. |
| `Given with {field} {value}` | One more field of whatever the previous `Given` named. |
| `Given without {field}` | `And without a slug` — the field is not there at all. |
| `Then it does not mention {value}` | This appears nowhere in what came back. |
| `Then it mentions {value}` | `Then it mentions "groceries"` — anywhere in what came back. |
| `Then its {field} contains {value}` | That field holds this somewhere inside it. |
| `Then its {field} does not contain {value}` | That field does not hold this anywhere. |
| `Then its {field} is not {value}` | That field of what last happened is anything but this. |
| `Then its {field} is {value}` | A field of what last happened is this value, or this kind. |
| `Then the previous mentions {value}` | This appears somewhere in what happened before `it`. |
| `Then the previous {field} is {value}` | The rare scenario holding two results at once. One more and it should have been two scenarios. |
| `Then the {kind} "{name}" exists` | That thing is there in this environment, asked now. |
| `Then the {kind} "{name}" is gone` | That thing is not there any more. |
| `Then the {kind} "{name}" {field} contains {value}` | A field of that thing holds this somewhere inside it. |
| `Then the {kind} "{name}" {field} does not contain {value}` | A field of that thing does not hold this. |
| `Then the {kind} "{name}" {field} is not {value}` | A field of that thing is anything but this. |
| `Then the {kind} "{name}" {field} is {value}` | A field of that thing, read from the environment now, is this. |
| `Then there are {count:d} {kind}` | This environment holds exactly this many of that kind. |
| `When I list every {kind}` | `When I list every list` — everything of that kind the environment holds. |
| `When the {kind} "{name}" {field} becomes {value}` | `When the task "laundry" done becomes true`. |

## The shell system

Running something on this machine.

| Sentence | What it does |
| --- | --- |
| `Then the command failed` | It exited with anything but zero. |
| `Then the command succeeded` | It exited zero. |
| `When I run "{command}"` | `When I run "todo show primary@example.com"`. What it produced becomes `it`. |

## The browser system

Using an interface, by role and accessible name.

| Sentence | What it does |
| --- | --- |
| `Then the words "{words}" are showing` | This text is somewhere on the page. |
| `Then the {role} "{name}" is disabled` | That control cannot be used. |
| `Then the {role} "{name}" is enabled` | That control can be used. |
| `Then the {role} "{name}" is not showing` | That control is not on the page. |
| `Then the {role} "{name}" is showing` | That control is on the page. |
| `Then the {role} "{name}" reads "{text}"` | That control's own text is exactly this. |
| `When I choose "{option}" from the {role} "{name}"` | Choose that option from that control. |
| `When I click the {role} "{name}"` | Click it. |
| `When I type "{text}" into the {role} "{name}"` | Put this text into that field. |

## The contract

What every system is held to. Run it with `atf run --contract`.

| Sentence | What it does |
| --- | --- |
| `Then every system held it` |  |
| `When I put every kind ATF may make through the contract` | Create, read back, update, delete, delete again — for every kind this environment owns. |

## Values

Quoting carries the type, and nothing else does.

| Written | What it is |
| --- | --- |
| `"0"` | the text |
| `0` | the number |
| `true`, `false` | the boolean |
| `nothing` | not there at all |

Text between quotes reads its escapes: `\n`, `\t`, `\\`, `\"`.

## Kinds

Where the value is not the point, say what sort of thing must be there.

- `any date`
- `any datetime`
- `any number`
- `any text`
- `any text like`
- `any time`
- `any uuid`
- `any whole number`
- `missing`
- `set`

A team registers its own with `@kind("iban")`. **ATF ships none that know a domain** — an `iban` is
your vocabulary, and a framework that learned it would spend its life maintaining a validation
library nobody wanted from it.
