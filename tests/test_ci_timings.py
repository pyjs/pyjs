from copy import deepcopy

import pytest

from scripts.ci_timings import native_weights, report


def job(name, start, end, *, steps=()):
    return {"name": name, "status": "completed", "conclusion": "success",
            "startedAt": f"2026-01-01T00:{start}Z", "completedAt": f"2026-01-01T00:{end}Z",
            "steps": list(steps)}


def test_overlapping_jobs_distinguish_runner_time_from_critical_path():
    run = {"headSha": "a" * 40, "status": "completed", "createdAt": "2026-01-01T00:00:00Z",
           "jobs": [job("one", "00:10", "02:10", steps=[job("Run target tests", "00:40", "02:00")]),
                    job("two", "01:10", "02:40")]}
    result = report(run)
    assert "| one | success | 2.00 | 1.33 |" in result
    assert "Completed-job runner minutes: 3.50" in result
    assert "last job completion: 2.50 minutes" in result
    assert "Initial queue delay: 0.17 minutes" in result


def test_device_step_is_counted_without_skipped_host_step():
    skipped = job("Run target tests", "00:10", "00:10")
    skipped["conclusion"] = "skipped"
    run = {"headSha": "a" * 40, "status": "completed",
           "jobs": [job("device", "00:00", "03:00", steps=[skipped,
                    job("Run Android device tests", "00:30", "02:30")])]}
    assert "| device | success | 3.00 | 2.00 |" in report(run)


def test_partial_rerun_has_no_measurable_queue_delay_or_cumulative_cost():
    run = {"headSha": "a" * 40, "status": "completed", "createdAt": "2026-01-01T00:10:00Z",
           "jobs": [job("carried", "00:10", "02:10"), job("retried", "10:10", "11:10")]}
    text = report(run)
    assert "Initial queue delay: unavailable (jobs predate this attempt)." in text
    assert "Initial queue delay: -" not in text
    assert "Completed-job runner minutes: 3.00" in text
    assert "not cumulative retry-inclusive use" in text
    assert "last job completion: 11.00 minutes" in text


def test_live_and_skipped_jobs_never_get_fake_or_negative_durations():
    pending = job("waiting", "00:00", "01:00")
    pending.update(status="in_progress", conclusion="", completedAt="0001-01-01T00:00:00Z")
    skipped = deepcopy(pending)
    skipped.update(name="skipped", status="completed", conclusion="skipped", startedAt=None)
    run = {"headSha": "a" * 40, "status": "in_progress",
           "jobs": [job("done", "00:00", "01:00"), pending, skipped]}
    text = report(run)
    assert "| waiting | in_progress | — | — |" in text
    assert "| skipped | skipped | — | — |" in text
    assert "Completed-job runner minutes: 1.00" in text
    assert "Partial evidence" in text
    assert "last job completion" not in text


def test_native_weights_aggregate_cases_not_unrelated_suites(tmp_path):
    (tmp_path / "1.xml").write_text('''<testsuite>
      <testcase classname="tests.native.test_one" name="a" time="1.5"/>
      <testcase classname="tests.native.test_one" name="b" time="2.1"/>
      <testcase classname="tests.native.test_two" name="a" time="0"/>
      <testcase classname="tests.other" name="a" time="50"/>
    </testsuite>''')
    assert native_weights(tmp_path) == {"tests/native/test_one.py": 4,
                                        "tests/native/test_two.py": 1}


def test_native_weights_reject_mixed_runs_and_empty_evidence(tmp_path):
    with pytest.raises(ValueError, match="No native"):
        native_weights(tmp_path)
    xml = '<testsuite><testcase classname="tests.native.test_one" time="1"/></testsuite>'
    for name in ("first.xml", "second.xml"):
        (tmp_path / name).write_text(xml)
    with pytest.raises(ValueError, match="Repeated native modules"):
        native_weights(tmp_path)
