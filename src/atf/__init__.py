"""ATF — declared resources, and the tests that need them."""

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
    Reconciliation,
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
from .record import Outcome, Run, TestOutcome, Verdict, Where  # isort: skip
from .registries import Check, check, claim  # isort: skip
from .reports import report  # isort: skip
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
    "Reconciliation",
    "Run",
    "ProvisionError",
    "Record",
    "SpiError",
    "State",
    "Step",
    "StepError",
    "Suite",
    "TestOutcome",
    "SuiteError",
    "Unmet",
    "Unreachable",
    "Update",
    "Verdict",
    "Where",
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
    "report",
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
