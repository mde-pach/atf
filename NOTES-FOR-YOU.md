# Things needing your call

Written as I went, so they are not lost in a transcript. **Nothing here is blocking.** Each has a
defensible answer in place; each is somewhere I made a judgement you might make differently.

## 1. The composer's offers are mine, not the specification's

`the-editor.md#composer` says a claim is offered "only once something above it has produced what the
claim reads", and gives two examples. It does not enumerate the rules. What I implemented:

- a `Given` for every declared resource, and for every kind that has a factory;
- a `When` for an action **only when the kind declares it and its adapter implements `act`**, and
  for `list every` only when the adapter implements `browse`;
- a `Then` about a resource only once a `Given` above it named that resource, and about a slot only
  once a `When` above it produced one.

The third is the one to look at. I key "what has been arranged" off resource *names* appearing in
the sentences above, which is a text match rather than a compile. A scenario that arranges something
through a phrase gets the right answer only because phrases expand first.

## 2. `atf docs` output shape

The specification gives one console line and no page layout. I chose: one markdown page per feature,
`##` per scenario with the verdict in a code span beneath it, tags as code spans, one bullet per
sentence carrying the keyword the author typed. Nothing about that is derived from the spec.

## 3. The five markers are the documented ones; `#regex` is not registered

`assert.md` lists `#uuid #datetime #date #absent #present #int #str #bool` as built in, and the old
`compare.py` also had `#notnull`, `#null`, `#decimal`, `#number`, `#time` and `#regex`. I registered
only the documented eight. The machinery for a marker taking an argument is there and unused.

## 4. `unique_by` composite keys cannot name a parent

You chose b1. The cost, recorded again here because it is the one that will be met in the field: a
resource unique only *within* its parent — `[owner_id, slug]`, which the old fixtures used — has to
carry a field of its own to say so. There is no way to write it as `("owner", "slug")`.

## 5. Global flags are accepted before *and* after the subcommand

`atf --config X run` and `atf run --config X` both work. The specification says global flags are
"accepted by every subcommand" and its own examples use both positions, so I supported both. The
cost is a small shared decorator and one merge step; the alternative was to break either a manifest
`command:` prefix or the documented `atf make readonly --json`.

## 6. `atf edit --mcp` pins `mcp>=2`

The SDK renamed `FastMCP` to `MCPServer`. I wrote a fallback for both, then deleted it: the optional
group already pins `mcp>=2`, so the older name is dead code against our own constraint. If you want
to support pre-2 SDKs, that fallback needs to come back and `ty` will need an exclusion.

## 7. What is still not built

- **The editor's graph view draws nothing.** It lists nodes and their edges as a table.
  `the-editor.md#graph` says small lineage is stated in words and past that "the view draws it". The
  words are there (`core.in_words`); the drawing is not.
- **`atf docs` has no index page.** One file per feature, no contents.
- **Flakiness is computed and never surfaced** outside `atf history --json`. `the-record.md` wants it
  beside a verdict.
- **`--report` supports only `ctrf`.** That is per the specification — any other format is one a team
  registers — but nothing in the suite registers a second one, so the registry is unexercised.
