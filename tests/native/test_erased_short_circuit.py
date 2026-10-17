import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_short_circuit_binds_once_and_only_runs_selected_arm(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        events: list[str] = []

        class Check:
            def __init__(self, name: str, truth: bool, fail: bool = False):
                self.name = name
                self.truth = truth
                self.fail = fail
            def __bool__(self) -> bool:
                events.append("truth:" + self.name)
                gc_collect()
                if self.fail:
                    raise ValueError(self.name)
                return self.truth
            def __repr__(self) -> str:
                return self.name

        def value(name: str, truth: bool, fail: bool = False) -> object:
            events.append("make:" + name)
            gc_collect()
            return Check(name, truth, fail)

        def erase(value: object) -> object: return value

        def main() -> str:
            gc_set_threshold(1)
            first = value("a", True) or value("unused", False)
            second = value("b", False) and value("unused", True)
            nested = value("c", False) or (value("d", True) and value("e", True))
            text = erase("") or "fallback"
            absent = erase(None) and "unused"
            integers = erase(0) or (erase(4) and erase(7))
            for index in range(3):
                try:
                    value("fail", True, True) or value("unused", True)
                except ValueError as error:
                    events.append(str(error))
                recovered = erase("ok") or erase("unused")
                assert isinstance(recovered, str) and recovered == "ok"
                gc_collect()
            return str((first, second, nested, text, absent, integers, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
