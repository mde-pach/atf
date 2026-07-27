from __future__ import annotations

import os
import sys
import time

import pytest

from atf import runner
from atf.bootstrap import bootstrap
from atf.jobs import PENDING, PROVISION, RUN, RUNNING, JobRunner
from atf.store import RunStore
from tests.sample_project import write_sample_project

REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", REPO_SRC)
    return write_sample_project(tmp_path / "suite")


@pytest.fixture
def engine(project, monkeypatch):
    """The provisioning engine of the sample project, in this process."""
    monkeypatch.setenv("ATF_MANIFEST", str(project / "atf.yaml"))
    # The suite's adapter module resolves its store path relative to its own file, so a module
    # left over from another temp project would write to the wrong place.
    sys.modules.pop("suite_adapters", None)
    return bootstrap("dev").materializer


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


def test_a_run_is_timestamped_for_the_history(project):
    before = time.time()
    summary = runner.run(None, "dev", project, project / "specs")
    assert before <= summary.started_at <= summary.finished_at <= time.time()

    record = summary.as_record("dev")
    assert record.env == "dev" and record.id
    assert record.counts == summary.counts


# ---- step capture -----------------------------------------------------------


def test_a_passing_scenario_reports_its_gherkin_steps(project):
    summary = runner.run(None, "dev", project, project / "specs")

    result = next(r for r in summary.results.values() if "standard_account" in r.nodeid)
    assert [(step.keyword, step.text) for step in result.steps] == [
        ("Given", 'the account "primary"'),
        ("When", "I read its plan"),
        ("Then", 'the plan is "standard"'),
    ]
    assert all(step.state == "passed" for step in result.steps)
    assert result.failed_step is None


def test_a_failing_scenario_names_the_step_that_failed(project):
    steps = project / "specs" / "steps" / "test_accounts.py"
    steps.write_text(steps.read_text().replace("assert context.result == expected", "assert False, 'boom'"))

    summary = runner.run(None, "dev", project, project / "specs")
    failure = next(r for r in summary.results.values() if r.outcome == "failed")

    failed = failure.failed_step
    assert failed is not None
    assert failed.keyword == "Then" and failed.text.startswith("the plan is")
    assert "boom" in failed.error
    assert [step.state for step in failure.steps[:-1]] == ["passed"] * (len(failure.steps) - 1)


def test_the_steps_after_a_failure_are_reported_skipped(project):
    feature = project / "specs" / "features" / "visitors.feature"
    feature.write_text(
        feature.read_text().replace(
            '    When I read its state\n    Then the state is "ready"\n',
            '    When I read its state\n    Then the state is "wrong"\n    And the state is "ready"\n',
        ),
        encoding="utf-8",
    )

    summary = runner.run(None, "dev", project, project / "specs")
    failure = next(r for r in summary.results.values() if "visitor_is_ready" in r.nodeid)
    assert [step.state for step in failure.steps] == ["passed", "passed", "failed", "skipped"]


def test_a_plain_pytest_test_simply_has_no_steps(project):
    plain = project / "specs" / "steps" / "test_plain.py"
    plain.write_text("def test_plain():\n    assert True\n", encoding="utf-8")

    summary = runner.run([f"{plain}::test_plain"], "dev", project, project / "specs")
    result = next(iter(summary.results.values()))
    assert result.outcome == "passed" and result.steps == []


def test_a_test_reports_what_it_provisioned(project):
    summary = runner.run(None, "dev", project, project / "specs")

    result = next(r for r in summary.results.values() if "project_belongs" in r.nodeid)
    assert result.provisioned == ["accounts.primary", "projects.alpha"]

    badge = next(r for r in summary.results.values() if "badge_is_issued" in r.nodeid)
    assert "visitors.walkin" in badge.provisioned, "a dependency provisioned on the way counts"


def test_a_test_reports_what_its_context_was_holding(project):
    """What was available to assert on, which nothing could say while the context was a namespace."""
    summary = runner.run(None, "dev", project, project / "specs")

    result = next(r for r in summary.results.values() if "project_belongs" in r.nodeid)
    held = {slot.name: slot for slot in result.held}

    assert held["account"].resource_type == "account"
    assert held["account"].node_id == "accounts.primary", "the provisioning step knows, so it says"
    assert held["account"].guessed is False
    assert "email" in held["account"].fields

    assert held["result"].kind == "records", "what the When produced, described without being told"
    assert held["result"].count == 1
    assert "slug" in held["result"].fields


def test_what_a_context_held_never_carries_a_value(project):
    """Run history goes to disk. A record carries a token as readily as a title."""
    summary = runner.run(None, "dev", project, project / "specs")
    everything = str([slot for result in summary.results.values() for slot in result.held])
    assert "primary@example.test" not in everything
    assert "email" in everything


# ---- jobs -----------------------------------------------------------------


def test_job_streams_queued_running_then_passed(project):
    everything = runner.run(None, "dev", project, project / "specs")
    nodeids = sorted(everything.results)

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run(nodeids, "dev")

    assert job.kind == RUN
    assert job.counts[PENDING] == len(nodeids)
    assert jobs.active("dev") is job

    wait_for(lambda: job.done)

    assert job.done and job.returncode == 0
    assert job.completed == len(nodeids)
    assert all(item.done for item in job.items.values())
    assert job.counts["passed"] == 7
    assert job.counts["skipped"] == 1
    assert job.elapsed > 0


def test_a_running_test_is_reported_as_running(project):
    """The progressive view depends on this; the sample suite is too fast to observe it."""
    slow = project / "specs" / "steps" / "test_slow.py"
    slow.write_text("import time\n\n\ndef test_slow():\n    time.sleep(2)\n", encoding="utf-8")

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([f"{slow}::test_slow"], "dev")

    wait_for(lambda: any(item.state == RUNNING for item in job.items.values()), timeout=30)
    wait_for(lambda: job.done, timeout=60)
    assert job.counts[PENDING] == 0


def test_items_are_labelled_for_the_progress_view(project):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    labels = {item.label for item in job.items.values()}
    assert "A standard account reports its plan" in labels

    named = jobs.start_run(["specs/steps/test_x.py::test_y"], "dev", labels={"specs/steps/test_x.py::test_y": "Given"})
    assert named.items["specs/steps/test_x.py::test_y"].label == "Given"
    wait_for(lambda: named.done)


def test_job_results_fold_into_run_results(project):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    merged = job.merged()
    assert len(merged) == 8
    assert all(result.outcome in {"passed", "failed", "skipped", "error"} for result in merged.values())
    assert job.summary().counts["passed"] == 7


def test_a_job_captures_steps_and_provisioning_too(project):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    item = next(item for item in job.items.values() if "project_belongs" in item.id)
    assert [step.keyword for step in item.steps] == ["Given", "And", "When", "Then"]
    assert item.provisioned == ["accounts.primary", "projects.alpha"]
    assert job.merged()[item.id].steps == item.steps


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
    failed = next(item for item in job.items.values() if item.state == "failed")
    assert "boom" in failed.detail
    assert failed.failed_step is not None and failed.failed_step.keyword == "Then"
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
    assert any(item.state == "failed" for item in job.items.values())
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


# ---- runs reach the store ---------------------------------------------------


def test_a_finished_run_job_is_persisted(project):
    store = RunStore(project)
    jobs = JobRunner(project, project / "specs", store=store)
    job = jobs.start_run([], "dev")
    wait_for(lambda: job.done)

    record = store.latest("dev")
    assert record is not None
    assert record.env == "dev" and record.returncode == 0
    assert record.counts["passed"] == 7
    assert record.started_at == job.started_at

    result = next(r for r in record.results.values() if "project_belongs" in r.nodeid)
    assert [step.keyword for step in result.steps] == ["Given", "And", "When", "Then"]
    assert result.provisioned == ["accounts.primary", "projects.alpha"]


def test_a_provision_job_is_not_persisted_as_a_run(project, engine):
    store = RunStore(project)
    jobs = JobRunner(project, project / "specs", store=store)
    job = jobs.start_provision(["accounts.primary"], "dev", engine)
    wait_for(lambda: job.done)

    assert store.latest("dev") is None


# ---- provision jobs ---------------------------------------------------------


def test_a_provision_job_reports_every_node(project, engine):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_provision(["projects.alpha"], "dev", engine)

    assert job.kind == PROVISION
    assert list(job.items) == ["accounts.primary", "projects.alpha"], "the closure, dependency first"

    wait_for(lambda: job.done)

    assert job.returncode == 0
    assert [item.state for item in job.items.values()] == ["created", "created"]
    assert job.counts["created"] == 2
    assert job.completed == job.total


def test_provisioning_twice_reports_what_was_already_there(project, engine):
    jobs = JobRunner(project, project / "specs")
    wait_for(lambda: jobs.start_provision(["accounts.primary"], "dev", engine).done)

    again = jobs.start_provision(["accounts.primary"], "dev", engine)
    wait_for(lambda: again.done)
    assert again.items["accounts.primary"].state == "exists"


def test_a_reference_that_does_not_exist_is_an_error_not_a_reference(project, engine):
    jobs = JobRunner(project, project / "specs")
    job = jobs.start_provision(["widgets.imported"], "dev", engine)
    wait_for(lambda: job.done)

    item = job.items["widgets.imported"]
    assert item.state == "error"
    assert "not found" in item.detail
    assert job.returncode == 1


def test_a_failure_blocks_its_dependents(project, engine, monkeypatch):
    def explode(self, node, body, ctx):
        raise RuntimeError("no room at the inn")

    monkeypatch.setattr(type(engine.adapters["store"]), "create", explode)

    jobs = JobRunner(project, project / "specs")
    job = jobs.start_provision(["projects.alpha"], "dev", engine)
    wait_for(lambda: job.done)

    assert job.items["accounts.primary"].state == "error"
    assert "no room at the inn" in job.items["accounts.primary"].detail
    assert job.items["projects.alpha"].state == "blocked"
    assert "did not provision" in job.items["projects.alpha"].detail
    assert "no room at the inn" in job.output


def test_an_environment_never_runs_and_provisions_at_once(project, engine):
    jobs = JobRunner(project, project / "specs")
    running = jobs.start_run([], "dev")
    refused = jobs.start_provision(["accounts.primary"], "dev", engine)

    assert refused is running, "the active run holds the environment"
    wait_for(lambda: running.done)

    provision = jobs.start_provision(["accounts.primary"], "dev", engine)
    assert provision.kind == PROVISION
    wait_for(lambda: provision.done)
    assert jobs.get(provision.id) is provision
    assert jobs.history()[0] is provision
