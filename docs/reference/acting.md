# Acting reference

One of four pages on the pytest surface `atf.spec.plugin` adds: this one covers doing something to
a resource once [provisioning](provisioning.md) has made it exist. See also
[assertions](assertions.md) and [fixtures](fixtures.md).

## Acting on a system {#acting}

```gherkin
When I <action> the <type> "<name>"
When I list every <type>
When I run "<command line>"
```

An adapter offers *mechanical* verbs; the catalog names a *domain* action in terms of them; the
spec says the domain action. Nothing in between needs code.

```yaml
task:
  system: rest
  path: /tasks
  actions:
    complete: { patch: { done: true } }
    reopen:   { patch: { done: false } }
```

```gherkin
Given the task "laundry"
When I complete the task "laundry"
Then the task "laundry" is done
```

The action's body is adapter configuration, exactly as `path` is: ATF validates its shape and reads
nothing into it. See [`actions:`](catalog.md#actions) for what the built-in `rest` adapter
understands, and [`act`](adapter-spi.md#act) for writing your own.

**`delete` is ATF's own** and needs no declaration — every adapter has one, and a backend without
deletion no-ops it through `NoopDelete`, so the claim after it reads the resource back and finds
out. A type may not declare an action by that name.

**`I list every <type>`** reads back everything of a type the environment holds, onto
[`result`](assertions.md#slots) — which is [`browse`](adapter-spi.md#browse), the optional half of
the SPI. A type whose listing is scoped to a parent says so rather than guessing at one, and an
adapter that cannot list says that.

**`I run "<command line>"`** runs a command line through the [`command`](manifest.md#command-settings)
system this environment configures, and puts what came back on `result` — the exit code, both
streams, and `ok`. The line is written the way a person writes one: `atf seed local`, split the way
a shell splits it.

An action puts what it produced on `result`, so a scenario can claim something about the response
as well as about the resource. A system that says nothing useful leaves the record the action was
performed on, so there is always something there.

## Acting on an interface {#ui}

A page is a resource like any other, and the controls on it are named **inline**, by **role** and
**accessible name** — never in the catalog, and never with a selector.

```yaml
# The only thing a catalog says about a page is where it is.
page:
  system: html          # what the server sent — no browser
  mode: data
  natural_key: at
  id_field: at

screen:
  system: browser       # the same page, after it has run
  mode: data
  natural_key: at
  id_field: at
```

**Two systems, one vocabulary.** [`html`](manifest.md#html-settings) reads the page a server sent
and [`browser`](manifest.md#browser-settings) reads the page a browser ran. They answer the same
claims, so which one a suite configures decides what a claim *costs*, never what it says — and most
of what there is to say about a server-rendered interface is true of the response, which needs
nothing installed.

Where they differ is honest and narrow. Only a browser can see a stylesheet apply, a fragment swap
in or a combobox open — and only a browser can be *acted* on, because reading a response can never
click anything. The acting steps say so where there is no browser rather than quietly doing less.

```gherkin
Given the screen "compose"
When I click the combobox "what is this about…"
And I type "groceries" into the combobox "what is this about…"
Then the option "groceries" is showing
And the option "every owner" is not showing
```

| Step | What it does |
|---|---|
| `When I click the <role> "<name>"` | clicks it |
| `When I type "<text>" into the <role> "<name>"` | replaces its contents |
| `When I choose the <role> "<name>"` | picks an option |
| `Then the <role> "<name>" is showing` | it is there and visible |
| `Then the <role> "<name>" is not showing` | it is not — *hidden* counts, which is what a person means |
| `Then the <role> "<name>" reads "<text>"` | compares what it says |
| `Then the <role> "<name>" is disabled` | it is there and refuses to be used |
| `Then the <role> "<name>" is enabled` | it is there and usable |
| `Then the words "<text>" are showing` | prose, which has no accessible name |
| `Then the words "<text>" are not showing` | it does not |

**Why role and name.** They are what a screen reader announces, so a scenario written in them is a
scenario about what a person can perceive — and they are what an accessibility tree exposes, so they
are also the most stable thing to automate against. A selector describes today's markup; a role and
a name describe the thing. A catalog node per control would be a Page Object with a YAML file for a
class, and would put the shape of a template into the file that describes the domain.

**Prose is the exception.** ARIA computes an accessible name for things you can *do* something to,
and a paragraph is not one — so what a page *says* is claimed with `the words "…"`, which is still
what a reader reads and still not a selector.

**Disabled is not the same as absent**, and the difference is worth a claim of its own: an
interface that hides what you may not do teaches nothing, and one that offers it and then refuses
is worse. Disabled, with the reason beside it, is the third option.

**A claim waits, where waiting means anything.** In a browser, `is showing` and `the words …` wait
for what they name to arrive, because an interface that swaps a fragment in after a request has
settled is asynchronous, not broken. A response is finished when it arrives, so `html` answers at
once.

**A failure says what is there.** Naming a control that is not on the page lists the ones that are,
with that role, so a wrong name is one line to fix rather than a hunt.

**What `html` reads is a documented subset of ARIA**: the implicit role HTML gives an element, with
an explicit `role=` winning, and the accessible name computed in the specification's order —
`aria-labelledby`, `aria-label`, what HTML names it natively (a label, an `alt`, a caption, what is
written on it), then `title`. It cannot see layout or a stylesheet, so only an inline
`display: none`, a `hidden` or an `aria-hidden` hides something from it. A page whose naming it
cannot follow is a page to look at with `browser`.

Playwright is an optional dependency (`uv sync --group browser`). Without it that adapter reports
itself [unavailable](adapter-spi.md#unavailable) and scenarios tagged as needing it
[skip with the reason](manifest.md#requires) — while everything `html` can answer still runs.

## Where to go next

- [Provisioning reference](provisioning.md) — declaring what a scenario needs before it acts.
- [Assertions reference](assertions.md) — claiming something about what an action produced.
- [Catalog reference](catalog.md#actions) — declaring an action on a type.
- [Adapter SPI reference](adapter-spi.md#act) — writing `act` for an adapter of your own.
