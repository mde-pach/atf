"""What changes when a suite does *not* write `from __future__ import annotations`.

    uv run python -m lineage.run_no_future      # from prototypes/phase0

The four cases in `run.py` that lose an edge are all downstream of the annotation being a string.
Without that line the annotation is the class, and the two shapes that cannot be resolved stop
being ATF's problem: Python refuses them itself, at import, by name and line.
"""

from __future__ import annotations

import importlib
import typing

from .declare import DECLARED, registry_for, resolve_recommended

CASES = [
    ("n1_plain", "parent above child, no future import"),
    ("n2_forward", "forward reference, no future import"),
    ("n3_type_checking", "TYPE_CHECKING import, no future import"),
    ("n4_collection", "sixteen players and some games — no field to type"),
]


def main() -> None:
    for module_name, blurb in CASES:
        print(f"\n### {module_name} — {blurb}")
        try:
            importlib.import_module(f".cases.{module_name}", package="lineage")
        except Exception as exc:  # noqa: BLE001 - what Python says is the finding
            print(f"  REFUSED BY PYTHON AT IMPORT  {type(exc).__name__}: {exc}")
            print("  -> loud, located, and nothing for ATF to detect or decide")
            continue

        registry = registry_for([module_name])
        for cls in [c for c in DECLARED if c.__module__.rsplit(".", 1)[-1] == module_name]:
            annotations = dict(cls.__dict__.get("__annotations__", {}))
            strings = [n for n, a in annotations.items() if isinstance(a, str)]
            resolved = resolve_recommended(cls, registry)
            print(f"  {cls.__name__:<12} raw={ {n: str(a) for n, a in annotations.items()} }")
            print(f"  {'':<12} string annotations: {strings or 'none'}")
            print(f"  {'':<12} {resolved.summary}")
            for name, annotation in annotations.items():
                origin, args = typing.get_origin(annotation), typing.get_args(annotation)
                if origin is not None:
                    kinds = [getattr(a, "__name__", a) for a in args]
                    declared = [k for k in kinds if k in registry]
                    print(
                        f"  {'':<12} {name}: origin={origin.__name__} args={kinds}"
                        f" -> {'declared kinds: ' + ', '.join(declared) if declared else 'not resources'}"
                    )


if __name__ == "__main__":
    main()
