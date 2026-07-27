from __future__ import annotations

import json

import pytest

from atf.runner import RunRecord, StepResult
from atf.runner import TestResult as Result
from atf.store import ReportError, RunStore


def result(nodeid: str, outcome: str = "passed", **extra) -> Result:
    return Result(nodeid=nodeid, outcome=outcome, **extra)


def record(env: str = "dev", started: float = 1000.0, outcomes: dict[str, str] | None = None, **extra) -> RunRecord:
    results = {nodeid: result(nodeid, outcome) for nodeid, outcome in (outcomes or {"a::t": "passed"}).items()}
    return RunRecord(
        id=extra.pop("id", f"run{int(started)}"),
        env=env,
        started_at=started,
        finished_at=started + 1.0,
        duration=1.0,
        returncode=0,
        results=results,
    )


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path, keep=3)


# ---- writing and reading ----------------------------------------------------


def test_a_saved_run_comes_back_whole(store):
    saved = record(
        outcomes={},
    )
    saved.results["specs/steps/test_lists.py::test_a_list"] = Result(
        nodeid="specs/steps/test_lists.py::test_a_list",
        outcome="failed",
        duration=0.5,
        detail="AssertionError: boom",
        finished_at=1001.0,
        steps=[
            StepResult(keyword="Given", text='the account "primary"', state="passed"),
            StepResult(keyword="Then", text="the plan is right", state="failed", error="AssertionError: boom"),
        ],
        provisioned=["accounts.primary"],
    )
    store.save(saved)

    loaded = store.latest("dev")
    assert loaded is not None
    assert loaded.id == saved.id and loaded.started_at == saved.started_at
    restored = loaded.results["specs/steps/test_lists.py::test_a_list"]
    assert restored.outcome == "failed"
    assert restored.provisioned == ["accounts.primary"]
    assert [step.keyword for step in restored.steps] == ["Given", "Then"]
    assert restored.failed_step is not None and restored.failed_step.error == "AssertionError: boom"


def test_the_store_lives_under_dot_atf(store, tmp_path):
    assert store.dir == tmp_path / ".atf" / "runs"
    path = store.save(record())
    assert path.parent == store.dir and path.suffix == ".json"


def test_recent_is_newest_first_and_limited(store):
    for index in range(3):
        store.save(record(started=1000.0 + index, id=f"r{index}"))

    assert [run.id for run in store.recent("dev")] == ["r2", "r1", "r0"]
    assert [run.id for run in store.recent("dev", limit=2)] == ["r2", "r1"]
    assert store.latest("dev") is not None and store.latest("dev").id == "r2"


def test_runs_of_other_environments_are_invisible(store):
    store.save(record(env="dev", started=1000.0, id="d1"))
    store.save(record(env="staging", started=1001.0, id="s1"))

    assert [run.id for run in store.recent("dev")] == ["d1"]
    assert [run.id for run in store.recent("staging")] == ["s1"]
    assert store.latest("nowhere") is None


def test_two_runs_in_the_same_millisecond_do_not_collide(store):
    store.save(record(started=1000.0, id="first"))
    store.save(record(started=1000.0, id="second"))
    assert len(store.recent("dev")) == 2


def test_saving_prunes_to_keep_newest_per_env(store):
    for index in range(6):
        store.save(record(started=1000.0 + index, id=f"r{index}"))
    store.save(record(env="other", started=1000.0, id="o0"))

    assert [run.id for run in store.recent("dev", limit=10)] == ["r5", "r4", "r3"]
    assert len(list(store.dir.glob("*.json"))) == 4
    assert [run.id for run in store.recent("other")] == ["o0"], "pruning one env must not touch another"


# ---- tolerance --------------------------------------------------------------


def test_a_corrupt_file_is_skipped_not_raised(store):
    store.save(record(started=1000.0, id="good"))
    (store.dir / "000000000002000-dev-broken.json").write_text("{not json", encoding="utf-8")
    (store.dir / "000000000003000-dev-empty.json").write_text("", encoding="utf-8")
    (store.dir / "000000000004000-dev-list.json").write_text("[1, 2]", encoding="utf-8")
    (store.dir / "000000000005000-dev-partial.json").write_text('{"env": "dev"}', encoding="utf-8")

    assert [run.id for run in store.recent("dev")] == ["good"]
    assert store.flaky("dev") == {}
    assert store.merged_results("dev")


def test_unknown_keys_do_not_break_loading(store):
    path = store.save(record(started=1000.0, id="fwd"))
    payload = json.loads(path.read_text())
    payload["invented_later"] = {"anything": 1}
    payload["results"]["a::t"]["also_new"] = ["x"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = store.latest("dev")
    assert loaded is not None and loaded.id == "fwd"
    assert loaded.results["a::t"].outcome == "passed"


def test_an_empty_store_answers_every_question(tmp_path):
    empty = RunStore(tmp_path / "nothing-here")
    assert empty.recent("dev") == []
    assert empty.latest("dev") is None
    assert empty.merged_results("dev") == {}
    assert empty.flaky("dev") == {}
    assert empty.failing_since("dev", "a::t") is None


# ---- history questions ------------------------------------------------------


def test_merged_results_let_the_newest_run_win(store):
    store.save(record(started=1000.0, id="old", outcomes={"a::t": "failed", "b::t": "passed"}))
    store.save(record(started=1001.0, id="new", outcomes={"a::t": "passed"}))

    merged = store.merged_results("dev")
    assert merged["a::t"].outcome == "passed", "the newer run overrides"
    assert merged["b::t"].outcome == "passed", "a test the newer run did not cover is still known"


def test_flaky_counts_verdict_changes(store):
    store.save(record(started=1000.0, id="r0", outcomes={"flip::t": "passed", "solid::t": "passed"}))
    store.save(record(started=1001.0, id="r1", outcomes={"flip::t": "failed", "solid::t": "passed"}))
    store.save(record(started=1002.0, id="r2", outcomes={"flip::t": "passed", "solid::t": "passed"}))

    assert store.flaky("dev") == {"flip::t": 2}


def test_a_skip_is_not_a_flip(store):
    store.save(record(started=1000.0, id="r0", outcomes={"a::t": "passed"}))
    store.save(record(started=1001.0, id="r1", outcomes={"a::t": "skipped"}))
    store.save(record(started=1002.0, id="r2", outcomes={"a::t": "passed"}))

    assert store.flaky("dev") == {}


def test_an_error_is_a_failure_for_flakiness(store):
    store.save(record(started=1000.0, id="r0", outcomes={"a::t": "failed"}))
    store.save(record(started=1001.0, id="r1", outcomes={"a::t": "error"}))
    store.save(record(started=1002.0, id="r2", outcomes={"a::t": "passed"}))

    assert store.flaky("dev") == {"a::t": 1}


def test_flaky_only_looks_at_its_window(store):
    keeping = RunStore(store.root, keep=10)
    for index in range(4):
        outcome = "passed" if index else "failed"
        keeping.save(record(started=1000.0 + index, id=f"r{index}", outcomes={"a::t": outcome}))

    assert keeping.flaky("dev", window=10) == {"a::t": 1}
    assert keeping.flaky("dev", window=2) == {}


def test_failing_since_is_the_start_of_the_streak(store):
    keeping = RunStore(store.root, keep=10)
    keeping.save(record(started=1000.0, id="r0", outcomes={"a::t": "passed"}))
    keeping.save(record(started=2000.0, id="r1", outcomes={"a::t": "failed"}))
    keeping.save(record(started=3000.0, id="r2", outcomes={"a::t": "failed"}))

    assert keeping.failing_since("dev", "a::t") == 2000.0
    assert keeping.failing_since("dev", "never-seen::t") is None


def test_a_green_test_is_not_failing_since_anything(store):
    store.save(record(started=1000.0, id="r0", outcomes={"a::t": "failed"}))
    store.save(record(started=1001.0, id="r1", outcomes={"a::t": "passed"}))

    assert store.failing_since("dev", "a::t") is None


def test_a_run_that_skipped_the_test_leaves_the_streak_intact(store):
    keeping = RunStore(store.root, keep=10)
    keeping.save(record(started=1000.0, id="r0", outcomes={"a::t": "failed"}))
    keeping.save(record(started=2000.0, id="r1", outcomes={"b::t": "passed"}))
    keeping.save(record(started=3000.0, id="r2", outcomes={"a::t": "failed"}))

    assert keeping.failing_since("dev", "a::t") == 1000.0


# ---- importing a CI report --------------------------------------------------


REPORT = {
    "created": 5000.0,
    "duration": 2.5,
    "tests": [
        {"nodeid": "specs/steps/test_a.py::test_ok", "outcome": "passed", "call": {"duration": 0.5}},
        {
            "nodeid": "specs/steps/test_a.py::test_bad",
            "outcome": "failed",
            "call": {"duration": 1.0, "longrepr": "E  AssertionError: boom"},
        },
        {"nodeid": "specs/steps/test_a.py::test_wip", "outcome": "skipped", "setup": {"duration": 0.1}},
    ],
}


def test_import_report_becomes_a_run(store, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps(REPORT), encoding="utf-8")

    imported = store.import_report(report, "staging")
    assert imported.env == "staging"
    assert imported.counts == {"passed": 1, "failed": 1, "skipped": 1, "error": 0}
    assert imported.returncode == 1, "a report with a failure did not pass"
    assert imported.finished_at == 5000.0 and imported.started_at == 4997.5
    assert "boom" in imported.results["specs/steps/test_a.py::test_bad"].detail

    assert store.latest("staging") is not None
    assert store.latest("staging").id == imported.id


def test_a_green_report_imports_as_green(store, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({**REPORT, "tests": REPORT["tests"][:1]}), encoding="utf-8")

    assert store.import_report(report, "dev").returncode == 0


def test_import_rejects_what_is_not_a_report(store, tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ReportError, match="no such file"):
        store.import_report(missing, "dev")

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"created": 1.0, "tests": []}), encoding="utf-8")
    with pytest.raises(ReportError, match="no test results"):
        store.import_report(empty, "dev")

    garbage = tmp_path / "garbage.json"
    garbage.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ReportError, match="no test results"):
        store.import_report(garbage, "dev")
