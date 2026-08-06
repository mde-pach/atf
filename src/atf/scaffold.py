"""`atf init` — three files and a directory, and nothing else.

It scaffolds **ATF itself**, not a project: a manifest with one environment, an empty `resources.py`,
an empty `specs/`. It generates no tests, no resources and no example code, because a suite that
starts with somebody else's example starts with somebody else's domain.

The manifest it writes deliberately does **not** carry `from __future__ import annotations` into
`resources.py`. A resources module states its shape in annotations, and under that import they are
strings rather than types.
"""

from __future__ import annotations

from pathlib import Path

MANIFEST = """\
resources: [./resources.py]
specs: ./specs
default_env: {env}

environments:
  {env}:
    # ATF may change this environment. It is false unless stated, so the dangerous setting is
    # never the one nobody had to type.
    mutable: true
    command: {{ prefix: "" }}
"""

RESOURCES = '''\
"""What must exist before a test runs.

Declare a resource as a class, and one particular resource as a module-level variable:

    from atf import filesystem

    @filesystem(path="config.toml", unique_by="path")
    class Config:
        text: str

    settings = Config(text="")

What a resource needs goes in `depends_on`, never in an annotation — a dependency does not always
have a field to live in.

Do not add `from __future__ import annotations` to this file. The annotations here are the shape,
and under that import they are strings rather than types.
"""
'''

CONFTEST = '''\
"""Enable ATF's pytest plugin for this suite."""

pytest_plugins = ["atf.plugin"]
'''


def init(root: Path, *, env: str = "local", force: bool = False) -> list[Path]:
    """Write the manifest, the resources module, the conftest and the specs directory."""
    manifest = root / "atf.yaml"
    if manifest.exists() and not force:
        raise FileExistsError(f"{manifest} already exists; pass --force to overwrite it")

    written: list[Path] = []
    manifest.write_text(MANIFEST.format(env=env), encoding="utf-8")
    written.append(manifest)

    resources = root / "resources.py"
    if not resources.exists() or force:
        resources.write_text(RESOURCES, encoding="utf-8")
        written.append(resources)

    conftest = root / "conftest.py"
    if not conftest.exists() or force:
        conftest.write_text(CONFTEST, encoding="utf-8")
        written.append(conftest)

    specs = root / "specs"
    specs.mkdir(exist_ok=True)
    written.append(specs)
    return written
