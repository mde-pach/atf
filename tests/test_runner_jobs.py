from __future__ import annotations

import os
import time

import pytest

from atf import runner
from atf.jobs import DONE_STATES, PENDING, RUNNING, JobRunner
from tests.sample_project import write_sample_project

REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", REPO_SRC)
    return write_sample_project(tmp_path / "suite")


def wait_for(predicate, timeout: float = 120.0, interval: float = 0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


# ---- runner ---------------------------------------------------------------


def test_run_all_returns_structured_results(project):
    summary = runner.run(None, "dev", project, project / "specs")
    assert summary.returncode == 0
    assert summary.counts["passed"] == 7
    assert summary.counts["skipped"] == 1
    assert summary.counts["failed"] == 0

    result = next(r for r in summary.results.values() if "standard_account" in r.nodeid)
    assert result.outcome == "passed"
    assert result.duration >= 0.0
    assert result.detail == ""


def test_run_a_subset(project):
    everything = runner.run(None, "dev", project, project / "specs")
    target = next(nodeid for nodeid in everything.results if "project_belongs" in nodeid)

    summary = runner.run([target], "dev", project, project / "specs")
    assert list(summary.results) == [target]
    assert summary.results[target].outcome == "passed"


def test_failures_carry_detail(project):
    steps = project / "specs" / "steps" / "test_accounts.py"
    steps.write_text(steps.read_text().replace("assert context.result == expected", "assert False, 'boom'"))

    summary = runner.run(None, "dev", project, project / "specs")
    assert summary.returncode != 0
    assert summary.counts["failed"] >= 1
    failure = next(r for r in summary.results.values() if r.outcome == "failed")
    assert "boom" in failure.detail


def test_run_honours_the_environment(project):
    check = project / "specs" / "steps" / "test_env.py"
    check.write_text("def test_env(env):\n    assert env == 'locked'\n", encoding="utf-8")
    summary = runner.run([f"{check}::test_env"], "locked", project, project / "specs")
    assert summary.returncode == 0


def test_timeout_is_reported_not_raised(project):
    summary = runner.run(None, "dev", project, project / "specs", timeout=0)
    assert summary.returncode == -1
    assert "timed out" in summary.output


# ---- jobs -----------------------------------------------------------------


def test_job_streams_queued_running_then_passed(project):
    everything = runner.run(None, "dev", project, project / "specs")
    nodeids = sorted(everything.results)

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run(nodeids, "dev")

    assert job.counts[PENDING] == len(nodeids)
    assert jobs.active("dev") is job

    wait_for(lambda: job.done)

    assert job.done and job.returncode == 0
    assert job.completed == len(nodeids)
    assert all(state.state in DONE_STATES for state in job.states.values())
    assert job.counts["passed"] == 7
    assert job.counts["skipped"] == 1
    assert job.elapsed > 0


def test_a_running_test_is_reported_as_running(project):
    """The progressive view depends on this; the sample suite is too fast to observe it."""
    slow = project / "specs" / "steps" / "test_slow.py"
    slow.write_text("import time\n\n\ndef test_slow():\n    time.sleep(2)\n", encoding="utf-8")

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([f"{slow}::test_slow"], "dev")

    wait_for(lambda: any(state.state == RUNNING for state in job.states.values()), timeout=30)
    wait_for(lambda: job.done, timeout=60)
    assert job.counts[PENDING] == 0


def test_job_results_fold_into_run_results(project):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    merged = job.merged()
    assert len(merged) == 8
    assert all(result.outcome in DONE_STATES for result in merged.values())
    assert job.summary().counts["passed"] == 7


def test_only_one_active_job_per_env(project):
    jobs = JobRunner(project, project / "specs")
    first = jobs.start_run([], "dev")
    second = jobs.start_run([], "dev")
    assert second is first

    wait_for(lambda: first.done)
    assert jobs.active("dev") is None

    third = jobs.start_run([], "dev")
    assert third is not first
    wait_for(lambda: third.done)


def test_jobs_are_isolated_per_env(project):
    jobs = JobRunner(project, project / "specs")
    dev = jobs.start_run([], "dev")
    locked = jobs.start_run([], "locked")
    assert dev is not locked
    wait_for(lambda: dev.done and locked.done)


def test_failures_appear_in_job_state(project):
    steps = project / "specs" / "steps" / "test_accounts.py"
    steps.write_text(steps.read_text().replace("assert context.result == expected", "assert False, 'boom'"))

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    assert job.counts["failed"] >= 1
    failed = next(state for state in job.states.values() if state.state == "failed")
    assert "boom" in failed.detail
    assert job.returncode != 0


def test_history_and_lookup(project):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    assert jobs.get(job.id) is job
    assert jobs.history()[0] is job
    assert jobs.get("nope") is None


def test_a_broken_suite_still_finishes_the_job(project):
    (project / "specs" / "steps" / "test_broken.py").write_text("import nonexistent_module\n", encoding="utf-8")
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)
    assert job.returncode != 0


def test_a_run_with_huge_output_still_finishes(project):
    """Output goes to a file, not a pipe: a pipe fills at ~64KB and deadlocks the child."""
    noisy = project / "specs" / "steps" / "test_noisy.py"
    noisy.write_text(
        "def test_noisy():\n"
        "    print('x' * 80 * 1024)\n"
        "    assert False, 'noisy failure'\n",
        encoding="utf-8",
    )

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([f"{noisy}::test_noisy"], "dev")
    wait_for(lambda: job.done, timeout=120)

    assert job.done, "80KB of output must not deadlock the child on a full pipe"
    assert job.returncode not in (None, 0)
    assert any(state.state == "failed" for state in job.states.values())
    assert "noisy failure" in job.output


def test_a_hanging_run_is_killed_and_the_slot_is_released(project):
    """Without a timeout a wedged job blocks every future run in that environment."""
    hang = project / "specs" / "steps" / "test_hang.py"
    hang.write_text("import time\n\n\ndef test_hang():\n    time.sleep(600)\n", encoding="utf-8")

    jobs = JobRunner(project, project / "specs", timeout=3)
    job = jobs.start_run([f"{hang}::test_hang"], "dev")
    wait_for(lambda: job.done, timeout=120)

    assert job.done, "the job must finish even though the test never did"
    assert "timed out after 3s" in job.output
    assert jobs.active("dev") is None, "the environment's run slot must be released"

    # and the next run works
    following = jobs.start_run([], "dev")
    assert following is not job
    wait_for(lambda: following.done, timeout=120)
