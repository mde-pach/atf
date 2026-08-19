"""`atf plan`: whether the suite is sound, and what a run would do to the environment."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import graph, lives, reconcile, steps
from . import phrases as phrase_reader
from .declare import declaration_of, name_of, values_of
from .environment import Ground
from .feature import Feature
from .loader import Suite, fixture_name
from .spi import Did, State
from .steps import Sentence, StepError


@dataclass(frozen=True)
class Fault:
    """One thing wrong with the suite, wherever it was found. Never about an environment."""

    where: str
    what: str
    hint: str = ""

    def lines(self) -> list[str]:
        out = [f"  {self.where}", f"    {self.what}"]
        if self.hint:
            out += [f"      {line}" for line in self.hint.splitlines()]
        return out


@dataclass
class Plan:
    """What a plan answers: whether the suite is sound, and what a run would do to the environment."""

    environment: str
    scenarios: int = 0
    phrases: int = 0
    python_tests: int = 0
    faults: list[Fault] = field(default_factory=list)
    standing: list[reconcile.Reconciliation] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    unreachable: str = ""
    spans: dict[str, str] = field(default_factory=dict)
    #: Why each thing lives as long as it does, by name. The rule that decided it.
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def sound(self) -> bool:
        return not self.faults

    def counted(self, state: State) -> list[reconcile.Reconciliation]:
        return [one for one in self.standing if one.state is state]

    @property
    def drifted(self) -> list[reconcile.Reconciliation]:
        return [one for one in self.standing if one.state is State.PRESENT and one.changes]


def python_tests(suite: Suite) -> list[str]:
    """Every Python test in the suite, by name — counted, never forbidden.

    The library can eat the surface, and a rule that forbade it would be routed around by worse
    means. So the hole in the spec is a number, in the output everyone already looks at.
    """
    from . import (
        core,
    )

    return [f"{path.name}::{name}" for path, name, _ in core._functions(suite)]


# --- Lint -------------------------------------------------------------------------------------


def lint(suite: Suite, features: list[Feature], phrases: dict[str, Any]) -> list[Fault]:
    """Everything wrong with the suite, asked of nothing but the files."""
    found: list[Fault] = []
    found += _sentences(suite, features, phrases)
    found += _ambiguous(phrases)
    found += _constant_recognition(suite)
    return found


def _sentences(suite: Suite, features: list[Feature], phrases: dict[str, Any]) -> list[Fault]:
    """Every sentence, bound to the step that answers it — or named as one nothing answers."""
    found: list[Fault] = []
    for feature in features:
        for scenario in feature.scenarios:
            try:
                expanded = phrase_reader.expand(scenario, phrases)
            except phrase_reader.PhraseError as exc:
                found.append(Fault(scenario.where, str(exc)))
                continue
            for line in expanded.lines:
                step = steps.matching(line.keyword, line.text)
                if step is None:
                    found.append(
                        Fault(
                            f"{scenario.where}  {scenario.name}",
                            f"{line.said} {line.text}",
                            steps.undefined(line.keyword, line.text),
                        )
                    )
                    continue
                found += _names_something_undeclared(suite, scenario.where, line, step)
    return found


def _names_something_undeclared(suite: Suite, where: str, line: Any, step: Any) -> list[Fault]:
    """A sentence naming a thing nothing declares — the commonest mistake, caught without a run.

    Only a sentence naming a kind as well is about a declared thing: `the button "Save"` fills a
    `{name}` that belongs to a page.
    """
    values = step.match(line.text) or {}
    name = values.get("name")
    kind = values.get("kind", "")
    if not kind or not any(fixture_name(one) == kind or one == kind for one in suite.kinds):
        return []
    # A phrase's `{hole}` is filled where the phrase is said, so it is not a name yet.
    if not name or name in suite.instances or "{" in name:
        return []
    near = [one for one in sorted(suite.instances) if name.lower() in one.lower()][:3]
    known = ", ".join(near) if near else ", ".join(sorted(suite.instances)[:5]) or "nothing at all"
    return [
        Fault(
            f"{where}  {line.said} {line.text}",
            f"nothing in this suite is called {name!r}",
            f"declared: {known}",
        )
    ]


def _ambiguous(phrases: dict[str, Any]) -> list[Fault]:
    """Two phrases one sentence could equally be. Wording decides, and a tie is nobody's answer."""
    found: list[Fault] = []
    seen = sorted(phrases)
    for index, one in enumerate(seen):
        for other in seen[index + 1 :]:
            if phrases[one].match(other) is not None and phrases[other].match(one) is not None:
                found.append(
                    Fault(
                        phrases[one].where,
                        f"this phrase and {other!r} match each other's wording",
                        "a sentence cannot be two phrases — reword one of them",
                    )
                )
    return found


def _constant_recognition(suite: Suite) -> list[Fault]:
    """A thing recognised by a field that resolves to a constant collides the second time.

    The fault names the field and says the second scenario asking will collide. It suggests no
    value.
    """
    found: list[Fault] = []
    for kind, cls in sorted(suite.kinds.items()):
        declaration = declaration_of(cls)
        for field_name, need in declaration.needs.items():
            if need.kind is not None or not _is_constant(need.resolver):
                continue
            found.append(
                Fault(
                    f"{declaration.module}  {kind}.{field_name}",
                    f"{kind}.{field_name} is filled by resolution and resolves to a constant.\n"
                    f"    The second scenario asking for a {kind} will collide.",
                    f"{field_name} = needs(...)        ← give it something that varies",
                )
            )
    return found


def _is_constant(resolver: Any) -> bool:
    """Whether calling this twice gives the same answer, as far as can be told without calling it."""
    return not callable(resolver)


# --- What a run would do to the environment ----------------------------------------------------


def against(
    ground: Ground, suite: Suite, names: list[str] | None = None
) -> tuple[list[reconcile.Reconciliation], str]:
    """Where the named things stand here, or where everything does, or why nothing could be asked."""
    try:
        standing = reconcile.status(ground, _selected(suite, names or []))
    except Exception as exc:  # noqa: BLE001 - an environment that will not answer is a line, not a crash
        return [], f"{type(exc).__name__}: {exc}"
    unreachable = [one for one in standing if one.state is State.UNREACHABLE]
    why = ""
    if unreachable:
        systems = sorted({declaration_of(one.resource).system for one in unreachable})
        why = f"the {', '.join(systems)} system could not be reached"
    return standing, why


def undeclared(ground: Ground, suite: Suite) -> list[str]:
    """What the environment holds that nothing in the suite knows about.

    This is what `atf adopt` was for. It belongs in the plan: a line you read every time beats a
    command nobody runs twice.
    """
    declared: dict[str, set[str]] = {}
    for node in suite.instances.values():
        for key in declaration_of(node).key:
            declared.setdefault(declaration_of(node).kind, set()).add(str(values_of(node).get(key)))

    out: list[str] = []
    for kind, cls in sorted(suite.kinds.items()):
        example = next((one for one in suite.instances.values() if type(one) is cls), None)
        if example is None or not ground.can(example, "browse"):
            continue
        keys = declaration_of(example).key
        try:
            everything = reconcile.browse(ground, example)
        except Exception:  # noqa: BLE001 - a system that cannot be listed contributes nothing here
            continue
        mine = declared.get(kind, set())
        for record in everything:
            found = ", ".join(str(record.get(key)) for key in keys)
            if found and found not in mine:
                out.append(f"{kind} {found}")
    return sorted(out)


def build(
    suite: Suite,
    features: list[Feature],
    phrases: dict[str, Any],
    ground: Ground | None,
    environment: str,
    names: list[str] | None = None,
) -> Plan:
    """The whole answer. The suite is read first, so a dead environment still gets you a lint."""
    scenarios = [one for feature in features for one in feature.tests]
    said = [one for feature in features for one in feature.phrases]
    plan = Plan(
        environment=environment,
        scenarios=len(scenarios),
        phrases=len(said),
        python_tests=len(python_tests(suite)),
        faults=lint(suite, features, phrases),
        spans=lives.table(suite),
        reasons={
            name: lives.why(lives.of(node), node) for name, node in suite.instances.items()
        },
    )
    if ground is None:
        plan.unreachable = f"no environment called {environment!r}"
        return plan
    plan.standing, plan.unreachable = against(ground, suite, names)
    if not plan.unreachable:
        plan.undeclared = undeclared(ground, suite)
    return plan


# --- Saying it --------------------------------------------------------------------------------


def lines(plan: Plan) -> list[str]:
    """The plan as a person reads it: the suite, then the environment, then what is wrong."""
    out = [f"  {plan.scenarios} scenarios"]
    if plan.phrases:
        out.append(f"  {plan.phrases} phrases")
    if plan.python_tests:
        # The hole in the spec is a number, in the output everyone already looks at, next to the
        # thing it is a hole in. A team that sees 8 and shrugs has made a decision; a team that sees
        # it climb to 60 has been told, by the tool, in time.
        out.append(f"  {plan.python_tests} python tests using atf resources        ← not in the spec")

    out.append("")
    if plan.unreachable:
        out.append(f"  {plan.environment} — {plan.unreachable}")
    else:
        present = plan.counted(State.PRESENT)
        absent = plan.counted(State.ABSENT)
        drifted = plan.drifted
        out.append(f"  {plan.environment}")
        out.append(f"    {len(present) - len(drifted)} present · {len(absent)} absent · {len(drifted)} drifted")
        for one in absent:
            resolved = plan.reasons.get(one.name, "") == lives.BECAUSE[lives.THE_RUN]
            would = "will be left alone"
            if one.did is Did.CREATED:
                would = "will be resolved when asked for" if resolved else "will be made"
            out.append(f"      absent      {one.name:<24} {would}")
        for one in drifted:
            out.append(f"      drifted     {one.name:<24} {', '.join(sorted(one.changes))}")
        for one in plan.undeclared:
            out.append(f"      undeclared  {one}")

    if plan.faults:
        out.append("")
        out.append(f"  {len(plan.faults)} problems in the suite")
        for fault in plan.faults:
            out += fault.lines()
    return out


def spans_lines(plan: Plan, suite: Suite | None = None) -> list[str]:
    """How long each thing lives, and why — the answer nobody had to type."""
    if not plan.spans:
        return []
    width = max(len(name) for name in plan.spans)
    return [
        f"  {name:<{width}}  {span:<9} "
        f"{lives.why(span, suite.instances.get(name) if suite else None)}"
        for name, span in sorted(plan.spans.items(), key=lambda one: (one[1], one[0]))
    ]


def apply(ground: Ground, suite: Suite, names: list[str] | None = None) -> list[reconcile.Reconciliation]:
    """Make what is missing, without running anything — `atf plan --apply`.

    The only reason this exists is somebody who wants the state without the tests, which is rare
    enough not to hold a name a newcomer has to learn is not the important one.
    """
    wanted = _selected(suite, names or [])
    return reconcile.provision(ground, wanted)


def _selected(suite: Suite, names: list[str]) -> list[Any]:
    """The things a command was pointed at, with the lineage they stand on, or all of them."""
    if not names:
        return list(suite.instances.values())
    wanted: list[Any] = []
    for name in names:
        for node in graph.closure(suite.resource(name)):
            if not any(seen is node for seen in wanted):
                wanted.append(node)
    return wanted


def as_json(plan: Plan, root: Path | None = None) -> dict[str, Any]:
    return {
        "environment": plan.environment,
        "sound": plan.sound,
        "scenarios": plan.scenarios,
        "phrases": plan.phrases,
        "python_tests": plan.python_tests,
        "unreachable": plan.unreachable,
        "faults": [{"where": one.where, "what": one.what, "hint": one.hint} for one in plan.faults],
        "resources": [
            {
                "name": one.name,
                "state": str(one.state),
                "would": str(one.did),
                "changes": sorted(one.changes),
                "lives": plan.spans.get(one.name, ""),
            }
            for one in plan.standing
        ],
        "undeclared": plan.undeclared,
        "lives": plan.spans,
    }


def resolved(suite: Suite, name: str) -> list[str]:
    """What resolution will call to produce one of these, in order.

    `needs()` moves work into resolution, where it is harder to read: a chain of callables that each
    take resources is powerful enough to hide real logic, and a reader looking at three words has no
    idea what they cost. This unfolds it.
    """
    node = suite.resource(name)
    out: list[str] = []
    for step in graph.closure(node):
        declaration = declaration_of(step)
        for field_name, need in declaration.needs.items():
            if field_name not in _instance(step).resolved:
                continue
            called = need.kind.__name__ if need.kind else getattr(need.resolver, "__name__", str(need.resolver))
            out.append(f"{name_of(step) or declaration.kind}.{field_name} = {called}")
    return out


def _instance(node: Any) -> Any:
    from .declare import instance_of

    return instance_of(node)


def unmatched(text: str) -> str:
    """What to say about a sentence nothing answers, with the nearest ones ATF does know."""
    return steps.undefined(steps.CHECK, text)


def sentence_of(line: Any) -> Sentence:
    """One line, bound to its step, or a `StepError` naming what did not match."""
    return Sentence(keyword=line.keyword, text=line.text, line=line.number).resolve()


__all__ = [
    "Fault",
    "Plan",
    "StepError",
    "against",
    "apply",
    "as_json",
    "build",
    "lines",
    "lint",
    "resolved",
    "spans_lines",
    "undeclared",
]
