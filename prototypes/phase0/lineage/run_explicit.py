"""Lineage with no annotations at all, asked whether the graph still answers everything it must.

    uv run python -m lineage.run_explicit      # from prototypes/phase0

The graph is what ATF sells. It has to give the provisioning order, the closure from one name, the
teardown order, `atf impact`, `atf unused`, and a loud complaint when a declaration cannot be met.
"""

from __future__ import annotations

import importlib

from .explicit import DECLARED, INSTANCES, closure, dependents, is_resource, name_of, scan, unused, values_of


def main() -> None:
    module = importlib.import_module(".cases.e1_explicit", package="lineage")
    scan(module)

    print("### what each decorator recorded — @sqlite is @resource plus that system's options")
    for name, cls in DECLARED.items():
        d = cls.__atf__
        needs = ", ".join(getattr(e, "__name__", None) or repr(e) for e in d.depends_on) or "-"
        print(f"  {name:<10} system={d.system or '(none)':<8} options={d.options or '{}'!s:<22} depends_on[{needs}]")

    print("\n### declared instances — built as DESIGN.md builds them, with the class's own constructor")
    for name, r in INSTANCES.items():
        written = ", ".join(k for k, v in values_of(r).items() if not is_resource(v)) or "-"
        print(f"  {name:<10} kind={type(r).__name__:<9} writes[{written}]")

    print("\n### closure — what is made, in order, from one name")
    for name in ("groceries", "laundry", "quarterly", "scratch", "march"):
        print(f"  ask for {name:<10} {' -> '.join(repr(r) for r in closure(INSTANCES[name]))}")
    print("  (* is factory-built: the kind was asked for and nothing named one)")

    print("\n### teardown — the reverse, so a list goes before its owner")
    print(f"  drop laundry    {' -> '.join(repr(r) for r in reversed(closure(INSTANCES['laundry'])))}")

    print("\n### atf impact — what breaks if this changes")
    for name in ("primary", "groceries", "free"):
        print(f"  {name:<10} {', '.join(name_of(r) for r in dependents(INSTANCES[name])) or '-'}")

    print("\n### atf unused — what nothing asks for")
    print(f"  {', '.join(name_of(r) for r in unused()) or '-'}")

    print("\n### a requirement that cannot be met is named, not arranged")
    stray = module.Invoice(number="stray")
    stray.__atf_name__ = "stray"
    try:
        closure(stray)
    except ValueError as exc:
        print(f"  {exc}")

    print("\n### a cycle is refused")
    a = module.Owner(email="a@example.com")
    b = module.Owner(email="b@example.com", depends_on=[a])
    a.__atf_name__, b.__atf_name__ = "a", "b"
    a.__atf_depends_on__.append(b)
    try:
        closure(a)
    except ValueError as exc:
        print(f"  {exc}")


if __name__ == "__main__":
    main()
