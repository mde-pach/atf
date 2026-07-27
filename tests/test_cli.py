from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from atf.cli import main
from tests.sample_project import write_sample_project

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "todo"


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    monkeypatch.setenv("PYTHONPATH", str(REPO / "src"))
    monkeypatch.chdir(root)
    import sys as _sys

    _sys.modules.pop("suite_adapters", None)
    return root


# ---- init ------------------------------------------------------------------


def test_init_scaffolds_a_runnable_suite(tmp_path, capsys):
    target = tmp_path / "new-suite"
    assert main(["init", str(target)]) == 0

    for relative in ("atf.yaml", "catalog/resources.yaml", "adapters.py", "conftest.py",
                     "specs/features/accounts.feature", "specs/steps/test_accounts.py", "README.md"):
        assert (target / relative).is_file(), relative

    assert 'pytest_plugins = ["atf.plugin"]' in (target / "conftest.py").read_text()
    assert "mutable_envs" in (target / "atf.yaml").read_text()
    assert "Scaffolded" in capsys.readouterr().out


def test_init_never_overwrites(tmp_path, capsys):
    target = tmp_path / "suite"
    main(["init", str(target)])
    (target / "atf.yaml").write_text("mine\n", encoding="utf-8")

    assert main(["init", str(target)]) == 0
    assert (target / "atf.yaml").read_text() == "mine\n"
    assert "already contains a suite" in capsys.readouterr().out


def test_the_scaffolded_suite_runs_green(tmp_path, monkeypatch):
    """What `atf init` writes must pass against a live backend — it is the first thing a user runs."""
    from tests.stub_api import StubAPI

    target = tmp_path / "suite"
    main(["init", str(target)])

    stub = StubAPI()
    base_url = stub.start()
    try:
        manifest = target / "atf.yaml"
        manifest.write_text(
            manifest.read_text().replace("https://dev.example.com", base_url), encoding="utf-8"
        )
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=target,
            env={
                **os.environ,
                "ATF_MANIFEST": str(manifest),
                "ATF_ACTOR": "scaffold",
                "PYTHONPATH": str(REPO / "src"),
            },
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        # One scenario needing no step code, one needing a When and a Then: the scaffold has to
        # show both, because knowing which is which is most of writing a suite.
        assert "2 passed" in completed.stdout
    finally:
        stub.stop()


def test_the_scaffolded_catalog_loads(tmp_path, monkeypatch):
    target = tmp_path / "suite"
    main(["init", str(target)])
    monkeypatch.setenv("ATF_MANIFEST", str(target / "atf.yaml"))
    monkeypatch.setenv("ATF_ACTOR", "actor")

    from atf.bootstrap import bootstrap

    boot = bootstrap("dev")
    assert set(boot.materializer.nodes) == {"accounts.primary", "projects.alpha"}


# ---- status / seed / run ---------------------------------------------------


def test_status_lists_every_resource(project, capsys):
    assert main(["status", "dev"]) == 0
    out = capsys.readouterr().out
    assert "accounts.primary" in out and "absent" in out
    assert "visitors.walkin" in out and "ephemeral" in out
    assert "built per run" in out
    assert "0/5 present in dev (1 built per run)" in out


def test_seed_then_status_reports_present(project, capsys):
    main(["seed", "dev", "--type", "account", "--name", "primary"])
    capsys.readouterr()

    assert main(["status", "dev"]) == 0
    out = capsys.readouterr().out
    assert "accounts.primary" in out.split("\n")[0] or "present" in out


def test_seed_provisions_the_closure_of_a_subset(project, capsys):
    assert main(["seed", "dev", "--type", "project", "--name", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "accounts.primary" in out  # the dependency came along
    assert "projects.alpha" in out
    assert "2 created" in out


def test_seed_refuses_a_non_mutable_env(project, capsys):
    assert main(["seed", "locked"]) == 2
    assert "not in `mutable_envs`" in capsys.readouterr().err


def test_seed_rejects_an_unknown_type(project, capsys):
    assert main(["seed", "dev", "--type", "ghost"]) == 2
    assert "unknown resource type 'ghost'" in capsys.readouterr().err


def test_seed_rejects_a_name_without_a_type(project, capsys):
    assert main(["seed", "dev", "--name", "primary"]) == 2
    assert "--name needs --type" in capsys.readouterr().err


def test_run_reports_results_and_exits_zero(project, capsys):
    assert main(["run"]) == 0
    out = capsys.readouterr().out
    assert "7 passed, 0 failed, 1 skipped" in out
    assert "passed" in out


def test_run_exits_nonzero_on_failure(project, capsys):
    steps = project / "specs" / "steps" / "test_accounts.py"
    steps.write_text(steps.read_text().replace("assert context.result == expected", "assert False, 'boom'"))

    assert main(["run"]) == 1
    out = capsys.readouterr().out
    assert "failed" in out
    assert "AssertionError" in out


def test_missing_manifest_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ATF_MANIFEST", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["status", "dev"]) == 2
    assert "atf init" in capsys.readouterr().err


def test_unknown_env_is_a_clear_error(project, capsys):
    assert main(["status", "nowhere"]) == 2
    assert "unknown environment" in capsys.readouterr().err


# ---- the example project ---------------------------------------------------


def example_env(url: str) -> dict[str, str]:
    return {
        **os.environ,
        "TODO_URL": url,
        "TODO_ACTOR": "example",
        "ATF_MANIFEST": str(EXAMPLE / "atf.yaml"),
        "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(EXAMPLE)]),
    }


@pytest.fixture
def example_api():
    sys.path.insert(0, str(EXAMPLE))
    from fake_api import TodoAPI

    api = TodoAPI(actor="example")
    url = api.start()
    yield url
    api.stop()
    sys.path.remove(str(EXAMPLE))


def cli(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "atf.cli", *args],
        cwd=EXAMPLE,
        env=example_env(url),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_the_example_seeds_and_runs_green(example_api):
    seeded = cli(example_api, "seed", "dev")
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    assert "6 created, 1 found" in seeded.stdout  # the ephemeral guest is not seeded

    run = cli(example_api, "run")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "8 passed, 0 failed" in run.stdout


def test_the_example_runs_green_without_seeding_first(example_api):
    """Specs provision what they need — a fresh environment needs no seed step."""
    run = cli(example_api, "run")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "8 passed, 0 failed" in run.stdout


def test_the_example_is_idempotent(example_api):
    assert cli(example_api, "run").returncode == 0
    second = cli(example_api, "run")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "8 passed, 0 failed" in second.stdout


def test_the_example_exercises_rest_reference_and_a_custom_ephemeral_adapter(example_api):
    cli(example_api, "seed", "dev")
    status = cli(example_api, "status", "dev")
    assert status.returncode == 0

    assert "labels.urgent" in status.stdout and "present" in status.stdout   # reference (find-only)
    assert "guests.visitor" in status.stdout and "ephemeral" in status.stdout  # custom adapter
    assert "tasks.milk" in status.stdout                                      # rest, non-default id_field

    import httpx

    headers = {"X-Actor": "example"}
    # the ephemeral guest each run creates is torn down again
    cli(example_api, "run")
    guests = httpx.get(f"{example_api}/guests", headers=headers).json()
    assert guests["results"] == []


def test_the_example_refuses_to_seed_its_read_only_env(example_api):
    result = cli(example_api, "seed", "staging")
    assert result.returncode == 2
    assert "not in `mutable_envs`" in result.stderr


def test_seed_stops_at_the_first_failure_by_default(project, capsys, monkeypatch):
    """One bad token or an unreachable backend should report once, not once per resource."""
    store = project / "store.json"
    store.write_text("not json at all", encoding="utf-8")

    assert main(["seed", "dev"]) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "Stopped at the first failure" in out
    assert "--keep-going" in out


def test_seed_keep_going_reports_every_independent_failure(project, capsys):
    """`external_widget` is find-only and absent, so it always fails; the rest must still run."""
    assert main(["seed", "dev", "--keep-going"]) == 1
    out = capsys.readouterr().out

    assert "[FAIL] widgets.imported" in out
    assert "accounts.primary" in out and "created" in out
    assert "5 created" in out and "1 failed" in out
    assert "Stopped at the first failure" not in out


def test_seed_marks_the_dependents_of_a_failure_as_blocked(project, capsys):
    types = project / "catalog" / "resources.yaml"
    types.write_text(
        types.read_text() + "\nbanner:\n  system: store\n  collection: banners\n  natural_key: slug\n",
        encoding="utf-8",
    )
    (project / "catalog" / "banners.yaml").write_text(
        "hero:\n  resource: banner\n  depends_on: [widgets.imported]\n"
        "  body: {slug: hero, widget_id: '${widgets.imported.id}'}\n",
        encoding="utf-8",
    )

    assert main(["seed", "dev", "--keep-going"]) == 1
    out = capsys.readouterr().out
    assert "[skip] banners.hero" in out
    assert "depends on widgets.imported" in out
    assert "blocked" in out


def test_the_example_needs_no_setup(tmp_path):
    """`cd examples/todo && atf serve` must work on a clean checkout, with nothing exported."""
    bare = {
        key: value
        for key, value in os.environ.items()
        if key not in {"TODO_URL", "TODO_ACTOR", "ATF_ENV", "ATF_MANIFEST"}
    }
    completed = subprocess.run(
        [sys.executable, "-m", "atf.cli", "status", "dev"],
        cwd=EXAMPLE,
        env={**bare, "PYTHONPATH": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "started the stand-in API" in completed.stdout
    assert "present in dev" in completed.stdout
