import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["left + right", "concat(left, right)", "iconcat(left, right)",
                                        "left.__add__(right)"])
def test_fixed_tuple_concatenation_preserves_fields_identity_and_gc(expression, optimize):
    result = LLVM().assert_matches_python('''
        from operator import concat, iconcat
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        def combine(left: tuple[Box], right: tuple[Box, Box]) -> tuple[Box, Box, Box]:
            return EXPRESSION
        def main() -> str:
            gc_set_threshold(1)
            left = (int8(127), "two", (int64(9007199254740993),))
            right = (True, float32(1.5), Box(4))
            combined = EXPRESSION
            objects = combine((Box(2),), (Box(3), Box(5)))
            nested = ((1,) + ("two",)) + ((True,) + (4,))
            empty = ()
            assert empty + left is left and right + empty is right
            assert empty + empty is empty
            for index in range(20): Box(index)
            gc_collect()
            assert combined[5] is right[2]
            return repr((int(combined[0] + int8(1)), combined[1], combined[2], combined[3],
                         combined[4], combined[5].value, objects[0].value + objects[1].value
                         + objects[2].value, nested))
    '''.replace("EXPRESSION", expression), optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_concat_evaluation_order_failures_and_augmented_targets(optimize):
    result = LLVM().assert_matches_python('''
        from operator import iadd
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        def operand(events: list[int], label: int) -> tuple[Box]:
            events.append(label)
            gc_collect()
            if label < 0: raise ValueError("stop")
            return (Box(label),)
        def empty(events: list[int]) -> tuple[()]:
            events.append(0)
            gc_collect()
            return ()
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result = operand(events, 1) + operand(events, 2)
            assert events == [1, 2]
            prefix = empty(events) + operand(events, 3)
            suffix = operand(events, 4) + empty(events)
            assert events == [1, 2, 0, 3, 4, 0]
            for bad in [-1, 1]:
                events.clear()
                try: operand(events, bad) + operand(events, -2)
                except ValueError: pass
                assert events == ([-1] if bad < 0 else [1, -2])
            values = (1,)
            alias = values
            values += ()
            assert values is alias
            extended = iadd(values, (3,))
            gc_collect()
            return repr((result[0].value, result[1].value, prefix[0].value, suffix[0].value, extended))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["left + right", "concat(left, right)", "iconcat(left, right)",
                                        "left.__add__(right)"])
def test_tuple_concat_accepts_runtime_shapes(expression):
    result = LLVM().assert_matches_python(f'''from operator import concat, iconcat
def combine(left: tuple[int, ...], right: tuple[int]) -> tuple[int, ...]:
    return {expression}
def main() -> str:
    return repr((combine(tuple(range(2)), (3,)), combine((), (4,))))
''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_tuple_concat_shape_changing_reassignment_is_still_rejected():
    with pytest.raises(CompilationError, match="Cannot assign tuple\\[int, int\\]"):
        transpile_llvm('''
def main() -> int:
    values = (1,)
    values += (2,)
    return len(values)
''', filename="tuple_concat.py")


@pytest.mark.parametrize("declaration, argument", [
    ("", "tuple[int] | list[int]"),
    ("class tuple:\n    def __add__(self, other: object) -> int: return 1\n", "tuple"),
])
def test_operator_concat_diagnoses_nonconcrete_and_namesake_receivers(declaration, argument):
    with pytest.raises(CompilationError, match="concrete builtin sequence receiver"):
        transpile_llvm(f'''from operator import concat
{declaration}
def main(left: {argument}) -> int:
    return concat(left, (1,))
''', filename="tuple_concat.py")


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_concat_does_not_intercept_application_reflected_add(optimize):
    result = LLVM().assert_matches_python('''
        class Right:
            def __radd__(self, left: tuple[int]) -> int:
                return left[0] + 7
        def main() -> int:
            return (2,) + Right()
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_concat_allocation_failure_preserves_inputs_and_retry(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining
        class Box:
            def __init__(self, value: int): self.value = value
        def main() -> int:
            gc_set_threshold(1)
            left = (Box(2),)
            right = (Box(3), "tail")
            failures = 0
            exhausted = False
            for stage in range(1, 100):
                try:
                    arm(stage)
                    result = left + right
                    exhausted = remaining() > 0
                    arm(0)
                    assert result[0] is left[0] and result[1] is right[0]
                    assert result[2] == "tail"
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert left[0].value == 2 and right[0].value == 3
                retry = left + right
                assert retry[0] is left[0] and retry[1] is right[0]
                if exhausted: break
            assert failures > 0 and exhausted
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
