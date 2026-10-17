import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_truth_preserves_builtin_values_and_application_protocols(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Sized:
            def __init__(self, size: int):
                self.size = size
            def __len__(self) -> int:
                gc_collect()
                return self.size

        class Flag(Sized):
            def __bool__(self) -> bool:
                gc_collect()
                return False

        class Plain:
            pass

        class Broken:
            def __bool__(self) -> bool:
                gc_collect()
                raise ValueError("broken")

        def check(value: object) -> str:
            if value:
                return str(bool(value)) + str(not value)
            return str(bool(value)) + str(not value)

        def optional(value: object | None) -> str:
            return str(bool(value))

        def main() -> str:
            gc_set_threshold(1)
            empty_list: list[int] = []
            empty_dict: dict[str, int] = {}
            empty_set: set[int] = set()
            output = check(None) + check(False) + check(True) + check(0) + check(4)
            output += check(0.0) + check(-0.0) + check(float("nan"))
            output += check("") + check("x") + check(b"") + check(b"x")
            output += check(empty_list) + check([1]) + check(empty_dict) + check({"x": 1})
            output += check(empty_set) + check({1}) + check(frozenset(empty_set))
            output += check(range(0)) + check(range(4)) + check(range(-9223372036854775807, 9223372036854775807))
            output += check((1, "x")) + optional(None) + optional(0) + optional("x")
            output += check(Sized(0)) + check(Sized(2)) + check(Flag(-1)) + check(Plain())
            for repeat in range(4):
                try:
                    output += check(Sized(-1))
                except ValueError:
                    output += "size"
                try:
                    output += check(Broken())
                except ValueError:
                    gc_collect()
                    output += "broken"
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_truth_with_one_application_protocol_keeps_the_builtin_fallback(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect

        class Flag:
            def __bool__(self) -> bool:
                gc_collect()
                return True

        def truth(value: object) -> bool:
            return bool(value)

        def range_roundtrip(value: object) -> str:
            gc_collect()
            source = cast(range, value)
            return str(source) + str(isinstance(value, range)) + str(value is source)

        def main() -> str:
            return (str((truth(Flag()), truth(None), truth(False), truth(0), truth("")))
                    + range_roundtrip(range(1, 10, 2)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
