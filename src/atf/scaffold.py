"""`atf init` — a manifest, an empty resources module, an empty specs directory, and no fourth file."""

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
    # One block per driver. `filesystem` is here because the example in resources.py uses it;
    # `command` is what `When I run "..."` and the `shell` fixture reach.
    filesystem: {{ root: . }}
    command:    {{ prefix: "" }}
"""

RESOURCES = '''\
"""What must exist before a test runs.

Declare a resource as a class, and one particular resource as a module-level variable:

    from atf import file

    @file(unique_by="path")
    class Config:
        path: str
        text: str

    settings = Config(path="config.toml", text="")

What a resource needs goes in `depends_on`, never in an annotation — a dependency does not always
have a field to live in.
"""
'''

def init(root: Path, *, env: str = "local", force: bool = False) -> list[Path]:
    """Write the manifest, the resources module and the specs directory."""
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

    specs = root / "specs"
    specs.mkdir(exist_ok=True)
    written.append(specs)
    return written
