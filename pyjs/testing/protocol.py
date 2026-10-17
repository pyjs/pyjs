import json
from typing import Any, Literal

type RunFailureStage = Literal[
    "busy",
    "bundle_build",
    "browser_connection",
    "bundle_dispatch",
    "browser_execution",
    "result_transport",
]


def failed_run(stage: RunFailureStage, error: str) -> dict[str, Any]:
    return {
        "type": "run_tests_result",
        "status": "failed",
        "stage": stage,
        "error": error,
    }


def format_failure_artifact(artifact: object) -> str | None:
    if not isinstance(artifact, dict):
        return None
    paths = [
        f"{name}: {path}"
        for name, path in artifact.items()
        if name != "error" and isinstance(path, str)
    ]
    if paths:
        return ", ".join(paths)
    if artifact.get("error"):
        return f"capture failed: {artifact['error']}"
    return None


def format_run_failure(response: dict[str, Any]) -> str:
    error = response.get("error", "Unknown browser test failure")
    stage = response.get("stage")
    if isinstance(stage, str):
        lines = [f"Browser test run failed during {stage.replace('_', ' ')}: {error}"]
    else:
        lines = [str(error)]

    daemon_state = response.get("daemon_state")
    if isinstance(daemon_state, dict):
        lines.append("Daemon state: " + json.dumps(daemon_state, sort_keys=True))
    daemon_log_tail = response.get("daemon_log_tail")
    if isinstance(daemon_log_tail, str) and daemon_log_tail:
        lines.extend(["Recent daemon log:", daemon_log_tail])
    failure_artifacts = response.get("failure_artifacts")
    if isinstance(failure_artifacts, dict):
        for nodeid, artifact in failure_artifacts.items():
            if details := format_failure_artifact(artifact):
                lines.append(f"Failure artifacts for {nodeid}: {details}")
    return "\n".join(lines)
