import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_text_views_keep_identity_and_allocation_free_results(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        def optional(value: str | None) -> str:
            return str(value)

        def boolean(value: bool | None) -> str:
            return repr(value)

        def integer(value: int | None) -> str:
            return str(value)

        def mixed(value: int | float | str | None) -> str:
            return str(value)

        def quoted(value: int | float | None) -> str:
            return repr(value)

        def main() -> int:
            gc_set_threshold(1)
            owned = "runtime-" + str(7)
            gc_collect()
            arm(1)
            first = optional(owned)
            second = mixed(owned)
            assert first is owned and second is owned
            assert optional(None) == "None"
            assert boolean(True) == "True" and boolean(False) == "False"
            assert boolean(None) == "None"
            assert integer(None) == "None"
            assert mixed(None) == "None" and mixed(False) == "False"
            assert quoted(None) == "None" and quoted(True) == "True"
            assert remaining() == 1
            arm(0)
            assert integer(42) == "42"
            gc_collect()
            return 0 if first == "runtime-7" and second == first else 1
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_text_views_match_python_with_collecting_callbacks(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Label:
            def __init__(self, text: str):
                self.text = text
            def __str__(self) -> str:
                gc_collect()
                return "str:" + self.text
            def __repr__(self) -> str:
                gc_collect()
                return "repr:" + self.text

        def optional(value: str | None) -> str:
            result = str(value)
            if value is not None:
                assert result is value
            return result

        def main() -> str:
            gc_set_threshold(1)
            text = "runtime-" + str(7)
            values: list[int | float | str | Label | None] = [
                True, False, 42, -1.25, text, "quoted\\ntext", Label(text), None]
            output = optional(text) + ":" + optional(None)
            for value in values:
                rendered = str(value)
                if isinstance(value, str):
                    assert rendered is value
                output += "|" + rendered + ":" + repr(value)
            gc_collect()
            return output + "|" + repr(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
