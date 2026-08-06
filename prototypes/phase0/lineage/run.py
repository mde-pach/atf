"""Run every case against every strategy and print what each one made of it.

    uv run python -m lineage.run          # from prototypes/phase0

A suite is a list of modules, the way `resources:` in `atf.yaml` is a list of modules. Each case
below names the modules that would be listed together, so the registry a strategy consults is the
one that suite would really have.
"""

from __future__ import annotations

import importlib

from .declare import DECLARED, STRATEGIES, Resolution, qualify, registry_for, resolve_factory

CASES: list[tuple[str, list[str], str]] = [
    ("c1_ordered", ["c1_ordered"], "parent above child, one module"),
    ("c2_forward", ["c2_forward"], "forward reference — parent below child"),
    ("c3_type_checking", ["parents", "c3_type_checking"], "parent imported under TYPE_CHECKING"),
    ("c4_cross_module", ["parents", "c4_cross_module"], "parent imported normally"),
    ("c5_self_factory", ["c5_self_factory"], "factory typed -> Self"),
    ("c6_optional", ["c6_optional"], "Owner | None and Optional[Owner]"),
    ("c7_alias_and_stranger", ["parents", "c7_alias_and_stranger"], "aliased parent + a non-lineage field"),
    ("c8_shadow", ["parents", "c8_other_owner", "c8_shadow"], "two kinds answering to the name Owner"),
]

# What the author meant, written as `module.Kind`. This is the only place intent is stated.
EXPECTED: dict[str, dict[str, dict[str, str]]] = {
    "c1_ordered": {"TodoList": {"owner": "c1_ordered.Owner"}},
    "c2_forward": {"TodoList": {"owner": "c2_forward.Owner"}},
    "c3_type_checking": {"TodoList": {"owner": "parents.Owner"}},
    "c4_cross_module": {"TodoList": {"owner": "parents.Owner"}},
    "c5_self_factory": {"TodoList": {"owner": "c5_self_factory.Owner"}},
    "c6_optional": {"TodoList": {"owner": "c6_optional.Owner"}, "Archive": {"owner": "c6_optional.Owner"}},
    "c7_alias_and_stranger": {"TodoList": {"owner": "parents.Owner"}},
    "c8_shadow": {"TodoList": {"owner": "c8_other_owner.Owner"}},
}


def verdict(case: str, kind: str, got: Resolution) -> str:
    """SILENT is the failure mode §1.1 calls the worst in the system: no error, wrong result."""
    want = EXPECTED.get(case, {}).get(kind)
    if want is None:
        return "     "
    if got.failed or got.unresolved:
        return "LOUD "
    if got.edges == want:
        return "OK   "
    return "SILENT"


def main() -> None:
    silent: list[str] = []
    loud: list[str] = []
    for case, modules, blurb in CASES:
        print(f"\n### {case} — {blurb}")
        for name in modules:
            importlib.import_module(f".cases.{name}", package="lineage")
        registry = registry_for(modules)
        if collisions := {k: v for k, v in registry.items() if len(v) > 1}:
            for kind, classes in collisions.items():
                print(f"    registry: '{kind}' is claimed by {' and '.join(qualify(c) for c in classes)}")

        subjects = [c for c in DECLARED if c.__module__.rsplit(".", 1)[-1] == case and c.__name__ in EXPECTED[case]]
        for cls in subjects:
            rows = [("at-decoration", cls.__atf_at_decoration__)]
            rows += [(name, strategy(cls, registry)) for name, strategy in STRATEGIES.items()]
            for strategy_name, result in rows:
                mark = verdict(case, cls.__name__, result)
                entry = f"{case}.{cls.__name__} via {strategy_name}"
                if mark == "SILENT":
                    silent.append(f"{entry}: {result.summary}")
                elif mark == "LOUD " and strategy_name != "at-decoration":
                    loud.append(entry)
                print(f"  {qualify(cls):<30} {strategy_name:<19} {mark:<6} {result.summary}")
            factory = resolve_factory(cls)
            if not factory.failed:
                print(f"  {'':<30} {'factory signature':<19} {'':<6} {factory.summary}")

    print("\n" + "=" * 110)
    print("Edges lost with NO error raised — the §1.1 failure mode:")
    for entry in silent or ["  (none)"]:
        print(f"  - {entry}" if silent else entry)
    print("\nRefused loudly instead (a suite author gets a message, not a wrong graph):")
    for entry in sorted(set(loud)) or ["  (none)"]:
        print(f"  - {entry}" if loud else entry)


if __name__ == "__main__":
    main()
