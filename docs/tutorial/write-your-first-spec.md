# Write your first spec

In this tutorial we will build a small test suite from scratch. By the end you will have written a
scenario in plain English, watched ATF create the data that scenario needs, and seen it pass.

You need Python 3.11 or newer and about fifteen minutes. You do not need a server, a database, or
any prior knowledge of ATF.

## Step 1: Install ATF

Make a directory to work in, and install ATF into it:

```sh
cd ~
mkdir atf-tutorial && cd atf-tutorial
python3 -m venv .venv
source .venv/bin/activate
pip install git+https://github.com/mde-pach/atf
```

Check that it worked:

```sh
atf --help
```

You will see a list of commands:

```
usage: atf [-h] {init,serve,seed,status,run} ...
```

## Step 2: Create the suite

ATF can write a starter suite for you:

```sh
atf init todo-suite
cd todo-suite
```

You will see:

```
Scaffolded an ATF suite in /path/to/atf-tutorial/todo-suite:
  atf.yaml
  catalog/resources.yaml
  catalog/accounts.yaml
  catalog/projects.yaml
  adapters.py
  conftest.py
  specs/conftest.py
  specs/api.py
  specs/features/accounts.feature
  specs/steps/test_accounts.py
  .gitignore
  README.md

Next: edit atf.yaml + catalog/, then `atf status dev`.
```

Let's look at the two files that matter most. First the catalog — this is the data your tests need:

```sh
cat catalog/accounts.yaml
```

```yaml
primary:
  resource: account
  represents: The account the rest of the catalog hangs off.
  body:
    email: primary@example.com
```

That is a **resource**: a thing that must exist before a test can run. Notice there is no code in
it — just a name, a type, and the fields it is made of.

Now the spec:

```sh
cat specs/features/accounts.feature
```

```gherkin
Feature: Accounts
  An account owns the projects created under it.

  Scenario: A project belongs to its account
    Given the account "primary"
    And the project "alpha"
    When I list the projects of the account
    Then the project "alpha" is listed
```

Notice the first line: `Given the account "primary"`. That names the resource you just looked at.
You did not write that step — ATF provides it for every resource in your catalog.

## Step 3: Give the suite something to test

Your suite needs a service to talk to. We will use a tiny fake one so the tutorial runs anywhere.

Create a file called `todo_api.py` next to `atf.yaml`, and paste this in:

```python
"""A tiny in-memory API, standing in for a real service."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DATA = {"accounts": [], "projects": []}
COUNTER = [0]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        collection = url.path.strip("/")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        records = [
            r for r in DATA.get(collection, [])
            if all(str(r.get(k)) == v for k, v in query.items())
        ]
        self.reply(200, records)

    def do_POST(self):
        collection = self.path.strip("/")
        size = int(self.headers.get("Content-Length") or 0)
        record = json.loads(self.rfile.read(size)) if size else {}
        COUNTER[0] += 1
        record["id"] = f"{collection[:-1]}-{COUNTER[0]}"
        DATA.setdefault(collection, []).append(record)
        self.reply(201, record)

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


print("todo API on http://127.0.0.1:8400")
ThreadingHTTPServer(("127.0.0.1", 8400), Handler).serve_forever()
```

It keeps accounts and projects in memory and serves `/accounts` and `/projects` — nothing more.

Open a **second terminal**, go to the same directory, and start it:

```sh
cd ~/atf-tutorial/todo-suite
source ../.venv/bin/activate
python todo_api.py
```

You will see:

```
todo API on http://127.0.0.1:8400
```

Leave it running — it stores everything in memory, so stopping it forgets every resource.
Go back to your first terminal for everything that follows.

## Step 4: Point the suite at it

Open `atf.yaml`. Find the two lines that read:

```yaml
        base_url: https://dev.example.com
```

Change **both** of them to:

```yaml
        base_url: http://127.0.0.1:8400
```

One is under `adapters:` (how ATF creates data) and one is under `clients:` (how your test talks to
the service) — see [About the model](../explanation/the-model.md) for why they are separate.

The manifest also asks for a value called `ATF_ACTOR`. ATF never stores secrets in files — it reads
them from the environment. Set it:

```sh
export ATF_ACTOR=tutorial
```

## Step 5: See what does not exist yet

Ask ATF what is in the environment:

```sh
atf status dev
```

```
  accounts.primary  absent
  projects.alpha    absent

0/2 present in dev
```

Both resources are **absent** — the API is running but empty. Nothing has been created.

## Step 6: Run your suite

```sh
atf run
```

```
  [ passed] specs/steps/test_accounts.py::test_a_project_belongs_to_its_account  0.02s

1 passed, 0 failed, 0 skipped, 0 errored in dev
```

You have just run your first test, and it passed. The test covers the scenario you read in
step 2 — ATF calls that scenario a **spec**, and the collected pytest item a **test**.

Now look again:

```sh
atf status dev
```

```
  accounts.primary  present
  projects.alpha    present

2/2 present in dev
```

Notice what happened. You never told the test to create an account. The scenario said
`Given the account "primary"`, and ATF created the account, then created the project underneath it,
then ran the test. That is the whole idea.

Run it once more:

```sh
atf run
```

It passes again — and `atf status dev` still shows exactly two resources. ATF found the ones it made
last time instead of making duplicates. Your suite is safe to re-run.

## Step 7: Add a resource of your own

Let's add a second account. Open `catalog/accounts.yaml` and add these lines at the end:

```yaml
secondary:
  resource: account
  represents: A second account, to prove one account's projects stay its own.
  body:
    email: secondary@example.com
```

That is all it takes to add a resource — no code, no registration.

Check that ATF sees it:

```sh
atf status dev
```

```
  accounts.primary    present
  accounts.secondary  absent
  projects.alpha      present

2/3 present in dev
```

Your new account is there, and it is absent.

## Step 8: Write a scenario that uses it

Open `specs/features/accounts.feature` and add this scenario at the end of the file, indented the
same as the one above it:

```gherkin
  Scenario: A new account has no projects
    Given the account "secondary"
    When I list the projects of the account
    Then no projects are listed
```

The `Given` and `When` lines already work. The `Then` line is new, so let's write it. Open
`specs/steps/test_accounts.py` and add this at the end:

```python
@then("no projects are listed")
def _(context):
    assert context.result == []
```

Run the suite:

```sh
atf run
```

```
  [ passed] specs/steps/test_accounts.py::test_a_new_account_has_no_projects  0.01s
  [ passed] specs/steps/test_accounts.py::test_a_project_belongs_to_its_account  0.02s

2 passed, 0 failed, 0 skipped, 0 errored in dev
```

Two tests, both green — one per scenario. Notice how little you wrote: one YAML block, three lines of Gherkin, and one
assertion. The account got created for you.

## Step 9: See the whole suite at once

ATF ships a web cockpit. Start it:

```sh
atf serve
```

```
ATF cockpit — http://127.0.0.1:8000
  This cockpit performs mutating actions against real environments and has NO authentication.
  It binds 127.0.0.1 by design; for shared access put it behind an authenticating reverse proxy.
  Mutable environments: dev
```

Open <http://127.0.0.1:8000> in a browser. The **Overview** page shows three meters — how much of
your catalog exists, how much of it your specs cover, and whether your tests pass.

Click **Catalog** in the sidebar, then click `projects.alpha`. You will see a diagram with
`accounts.primary` to its left: the dependency ATF walked for you in step 6.

Click **Specs**, then **A project belongs to its account**. The scenario is there in plain English,
with the resource names linked to the catalog entries you wrote.

Press `Ctrl-C` in the terminal when you are done looking.

## What you have done

You built a working test suite. Along the way you:

- declared a resource as YAML, with no code;
- wrote a scenario in plain English that named that resource;
- watched ATF create the resource and its dependency before the test ran;
- re-ran the suite and saw it reuse what already existed;
- added a second resource and a second scenario, and saw both picked up automatically.

## Where to go next

- To make ATF talk to your own service, read [How to add an adapter](../how-to/add-an-adapter.md).
- To add more resources to a catalog, read [How to add a resource](../how-to/add-a-resource.md).
- To understand why the catalog is data rather than code, read
  [About declarative catalogs](../explanation/why-declarative-catalogs.md).
