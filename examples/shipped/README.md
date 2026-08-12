# The systems ATF ships

`filesystem` and `shell` come with ATF, so this suite registers **nothing**. It imports its
decorators from `atf` itself.

It exists to show two things the todo suite cannot: a system ATF ships, and teardown where the order
is load-bearing.

## How long things live, and why the order matters

Nothing here types a span except `Sleeper`, which ATF cannot see the end of. `scratch` is a
directory and `today` is a file inside it, and the edge is the `needs()` at `Draft.workspace`.

Teardown is **always reverse lineage**, so the file goes before the directory. This is the case
where the wrong order fails loudly rather than quietly: a directory that still has something in it
does not remove.

```bash
cd examples/shipped
uv run atf plan
uv run atf run
```
