# The systems ATF ships

`filesystem` and `process` come with ATF, so this suite has **no `extensions:` key and no adapter of
its own**. It imports its decorators from `atf` itself.

It exists to show two things the todo suite cannot: a system ATF ships, and teardown where the order
is load-bearing.

## Scope, and why the order matters

`scratch` is a directory that lives for the run. `today` is a file inside it that lives for one
test, and says so with `depends_on=[scratch]`.

Teardown is **always reverse lineage**, so the file goes before the directory. This is the case
where the wrong order fails loudly rather than quietly: a directory that still has something in it
does not remove.

```bash
cd examples/shipped
uv run atf make local
find tmp
```

```text
scratch  present  created  changes: path
today    present  created  changes: path, text
waiter   present  created  changes: command

tmp
tmp/scratch
tmp/scratch/draft.txt
```

Nothing in the suite says "the directory before the file in it". The graph does.

## A process is recognised, not remembered

```bash
uv run python -c "
from atf import load_suite, build_ground, provision, teardown, status
suite = load_suite(); ground = build_ground(suite, 'local')
waiter = [suite.resource('waiter')]
print('before:', [str(o.state) for o in status(ground, waiter)])
print('made  :', [str(o.did) for o in provision(ground, waiter)])
print('again :', [str(o.did) for o in provision(ground, waiter)])
print('down  :', [str(o.state) for o in teardown(ground, waiter)])
"
```

```text
before: ['absent']
made  : ['created']
again : ['unchanged']
down  : ['absent']
```

The second pass recognises what the first one started rather than starting a second. **This is the
one system where `persistent` cannot outlive the process that made it** — recognition here asks
whether a handle this adapter started is still alive, so a server left running by a previous run is
not recognised by the next one.

## An instance is not named after its kind

`workspace = Workspace(...)` is refused at load, because `workspace` is also the name a test uses to
ask for *any* `Workspace`. The instances here are called `scratch`, `today` and `waiter`.
