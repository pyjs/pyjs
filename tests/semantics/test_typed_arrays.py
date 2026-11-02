import pytest

from .helpers import assert_semantics


@pytest.mark.parametrize("array_type", [
    "Int8Array", "Int16Array", "Int32Array", "Uint8Array", "Uint8ClampedArray",
    "Uint16Array", "Uint32Array", "Float16Array", "Float32Array", "Float64Array",
])
def test_typed_array_iteration_is_live_repeatable_and_bounded(array_type):
    assert_semantics(f"""
        from pyjs import js
        from pyjs.javascript import {array_type}

        @js
        def main() -> None:
            values = {array_type}([1, 2, 3, 4])
            view = values.subarray(1, 3)
            result = 0
            for value in view:
                result += int(value)
                values[2] = 9
            assert result == 11
            result = 0
            for value in view:
                result += int(value)
            assert result == 11
            for value in {array_type}(0):
                raise AssertionError("An empty typed array must not yield values")
            print(result)

        main()
    """)


def test_fractional_and_negative_typed_array_values_are_not_coerced():
    assert_semantics("""
        from pyjs import js
        from pyjs.javascript import Float64Array, Int8Array

        @js
        def main() -> None:
            result = 0.0
            for value in Float64Array([-1.25, 2.5]):
                result += float(value)
            assert result == 1.25
            for value in Int8Array([-1, -128]):
                result += float(value)
            assert result == -127.75
            print(result)

        main()
    """)


@pytest.mark.parametrize("array_type", ["BigInt64Array", "BigUint64Array"])
def test_bigint_typed_array_iteration_matches_indexed_values(array_type):
    assert_semantics(f"""
        from pyjs import int64, js
        from pyjs.javascript import {array_type}

        @js
        def main() -> None:
            values = {array_type}([int64(9007199254740993), int64(7)])
            position = 0
            for value in values:
                assert value == values[position]
                position += 1
            assert position == 2
            print(position)

        main()
    """)
