"""ATF — Another Test Framework.

A test framework whose bet is that **preconditions are declared as data rather than executed as
setup code**. Declaring them buys a graph ATF holds: what depends on what, and which tests need
which things.

```python
from adapters.sqlite import sqlite       # your suite's adapter, not ATF's


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug", depends_on=[Owner])
class TodoList:
    slug: str


primary = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
```

What a resource needs is written with `depends_on`, never read out of an annotation — a dependency
does not always have a field to live in, and one that has none is still a dependency.

Everything exported here is the declaration layer, the graph read off it, or the loader that turns a
manifest into both. The step and claim vocabulary (`when`, `then`, `claim`, `marker`, `claims`) and
the systems ATF ships (`command`, `browser`, `filesystem`, `process`) arrive with the phases that
build them.
"""

from __future__ import annotations

from .declare import (
    Declaration,
    DeclarationError,
    Instance,
    Unreachable,
    Update,
    adapter,
    declaration_of,
    instance_of,
    is_declared,
    is_resource,
    name_of,
    resource,
    system,
    values_of,
)
from .graph import (
    CycleError,
    Unmet,
    closure,
    dependents,
    edges,
    order,
    parents,
    teardown_order,
    unmet,
    unused,
)
from .loader import Suite, SuiteError, fixture_name, load_suite
from .manifest import Environment, Manifest, ManifestError

# Importing this registers the systems ATF ships, so a manifest naming `filesystem:` settings finds
# an adapter without the suite listing anything under `extensions:`.
from . import systems  # noqa: F401  # isort: skip
from .environment import Ground, GroundError, build_ground  # isort: skip
from .reconcile import (  # isort: skip
    Outcome,
    ProvisionError,
    act,
    browse,
    diff,
    ensure,
    provision,
    status,
    teardown,
)
from .spi import Adapter, Did, Record, SpiError, State  # isort: skip

from . import claims  # isort: skip
from .markers import Marker, MarkerError, marker  # isort: skip
from .registries import Check, check, claim  # isort: skip
from .steps import Step, StepError, given, then, when  # isort: skip

#: The systems ATF ships. `rest` joins them later; everything else is an adapter somebody wrote.
browser = system("browser")
command = system("command")
filesystem = system("filesystem")
process = system("process")
rest = system("rest")

__version__ = "0.1.0"

__all__ = [
    "Adapter",
    "Check",
    "CycleError",
    "Declaration",
    "DeclarationError",
    "Did",
    "Environment",
    "Ground",
    "GroundError",
    "Instance",
    "Manifest",
    "ManifestError",
    "Marker",
    "MarkerError",
    "Outcome",
    "ProvisionError",
    "Record",
    "SpiError",
    "State",
    "Step",
    "StepError",
    "Suite",
    "SuiteError",
    "Unmet",
    "Unreachable",
    "Update",
    "__version__",
    "act",
    "adapter",
    "browse",
    "browser",
    "build_ground",
    "claims",
    "check",
    "claim",
    "closure",
    "command",
    "declaration_of",
    "dependents",
    "diff",
    "edges",
    "ensure",
    "filesystem",
    "fixture_name",
    "given",
    "instance_of",
    "is_declared",
    "is_resource",
    "load_suite",
    "marker",
    "name_of",
    "order",
    "parents",
    "process",
    "provision",
    "resource",
    "rest",
    "status",
    "system",
    "teardown",
    "teardown_order",
    "then",
    "unmet",
    "unused",
    "values_of",
    "when",
]
