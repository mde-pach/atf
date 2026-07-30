"""The thing every question is asked of, and which steps a scenario may use."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ...engine.materializer import Materializer
from ...engine.status import Statuses
from ...model.catalog import Catalog, Node
from ...session import Session
from ...spec.patterns import GIVEN, THEN, WHEN
from ...spec.vocabulary import RESOURCE, SLOT_OF, TYPE_OF, generic
from ...suite.discovery import Discovery, StepDef

KEYWORDS = (GIVEN, WHEN, THEN)



# The three things a Then can be about, plus a project's own step. A slot and a type carry their name
# in the prefix: *which* one is half of what the choice says.
NODE_SUBJECT, SLOT_SUBJECT, STEP_SUBJECT, TYPE_SUBJECT = "node:", "slot:", "step:", "type:"

# What a step wording is filed under, so a caller can tell whose vocabulary it is looking at without
# knowing where any file lives. A phrase is its own answer: there is no Python behind one.
FROM_ATF, FROM_SUITE, FROM_PHRASEBOOK = "atf", "suite", "phrasebook"

class Outside(Exception):
    """A path that is not under the suite's specs directory. Refused, never clamped."""

    def __init__(self, specs_dir: Path) -> None:
        super().__init__(f"refusing to write outside {specs_dir}")

@dataclass(frozen=True)
class Surface:
    """One environment, as everything that decides what can be said about it.

    The set is exactly what an answer depends on: change the catalog, the environment's status or the
    steps the project registers, and every answer below changes with it.
    """

    env: str
    root: Path
    specs_dir: Path
    engine: Materializer
    found: Discovery
    status: Statuses = field(default_factory=Statuses)

    @classmethod
    def of(cls, session: Session, env: str) -> Surface:
        """One environment of a live session, as everything that decides what can be said about it.

        Assembled per question, each part of it already cached one layer down: a session hands back
        the same materializer, discovery and status until something invalidates them.
        """
        return cls(
            env=env,
            root=session.manifest.root,
            specs_dir=session.manifest.specs_dir,
            engine=session.state(env).materializer,
            found=session.discovery.of(env),
            status=session.status.of(env),
        )

    @property
    def catalog(self) -> Catalog:
        return self.engine.catalog

    @property
    def nodes(self) -> dict[str, Node]:
        return self.engine.nodes

@dataclass(frozen=True)
class Option:
    """One choice, carrying what is needed to make it.

    A list of names tells a reader nothing about which name they want, so every choice offered
    anywhere here has a short `meta` beside its label and a longer `desc` under it, and `group` is
    the heading it files under. The interface renders these and an agent reads them.
    """

    value: str
    label: str
    meta: str = ""
    desc: str = ""
    group: str = ""

    def as_dict(self) -> dict[str, str]:
        """The same choice for a caller that speaks JSON."""
        return {
            "value": self.value,
            "label": self.label,
            "meta": self.meta,
            "desc": self.desc,
            "group": self.group,
        }

def subject_kind(subject: str) -> str:
    """Which of the three things a chosen subject is, in the terms `COMPARISONS` is written in."""
    if subject.startswith(TYPE_SUBJECT):
        return TYPE_OF
    if subject.startswith(SLOT_SUBJECT):
        return SLOT_OF
    return RESOURCE

def features(found: Discovery) -> list[str]:
    return sorted({spec.feature for spec in found.specs if spec.feature})

def binding_module(found: Discovery, feature: str) -> Path | None:
    """The module that hands this feature to pytest, if one does.

    It matters far beyond collection: pytest-bdd registers every step as a fixture in the module
    that declares it, so *which* module binds a feature decides which steps that feature can use.
    """
    for test in found.tests:
        spec = found.spec(test.covers) if test.covers else None
        if spec is not None and spec.feature == feature and test.file:
            return Path(test.file)
    return None

def reachable(step: StepDef, module: Path | None, specs_dir: Path) -> bool:
    """Whether a step definition is visible from the module that will bind a feature.

    pytest's fixture rules, which is what step lookup really is: a step declared in a module is
    visible in that module, one declared in a `conftest.py` is visible below it, and one a plugin
    registered — every step ATF itself defines — is visible everywhere.

    A [phrase](../spec/phrasebook.py) is in that last group and is named here: its `file` is the
    phrasebook, which sits inside the specs tree, but ATF's plugin is what registered it, so every
    feature can say it.
    """
    if not step.file or step.phrase:
        return True
    path = Path(step.file)
    try:
        path.relative_to(specs_dir)
    except ValueError:
        return True
    if path.name == "conftest.py":
        return module is None or path.parent in module.parents
    return module is not None and path == module

def offered_steps(surface: Surface, feature: str = "") -> dict[str, list[StepDef]]:
    """The steps a scenario in `feature` can actually use, by keyword.

    Everything anything does with steps goes through here — what it offers, and what it accepts. A
    step resolved from a wider set than it is offered from is a step someone can keep by switching
    feature after choosing it, and then find missing only when it runs.
    """
    binding = binding_module(surface.found, feature) if feature else None
    return {
        keyword: [
            step
            for step in surface.found.steps_for(keyword)
            if reachable(step, binding, surface.specs_dir)
        ]
        for keyword in KEYWORDS
    }

def elsewhere(
    found: Discovery, offered: dict[str, list[StepDef]], binding: Path | None, specs_dir: Path
) -> list[str]:
    """Modules holding steps this feature cannot use, for a surface that has to say so.

    The fix is a choice between two files — move the scenario, or move the step into a `conftest.py`
    every feature can see — so this names both and picks neither.
    """
    shown = {step.pattern for steps in offered.values() for step in steps}
    files = {
        Path(step.file).name
        for keyword in KEYWORDS
        for step in found.steps_for(keyword)
        if step.pattern not in shown and step.file and not reachable(step, binding, specs_dir)
    }
    return sorted(files)


def summary_of(step: StepDef) -> str:
    """What a step says it does: its table entry where ATF defines it, else its own docstring."""
    own = generic(step.pattern)
    return own.summary if own else step.docstring