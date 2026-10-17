"""Statement scratch is collectible; published results remain alive."""

import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.gc_support import observe_collections


def check_counts(source, directory, optimize):
    executable = LLVM().compile(observe_collections(transpile_llvm(source)), directory,
                                optimize=optimize, sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, timeout=10)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_completed_statements_release_scratch_but_keep_stored_results(tmp_path, optimize):
    check_counts('''
        from pyjs.native import gc_collect
        from tests.native.gc_support import live
        class Box:
            def __init__(self, value: str):
                self.value = value
        def main() -> int:
            gc_collect()
            baseline = live()
            len([Box("discard"), Box("also discard")])
            gc_collect()
            assert live() == baseline
            value = [Box("kept"), Box("discard")][0]
            gc_collect()
            assert live() == baseline + 1 and value.value == "kept"
            if [Box("condition")]:
                gc_collect()
                assert live() == baseline + 1
            else:
                return 1
            result = Box("yes") if value.value == "kept" else Box("no")
            gc_collect()
            assert live() == baseline + 2 and result.value == "yes"
            try:
                [Box("failure")][9]
            except IndexError:
                gc_collect()
                assert live() == baseline + 2
            else:
                return 2
            return 0
    ''', tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", [
    'min([Box("good"), Box("bad")], key=key)',
    'max([Box("good"), Box("bad")], key=key)',
    'sorted([Box("good"), Box("bad")], key=key)',
    '[Box("good"), Box("bad")].sort(key=key)',
    'sorted([Box("good")], key=key, reverse=fail_reverse())',
    '[Box("good")].sort(key=key, reverse=fail_reverse())',
])
def test_failed_selection_releases_operands_and_keeps_retry_result(tmp_path, optimize, operation):
    check_counts('''
        from pyjs.native import gc_collect
        from tests.native.gc_support import live
        class Box:
            def __init__(self, value: str):
                self.value = value
        def key(value: Box) -> str:
            gc_collect()
            if value.value == "bad":
                raise ValueError("bad key")
            return value.value + " key"
        def fail_reverse() -> bool:
            gc_collect()
            raise ValueError("bad reverse")
        def main() -> int:
            gc_collect()
            baseline = live()
            try:
                OPERATION
            except ValueError:
                gc_collect()
                assert live() == baseline
            else:
                return 1
            selected = min([Box("ready"), Box("good")], key=key)
            gc_collect()
            assert live() == baseline + 1 and selected.value == "good"
            return 0
    '''.replace("OPERATION", operation), tmp_path, optimize)
