"""Coverage boundaries for the public target matrix; no cloud calls required."""

import pytest
import yaml

from scripts.ci import BACKENDS, ROOT, TARGETS, suites


def test_native_shards_cover_every_module_once():
    files = [path.relative_to(ROOT).as_posix()
             for path in (ROOT / "tests/native").rglob("test_*.py")]
    shards = [suites("native", shard, 4)[0] for shard in range(1, 5)]
    flattened = [name for shard in shards for name in shard]
    assert sorted(flattened) == sorted(files)
    assert len(flattened) == len(set(flattened))


@pytest.mark.parametrize("target,shard,shards", [
    ("native", 0, 4), ("native", 5, 4), ("core", 1, 4), ("native", 1, 0),
])
def test_invalid_shards_fail_instead_of_running_nothing(target, shard, shards):
    with pytest.raises(ValueError):
        suites(target, shard, shards)


def test_empty_native_shard_is_not_a_pass(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        suites("native", root=tmp_path)


def test_core_and_backend_suites_partition_python_tests():
    core = suites("core")
    assert [suite[0] for suite in core] == ["tests", "examples", "extras"]
    assert {arg.removeprefix("--ignore=tests/") for arg in core[0]
            if arg.startswith("--ignore=")} == set(BACKENDS)
    directories = {path.removeprefix("tests/") for target in ("js", "jvm", "wasm")
                   for path in suites(target)[0] if path.startswith("tests/")}
    assert directories | {"native"} == set(BACKENDS)


def test_browser_and_android_suites_execute_platform_tests_in_separate_processes():
    assert [suite[:suite.index("-m")] for suite in suites("browser")] == [["tests"], ["examples", "extras"]]
    for suite in suites("browser"):
        assert "--pyjs-target=web" in suite
        assert "--pyjs-browser=managed" in suite
        assert not any(arg.startswith("--ignore") for arg in suite)
    for suite in suites("android-robolectric"):
        assert "pyjs_android_jvm and not pyjs_android_device" in suite
    device = suites("android-device")
    assert device[0][device[0].index("-m") + 1] == "pyjs_android"
    assert "--pyjs-android-runtime=host" in device[0]
    for suite in device[1:]:
        assert "pyjs_android_jvm" in suite
        assert "--pyjs-android-runtime=device" in suite


def test_workflow_runs_every_target_without_privileged_pr_execution():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    # PyYAML uses YAML 1.1, where unquoted 'on' is a boolean key.
    triggers = workflow[True]
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["tests"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["strategy"]["fail-fast"] is False
    matrix = job["strategy"]["matrix"]["include"]
    assert {item["target"] for item in matrix} == set(TARGETS)
    native = [item for item in matrix if item["target"] == "native"]
    assert sorted(item["shard"] for item in native) == list(range(1, 5))
    assert all(item["shards"] == 4 for item in native)
    assert len({item["name"] for item in matrix}) == len(matrix)
    assert workflow["jobs"]["complete"]["needs"] == ["tests", "package"]
    assert workflow["jobs"]["package"]["uses"] == "./.github/workflows/build-runtime.yml"
    assert workflow["jobs"]["complete"]["if"] == "always()"
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
