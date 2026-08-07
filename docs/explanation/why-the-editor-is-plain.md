# Why the editor is plain

`atf edit` serves server-rendered HTML with about ten lines of CSS and no JavaScript. Every click is
a request; every view is a page. That is a decision, not a stage the project has not reached yet.

## What the plainness buys

ATF's own suite drives the editor in a real browser and claims on what is showing:

```gherkin
Scenario: the catalogue lists what the suite declares
  Given the screen "catalogue"
  Then the heading "Catalogue" is showing
  And the link "notebook" is showing
```

Those claims are made by role and accessible name. They work because the markup *is* the answer:
a heading is an `<h1>`, a link is an `<a>`, and the page is complete when the response ends. There is
no moment at which the page is present but not yet settled, so no scenario has to say how long to
wait, and no interface claim in this suite carries a timeout.

That is what the editor's shape is protecting. A view that assembles itself after the response
arrives puts a wait between every claim and the thing it claims about, and the suite that proves the
editor works becomes the suite most likely to go red for reasons that are not about the editor.

## What it costs

Real things, and they are worth naming:

- Every click is a full page load. Nothing is live; a run finishing does not update a view somebody
  is looking at.
- The graph is drawn as SVG with no zoom, no panning and no filtering. Past a few dozen resources it
  is a picture you scroll rather than one you explore.
- There is no dark mode, the layout is fixed-width, and nothing is reachable by keyboard beyond what
  the browser gives a document for free.

## What would change the decision

A view that a person operates rather than reads — a graph you drag, a composer that completes as you
type — is worth more than the plainness. The condition for building it is that the test hooks come
first: a settled signal the interface claims can wait on, so `Then the heading "Catalogue" is
showing` keeps meaning what it means today.

Until that exists, the editor gets better in place. The whole graph is drawn on the graph view
rather than only one resource's lineage, and each box is the same link its row in the table is.

## Where to go next

- **[One engine, two surfaces](one-engine-two-surfaces.md)** — why the editor performs nothing the
  command line cannot.
- **[The editor](../reference/the-editor.md)** — the views, and what each one is for.
- **[Test a web interface](../how-to/test-a-web-interface.md)** — the interface claims, and how a
  page is asked about by role and name.
