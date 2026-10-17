import pytest

from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import RANGE_NUMERIC_LOOKUP_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_range_lookup_contract(tmp_path, optimize):
    result = LLVM().assert_matches_python(
        RANGE_NUMERIC_LOOKUP_CONTRACT.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0, RANGE_NUMERIC_LOOKUP_CONTRACT.failure(result.native.returncode)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_float_range_lookup_matrix(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        def inspect(values: range, item: float) -> str:
            result = repr((item in values, item not in values,
                           values.__contains__(item), values.count(item)))
            try:
                return result + ":" + str(values.index(item))
            except ValueError as error:
                return result + ":" + str(error)

        def main() -> str:
            result: list[str] = []
            for values in [range(-5, 6, 2), range(6, -6, -2), range(0),
                           range(9007199254740990, 9007199254740995),
                           range(-9223372036854775808, -9223372036854775805),
                           range(9223372036854775804, 9223372036854775807)]:
                for item in [-0.0, 0.0, -1.0, 1.0, -1.5, 1.5, 5e-324,
                             9007199254740991.0, 9007199254740992.0, 9007199254740994.0,
                             -9223372036854775808.0, -9223372036854777856.0,
                             9223372036854774784.0, 9223372036854775808.0,
                             1e309, -1e309, 1e309 - 1e309]:
                    result.append(inspect(values, item))
            return "|".join(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_range_lookup_operand_order_and_numeric_consumers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import operator
        from pyjs import float32, float64, int64
        from pyjs.native import gc_collect, gc_set_threshold

        def item(events: list[str]) -> float:
            events.append("item")
            gc_collect()
            return 2.0

        def values(events: list[str]) -> range:
            events.append("range")
            return range(0, 6, 2)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            a = item(events) in values(events)
            b = values(events).count(item(events))
            c = values(events).index(item(events))
            d = operator.contains(values(events), item(events))
            source = range(4)
            return repr((a, b, c, d, events, source.count(float32(2.0)),
                         source.index(float64(2.0)), True in source,
                         source.count(False), source.index(True), source.index(int64(2))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_enormous_range_float_lookup_without_iteration(tmp_path, optimize):
    # CPython linearly searches non-int subjects. Compare against the exact
    # integral subject there so the test itself never traverses 2**64 entries.
    result = LLVM().run_source('''
        def main() -> str:
            values = range(-9223372036854775808, 9223372036854775807)
            present = 0.0 in values
            count = values.count(0.0)
            try:
                values.index(0.0)
                return "missing overflow"
            except OverflowError:
                return repr((present, count))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    expected = range(-(2**63), 2**63 - 1)
    assert result.stdout == repr((0 in expected, expected.count(0)))
    assert result.stderr == ""
