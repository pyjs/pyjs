import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize('optimize', [0, 2])
def test_slice_errors_preserve_aliases_and_cleanup(tmp_path, optimize):
    LLVM().assert_matches_python('''
def main() -> str:
    values = [1, 2, 3, 4]
    alias = values
    events: list[str] = []
    try:
        values[::2] = [8]
    except ValueError as error:
        events.append(str(error))
    try:
        values[::-2] = [8, 9, 10]
    except ValueError as reverse:
        events.append(str(reverse))
    try:
        values[::0] = [8]
    except ValueError as zero:
        events.append(str(zero))
    try:
        del values[::-0]
    except ValueError as deletion:
        events.append(str(deletion))
    try:
        invalid = range(4)[::0]
    except ValueError as ranges:
        events.append(str(ranges))
    finally:
        events.append(str(len(alias)))
    assert alias[0] == 1 and alias[1] == 2 and alias[2] == 3 and alias[3] == 4
    values[::2] = [8, 9]
    assert alias[0] == 8 and alias[2] == 9
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_numeric_python_errors_and_recovery(tmp_path, optimize):
    LLVM().assert_matches_python('''
def main() -> str:
    messages: list[str] = []
    try:
        rounded = round(1.7976931348623157e308, -308)
    except OverflowError as overflow:
        messages.append(str(overflow))
    try:
        absent = pow(4, -1, 6)
    except ValueError as inverse:
        messages.append(str(inverse))
    try:
        invalid = pow(4, 5, 0)
    except ValueError as modulus:
        messages.append(str(modulus))
    assert -9223372036854775808 % -1 == 0
    assert pow(3, -1, 7) == 5
    assert round(float("inf"), -308) == float("inf")
    return "|".join(messages)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
@pytest.mark.parametrize('expression', [
    'round(9223372036854775807, -1)',
    'round(-9223372036854775808, -1)',
    '-9223372036854775808 // -1',
    'divmod(-9223372036854775808, -1)',
    'range(-9223372036854775808, 9223372036854775807).index(0)',
    'range(0, 4, 3)[::-9223372036854775808]',
    'range(-9223372036854775808, 0)[::-1]',
])
def test_native_i64_boundary_overflow_is_catchable(tmp_path, optimize, expression):
    # CPython has arbitrary-precision integers. These are explicit native-width
    # limits, not a claim that Python itself rejects the same expressions.
    result = LLVM().run_source(f'''
def main() -> int:
    caught = 0
    index = 0
    while index < 3:
        try:
            value = {expression}
            return 1
        except OverflowError:
            caught += 1
        finally:
            index += 1
    return 0 if caught == 3 else 2
''', directory=tmp_path, optimize=optimize)
    assert result.returncode == 0, result.stderr
