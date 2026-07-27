"""The vocabulary the cockpit explains in place.

Every domain word the interface renders as a chip, pill or heading is defined here once, so the
same sentence appears everywhere the word does. `doc` names an anchor on the documentation's
glossary page, which carries the longer treatment; keep the two in step when adding a term.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, metadata


def docs_url(path: str = "") -> str:
    """Where the documentation is, so the cockpit can point at it rather than paraphrase it.

    `ATF_DOCS` wins, which is how you read the docs of the checkout you are working on — run
    `mkdocs serve` in the ATF repository and export `ATF_DOCS=http://127.0.0.1:8000/atf`.
    Otherwise the published site, whose address lives in `pyproject.toml` alone: ATF is a generic
    framework and its source names no domain.
    """
    base = os.environ.get("ATF_DOCS", "").strip() or _published()
    return f"{base.rstrip('/')}/{path.lstrip('/')}" if base else ""


def _published() -> str:
    try:
        entries = metadata("atf").get_all("Project-URL") or []
    except PackageNotFoundError:
        return ""
    for entry in entries:
        label, _, url = entry.partition(",")
        if label.strip().lower() == "documentation":
            return url.strip()
    return ""


@dataclass(frozen=True)
class Term:
    label: str
    short: str
    doc: str

    @property
    def url(self) -> str:
        base = docs_url("explanation/glossary/")
        return f"{base}#{self.doc}" if base else ""


TERMS: dict[str, Term] = {
    "resource": Term(
        "Resource",
        "One thing that must exist before a test is meaningful — an account, a list, a subscription. "
        "Declared as a node in the catalog, never as code.",
        "resource",
    ),
    "resource_type": Term(
        "Resource type",
        "The kind a resource is an instance of. Declared once with the system that provisions it; "
        "each type becomes a pytest fixture and a word your scenarios can use.",
        "resource-type",
    ),
    "scenario": Term(
        "Scenario",
        "A behaviour written in Gherkin, in the language of the domain. It declares the resources it "
        "needs; ATF makes them exist before the steps run.",
        "scenario",
    ),
    "test": Term(
        "Test",
        "What pytest collects from a scenario — one per scenario, or one per row of its Examples "
        "table. Tests are not written; they follow from the scenario.",
        "test",
    ),
    "catalog": Term(
        "Catalog",
        "The YAML declaration of every resource your suite can ask for, and how they depend on each "
        "other. Read without touching the network.",
        "catalog",
    ),
    "collection": Term(
        "Collection",
        "The file a resource is declared in. `catalog/owners.yaml` gives every node in it an id "
        "beginning `owners.` — a filing choice, not a property of the resource.",
        "collection",
    ),
    "adapter": Term(
        "Adapter",
        "The code that knows how to find, create and delete resources in one backend. The only place "
        "in a suite that knows a particular system exists.",
        "adapter",
    ),
    "system": Term(
        "System",
        "The backend a resource type lives in, and therefore which adapter handles it. Configured per "
        "environment, so one adapter serves dev and staging.",
        "system",
    ),
    "provision": Term(
        "Provision",
        "Make a resource exist in an environment: look for it, create it if it is not there, and do "
        "the same for everything it depends on first.",
        "provision",
    ),
    "closure": Term(
        "Closure",
        "A resource plus everything it depends on, transitively. Provisioning anything provisions its "
        "whole closure, dependencies first.",
        "closure",
    ),
    "natural_key": Term(
        "Natural key",
        "The field — or fields — by which ATF recognises a resource that already exists, so a second "
        "run reuses it instead of creating a duplicate.",
        "natural-key",
    ),
    "id_field": Term(
        "Identity field",
        "The field of the backend's record that carries the resource's identity. Other resources "
        "interpolate it with `${...id}`.",
        "id-field",
    ),
    "reference": Term(
        "Reference mode",
        "The resource must already exist in the environment; ATF may look it up but will never create "
        "it. If it is missing, the environment is not configured as the suite assumes.",
        "reference-mode",
    ),
    "ephemeral": Term(
        "Ephemeral",
        "Built fresh for every run and deleted when the scenario that used it ends. Never looked up, "
        "never seeded — reusing one would defeat its purpose.",
        "ephemeral",
    ),
    "persistent": Term(
        "Persistent",
        "Found or created, then left in place for the next run. The default, and what keeps an "
        "end-to-end suite affordable.",
        "persistent",
    ),
    "placeholder": Term(
        "Placeholder",
        "A `${...}` reference in a resource body, resolved at provisioning time — a dependency's real "
        "identity, or a timestamp relative to now.",
        "placeholder",
    ),
    "environment": Term(
        "Environment",
        "One deployment the suite can run against, with its own adapter settings and secrets. Every "
        "answer the cockpit gives is about one environment at a time.",
        "environment",
    ),
    "mutable": Term(
        "Mutable environment",
        "An environment the manifest allows ATF to change. Everywhere else, provisioning and running "
        "are refused — leave production off the list and the guard is structural.",
        "mutable-env",
    ),
    "context": Term(
        "Context",
        "The per-scenario scratchpad. The provisioning step writes each record onto it, and your own "
        "steps read them from it.",
        "context",
    ),
    "fixture": Term(
        "Fixture",
        "A pytest fixture a test builds on. ATF generates one per resource type, so a plain pytest "
        "test can ask for a catalog resource directly.",
        "fixture",
    ),
    "run": Term(
        "Run",
        "One execution of a set of tests against one environment. Runs are kept on disk, so the "
        "cockpit still knows the answer after a restart.",
        "run",
    ),
    "blocked": Term(
        "Blocked",
        "The scenario names a resource that is absent here, so running it now would stop at "
        "provisioning. Provision first and it becomes runnable.",
        "blocked",
    ),
    "flaky": Term(
        "Flaky",
        "This test has both passed and failed across recent runs without the suite changing. Its "
        "verdict cannot be trusted either way.",
        "flaky",
    ),
    "present": Term(
        "Present",
        "Found in this environment. ATF looked it up by its natural key and the backend had it.",
        "provision",
    ),
    "absent": Term(
        "Absent",
        "Not in this environment yet. ATF will create it when a scenario needs it, or when you "
        "provision it here.",
        "provision",
    ),
    "unsupported": Term(
        "Unsupported",
        "No adapter is configured for this resource's system in this environment, so ATF cannot even "
        "look it up. Add the block to the manifest.",
        "adapter",
    ),
    "error": Term(
        "Error",
        "The adapter raised while looking this up. The environment or the credentials are the usual "
        "cause; the message says which.",
        "adapter",
    ),
}


# Reading order for the Concepts page: what a suite is made of, then what happens to it, then the
# words the interface uses to report back. Alphabetical would scatter the ideas that belong together.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "What a suite is made of",
        ("catalog", "resource", "resource_type", "collection", "scenario", "test", "fixture", "context"),
    ),
    (
        "How a resource comes to exist",
        ("provision", "closure", "adapter", "system", "natural_key", "id_field", "placeholder"),
    ),
    (
        "How resources differ",
        ("persistent", "ephemeral", "reference"),
    ),
    (
        "Where it all happens",
        ("environment", "mutable"),
    ),
    (
        "What the cockpit reports",
        ("present", "absent", "unsupported", "error", "run", "blocked", "flaky"),
    ),
)


def term(key: str) -> Term | None:
    return TERMS.get(key)
