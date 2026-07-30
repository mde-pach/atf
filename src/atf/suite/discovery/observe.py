"""Collecting a suite in a subprocess, and what the observer wrote down about it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ...model.catalog import Node
from .model import Discovery, Fixture, Spec, Test, slug

# The plugin, named as pytest loads it, and the file it writes down what it saw in.
OBSERVER = "atf.suite.discovery.observer"
OBSERVE_OUT = "ATF_OBSERVE_OUT"


_COLLECT_TIMEOUT = 300

def observe_pytest(root: Path, specs_dir: Path, env: str) -> tuple[dict[str, Any], list[str]]:
    """Collect the suite — never run it. See [the observer](observer.py)."""
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "observed.json"
        environment = _child_env(root, env)
        environment[OBSERVE_OUT] = str(out)

        completed = _run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", OBSERVER, str(specs_dir)],
            root,
            environment,
        )
        if completed is None:
            return {}, [f"discovery timed out after {_COLLECT_TIMEOUT}s"]
        if not out.exists():
            errors.append(_tail(completed.stdout + completed.stderr))
            return {}, errors
        if completed.returncode != 0:
            errors.append(_tail(completed.stdout + completed.stderr))
        return json.loads(out.read_text(encoding="utf-8")), errors

def attach_tests(discovery: Discovery, observed: dict[str, Any], nodes: dict[str, Node]) -> None:
    by_scenario = {(spec.feature, spec.scenario): spec for spec in discovery.specs}

    for nodeid, entry in sorted(observed.get("items", {}).items()):
        feature = entry.get("feature", "")
        scenario = entry.get("scenario", "")
        spec = by_scenario.get((feature, scenario))
        name = str(entry.get("name", ""))
        params = name[name.index("[") + 1 : -1] if name.endswith("]") and "[" in name else ""

        observed_fixtures = list(observed.get("fixtures", {}).get(nodeid) or entry.get("fixtures") or [])
        # The generic step resolves a factory through `request.getfixturevalue(resource_type)`, so
        # the dependency is invisible to collection. The catalog link supplies it instead.
        if spec is not None:
            observed_fixtures += [
                nodes[node_id].resource for node_id in spec.resources if node_id in nodes
            ]

        test = Test(
            id=slug(nodeid),
            nodeid=nodeid,
            name=name,
            params=params,
            file=str(entry.get("file", "")),
            covers=spec.id if spec else "",
            resources=list(spec.resources) if spec else [],
            fixtures=sorted({fixture for fixture in observed_fixtures if not fixture.startswith("_")}),
            skipped=bool(entry.get("skipped")) or (spec.skipped if spec else False),
        )
        if spec is not None and params:
            test.resources = _resources_for_row(spec, params)
        discovery.tests.append(test)
        if spec is not None:
            spec.test_ids.append(test.id)

def _resources_for_row(spec: Spec, params: str) -> list[str]:
    """An Examples row exercises only the resources its own values name."""
    values = set(params.split("-"))
    scoped = [node_id for node_id in spec.resources if node_id.split(".", 1)[-1] in values]
    fixed = [
        node_id
        for step in spec.steps
        for node_id in step.resources
        if not any(placeholder in step.text for placeholder in ("<", ">"))
    ]
    ordered = [node_id for node_id in spec.resources if node_id in set(scoped) | set(fixed)]
    return ordered or list(spec.resources)

def attach_fixtures(
    root: Path,
    env: str,
    observed: dict[str, Any],
    resource_types: set[str],
    errors: list[str],
    tests: list[Test],
) -> list[Fixture]:
    # Built from the finished tests, so generated factories attributed from the catalog appear here.
    used_by: dict[str, list[str]] = {}
    for test in tests:
        for name in test.fixtures:
            used_by.setdefault(name, []).append(test.nodeid)
    for nodeid, names in observed.get("fixtures", {}).items():
        for name in names:
            if nodeid not in used_by.setdefault(name, []):
                used_by[name].append(nodeid)

    described = _describe_fixtures(observed)
    fixtures: list[Fixture] = []
    for name in sorted(used_by):
        if name.startswith("_"):
            continue
        doc, scope = described.get(name, ("", "function"))
        fixtures.append(
            Fixture(
                name=name,
                doc=doc,
                scope=scope,
                used_by=sorted(used_by[name]),
                generated=name in resource_types,
            )
        )
    return fixtures

def _describe_fixtures(observed: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """What each fixture is for and how long it lives, from the collection pass.

    Read by the observer plugin, from inside the pytest that already has the fixture manager open.
    """
    described: dict[str, tuple[str, str]] = {}
    for name, entry in (observed.get("described") or {}).items():
        if isinstance(entry, dict):
            described[str(name)] = (str(entry.get("doc") or ""), str(entry.get("scope") or "function"))
    return described

def _child_env(root: Path, env: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["ATF_ENV"] = env
    manifest = root / "atf.yaml"
    if manifest.is_file():
        environment["ATF_MANIFEST"] = str(manifest)
    return environment

def _run(command: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_COLLECT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None

def _tail(text: str, limit: int = 800) -> str:
    stripped = text.strip()
    return stripped[-limit:] if len(stripped) > limit else stripped
