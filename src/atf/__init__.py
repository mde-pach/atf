"""ATF — declared things, and the tests that need them: the framework, and the library beside it."""

from __future__ import annotations

from .declare import (
    FOREVER,
    OWNERS,
    SPANS,
    THE_RUN,
    THE_TEST,
    Declaration,
    DeclarationError,
    Instance,
    Need,
    Unreachable,
    adapter,
    declaration_of,
    driver,
    instance_of,
    is_declared,
    is_resource,
    name_of,
    needs,
    resource,
    system,
    values_of,
)
from .graph import (
    CycleError,
    closure,
    dependents,
    edges,
    order,
    parents,
    teardown_order,
    unused,
)
from .loader import Suite, SuiteError, fixture_name, load_suite
from .manifest import Environment, Manifest, ManifestError

# Importing this registers the systems ATF ships, so a manifest naming `filesystem:` settings finds
# one without the suite listing anything anywhere.
from . import systems  # noqa: F401  # isort: skip
from .environment import Ground, GroundError, build_ground  # isort: skip
from .reconcile import (  # isort: skip
    Reconciliation,
    ProvisionError,
    browse,
    change,
    diff,
    ensure,
    living,
    provision,
    status,
    teardown,
)
from .spi import Adapter, Did, Record, Resource, SpiError, State  # isort: skip

from . import claims  # isort: skip
from . import lives  # isort: skip
from .kinds import Kind, KindError, kind  # isort: skip
from .literals import LiteralError  # isort: skip
from .naming import current as namespace, within  # isort: skip
from .runs import Outcome, Run, TestOutcome, Verdict, Where  # isort: skip
from .reports import report  # isort: skip
from .steps import Step, StepError, act, check, given  # isort: skip

#: The systems ATF ships. Each carries the kinds over it as attributes, so a declaration names both
#: at once: `@filesystem.file(...)`, `@sql.row(...)`, `@browser.page(...)`.
from .declare import DRIVERS as _DRIVERS  # isort: skip

browser = _DRIVERS["browser"]
filesystem = _DRIVERS["filesystem"]
http = _DRIVERS["http"]
shell = _DRIVERS["shell"]
sql = _DRIVERS["sql"]

__version__ = "0.1.0"

__all__ = [
    "FOREVER",
    "OWNERS",
    "SPANS",
    "THE_RUN",
    "THE_TEST",
    "Adapter",
    "CycleError",
    "Declaration",
    "DeclarationError",
    "Did",
    "Environment",
    "Ground",
    "GroundError",
    "Instance",
    "Kind",
    "KindError",
    "LiteralError",
    "Manifest",
    "ManifestError",
    "Need",
    "Outcome",
    "ProvisionError",
    "Reconciliation",
    "Record",
    "Resource",
    "Run",
    "SpiError",
    "State",
    "Step",
    "StepError",
    "Suite",
    "SuiteError",
    "TestOutcome",
    "Unreachable",
    "Verdict",
    "Where",
    "__version__",
    "act",
    "adapter",
    "browse",
    "browser",
    "build_ground",
    "change",
    "check",
    "claims",
    "closure",
    "declaration_of",
    "dependents",
    "diff",
    "driver",
    "edges",
    "ensure",
    "filesystem",
    "fixture_name",
    "given",
    "http",
    "instance_of",
    "is_declared",
    "is_resource",
    "kind",
    "lives",
    "living",
    "load_suite",
    "name_of",
    "namespace",
    "needs",
    "order",
    "parents",
    "provision",
    "report",
    "resource",
    "shell",
    "sql",
    "status",
    "system",
    "teardown",
    "teardown_order",
    "unused",
    "values_of",
    "within",
]
