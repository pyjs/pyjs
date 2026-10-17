"""Summarize `gh run view --json jobs,status,headSha` from stdin, without API writes."""

import json
import sys
from datetime import datetime


def timestamp(value):
    # gh uses year one for jobs/steps that have not completed.
    return datetime.fromisoformat(value) if value and not value.startswith("0001-") else None


def duration(record):
    start = timestamp(record.get("startedAt"))
    end = timestamp(record.get("completedAt"))
    if record.get("status") != "completed" or start is None or end is None:
        return None
    return (end - start).total_seconds()


def minutes(seconds):
    return "—" if seconds is None else f"{seconds / 60:.2f}"


def report(run):
    jobs = run["jobs"]
    complete = [job for job in jobs if duration(job) is not None]
    total = sum(duration(job) for job in complete)
    lines = [f"Revision: `{run['headSha']}`; run status: {run['status']}.", "",
             "| Job | Result | Runner minutes | Test-step minutes |",
             "| --- | --- | ---: | ---: |"]
    for job in jobs:
        # Keep setup, checkout and artifact time in runner totals. A single
        # workflow can have multiple test commands, including device actions.
        steps = [step for step in job.get("steps", [])
                 if step["name"] in ("Run target tests", "Run Android device tests")
                 and step.get("conclusion") != "skipped"]
        test_seconds = (sum(duration(step) for step in steps)
                        if steps and all(duration(step) is not None for step in steps) else None)
        name = job["name"].replace("|", "\\|").replace("\n", " ")
        result = job.get("conclusion") or job["status"]
        lines.append(f"| {name} | {result} | {minutes(duration(job))} | {minutes(test_seconds)} |")
    lines.extend(("", f"Completed-job runner minutes: {minutes(total)} (not billing units)."))
    if run["status"] == "completed" and len(complete) == len(jobs) and jobs:
        span = (max(timestamp(job["completedAt"]) for job in jobs)
                - min(timestamp(job["startedAt"]) for job in jobs)).total_seconds()
        lines.append(f"First job start to last job completion: {minutes(span)} minutes.")
        if created := timestamp(run.get("createdAt")):
            queue = (min(timestamp(job["startedAt"]) for job in jobs) - created).total_seconds()
            lines.append(f"Initial queue delay: {minutes(queue)} minutes.")
    else:
        lines.append("Partial evidence: unfinished/unstarted jobs have no duration; do not compare this total to a full run.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(report(json.load(sys.stdin)), end="")
