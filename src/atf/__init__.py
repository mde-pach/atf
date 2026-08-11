"""ATF — declared resources, and the tests that need them."""

from __future__ import annotations

from .declare import (
    Declaration,
    DeclarationError,
    Instance,
    Unreachable,
    adapter,
    declaration_of,
    driver,
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
    Reconciliation,
    ProvisionError,
    browse,
    change,
    diff,
    ensure,
    provision,
    status,
    teardown,
)
from .spi import Adapter, Did, Record, Resource, SpiError, State  # isort: skip

from . import claims  # isort: skip
from .markers import Marker, MarkerError, marker  # isort: skip
from .naming import current as namespace, within  # isort: skip
from .runs import Outcome, Run, TestOutcome, Verdict, Where  # isort: skip
from .registries import Check, check, claim  # isort: skip
from .reports import report  # isort: skip
from .steps import Step, StepError, given, then, when  # isort: skip

#: The things ATF ships an adapter for. Each is one kind of thing, not one technology: `file`,
#: `directory` and `tree` are three, and they read one `filesystem:` block between them.
#: The drivers ATF ships. Each carries the adapters over it as attributes, so a declaration names
#: both at once: `@filesystem.file(...)`, `@sql.row(...)`, `@browser.page(...)`.
from .declare import DRIVERS as _DRIVERS  # noqa: E402  # isort: skip

browser = _DRIVERS["browser"]
filesystem = _DRIVERS["filesystem"]
http = _DRIVERS["http"]
shell = _DRIVERS["shell"]
sql = _DRIVERS["sql"]

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
    "Reconciliation",
    "Run",
    "ProvisionError",
    "Record",
    "Resource",
    "SpiError",
    "State",
    "Step",
    "StepError",
    "Suite",
    "TestOutcome",
    "SuiteError",
    "Unmet",
    "Unreachable",
    "Verdict",
    "Where",
    "__version__",
    "adapter",
    "browse",
    "browser",
    "change",
    "build_ground",
    "claims",
    "check",
    "filesystem",
    "http",
    "claim",
    "closure",
    "declaration_of",
    "dependents",
    "diff",
    "edges",
    "ensure",
    "driver",
    "fixture_name",
    "given",
    "instance_of",
    "is_declared",
    "is_resource",
    "load_suite",
    "marker",
    "namespace",
    "name_of",
    "order",
    "parents",
    "provision",
    "report",
    "shell",
    "sql",
    "resource",
    "status",
    "system",
    "teardown",
    "teardown_order",
    "then",
    "unmet",
    "unused",
    "values_of",
    "when",
    "within",
]
