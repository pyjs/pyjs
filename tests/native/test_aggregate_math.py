import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_fsum_streaming_precision_and_consumption(optimize):
    LLVM().assert_matches_python('''
    from math import fsum, inf, nan, isnan

    def main() -> str:
        result = ""
        cases = [[1e100, 1.0, -1e100], [1.0, 1e-16, 1e-16, -1.0],
                 [9007199254740992.0, -0.5, -5.551115123125783e-17],
                 [9007199254740992.0, 1.0, 7.888609052210118e-31],
                 [1e16, 1.0, 1e-16], [-0.0], [5e-324, 5e-324],
                 [inf, 1.0], [-inf, 1.0]]
        for values in cases:
            result += str(fsum(iter(values))) + ";"
        assert fsum(range(5)) == 10.0
        assert fsum((1, 2.5, True)) == 4.5
        assert fsum(()) == 0.0
        assert fsum([True, False]) == 1.0
        assert isnan(fsum([nan, 1.0]))
        cursor = iter([1e308, 1e308, 7.0])
        try:
            fsum(cursor)
        except OverflowError as error:
            result += str(error) + str(next(cursor))
        for values in [[inf, -inf], [nan, inf, -inf]]:
            try:
                fsum(iter(values))
            except ValueError as error:
                result += str(error)
        return result
    ''', optimize=optimize)
