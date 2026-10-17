import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_nextafter_optional_steps_keep_numeric_and_evaluation_semantics(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import math
        from pyjs import int8, int64, float32

        def coordinate(value: float, events: list[int], position: int) -> float:
            events.append(position)
            return value

        def count(events: list[int]) -> int | None:
            events.append(3)
            return None

        def main() -> str:
            result: list[str] = []
            for x, y in [(-0.0, 0.0), (0.0, -0.0), (1.0, math.nan),
                         (math.nan, 1.0), (math.inf, 0.0), (1.0, 2.0)]:
                for steps in [None, False, True, 0, 1, 3, -1]:
                    try:
                        result.append(str(math.nextafter(x, y, steps=steps)))
                    except ValueError as error:
                        result.append(str(error))
            assert math.nextafter(1.0, 2.0) == math.nextafter(1.0, 2.0, steps=None)
            assert math.nextafter(0, 1, steps=None) == math.nextafter(0.0, 1.0)
            assert math.nextafter(int8(0), float32(1), steps=None) == math.nextafter(0.0, 1.0)
            assert math.nextafter(1.0, 2.0, steps=int8(2)) == math.nextafter(1.0, 2.0, steps=2)
            assert math.nextafter(1.0, 2.0, steps=int64(2)) == math.nextafter(1.0, 2.0, steps=2)
            events: list[int] = []
            result.append(str(math.nextafter(coordinate(1.0, events, 1),
                coordinate(2.0, events, 2), steps=count(events))))
            assert events == [1, 2, 3]
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("steps", ["1.5", "'1'"])
def test_nextafter_steps_reject_noninteger_domains(steps):
    with pytest.raises(CompilationError, match="Argument 'steps' to nextafter expects") as caught:
        transpile_llvm(f'''import math
def main() -> float:
    return math.nextafter(1.0, 2.0, steps={steps})
''')
    assert caught.value.lineno == 3
