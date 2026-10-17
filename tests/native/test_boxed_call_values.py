"""Boxed call boundaries preserve reference storage and explicitly erased scalars."""

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_numeric_erasure_at_scalar_keyword_and_method_boundaries(tmp_path, optimize):
    # The preserved boxed_arguments scenario predates the shared requirement
    # for explicit portable-scalar erasure. Nested reference storage is not erased.
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def one(value: object) -> str:
            gc_collect()
            return repr(value)

        def many(**values: object) -> str:
            gc_collect()
            return repr(values)

        class Holder:
            def __init__(self, value: object):
                self.value = value

            def show(self, value: object) -> str:
                gc_collect()
                return repr((self.value, value))

        def main() -> str:
            gc_set_threshold(1)
            narrow = int8(-128)
            large = int64(9007199254740993)
            fraction = float32(1.25)
            values = {"narrow": int(narrow)}
            nested = {"items": [narrow]}
            result = [one(int(narrow)), one(value=int(large)), one(float(fraction))]
            result.append(many(narrow=int(narrow), large=int(large), fraction=float(fraction)))
            result.append(many(**values, large=int(large), fraction=float(fraction)))
            result.append(many(**nested))
            result.append(one(**{"value": int(large)}))
            result.append(Holder(int(narrow)).show(float(fraction)))
            assert nested["items"][0] - 1 == 127
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_boxed_expansions_preserve_nested_aliases_and_lazy_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def many(*values: object) -> tuple[object, ...]:
            gc_collect()
            return values

        def keywords(**values: object) -> dict[str, object]:
            gc_collect()
            return values

        def main() -> str:
            gc_set_threshold(1)
            values = [int8(-128), int8(127)]
            nested = {"items": values}
            packed = keywords(**nested)
            positional = many(*(int(value) for value in values), int(int8(3)))
            fixed = many(*(int(int64(9007199254740993)), float(float32(1.25)), values))
            mixed = many(int(int8(2)), *(int(value) for value in values))
            deferred = (keywords(**nested, other=int(int8(index))) for index in range(2))
            lazy = lambda: keywords(**nested, large=int(int64(9007199254740993)))
            values.append(int8(42))
            results = [repr(next(deferred)), repr(lazy())]
            nested.clear()
            gc_collect()
            assert packed["items"] is values
            assert fixed[2] is values
            assert values[0] - 1 == 127
            results.extend([repr(packed), repr(positional), repr(fixed), repr(mixed)])
            deferred.close()
            return repr(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
