import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations, run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_and_base_format_failures_preserve_results_and_allow_retry(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_count
        from tests.native.allocation_support import arm, remaining

        class Box:
            pass

        def render(value: Box, number: int, mode: int) -> str:
            if mode == 0:
                return repr(value)
            if mode == 1:
                return str(value)
            if mode == 2:
                return repr([value])
            if mode == 3:
                return repr({"value": value})
            if mode == 4:
                return f"{value!r}"
            if mode == 5:
                return value.__repr__()
            if mode == 6:
                return value.__str__()
            if mode == 7:
                return bin(number)
            if mode == 8:
                return oct(number)
            return hex(number)

        def main() -> int:
            value = Box()
            numbers = [0, -1, 9223372036854775807, -9223372036854775808]
            sample = 0
            while sample < 4:
                number = numbers[sample]
                mode = 0 if sample == 0 else 7
                while mode < 10:
                    expected = render(value, number, mode)
                    arm(1000)
                    probe = render(value, number, mode)
                    stages = 1000 - remaining()
                    arm(0)
                    if probe != expected or stages < 1:
                        return 1
                    failure = 1
                    while failure <= stages:
                        result = "unchanged"
                        caught = False
                        arm(failure)
                        try:
                            result = render(value, number, mode)
                        except MemoryError:
                            caught = True
                        arm(0)
                        gc_collect()
                        if not caught or result != "unchanged" or gc_count() != 0:
                            return 2
                        if render(value, number, mode) != expected:
                            return 3
                        failure += 1
                    mode += 1
                sample += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("expression, message", [
    ("repr(value)", "native text output allocation failed"),
    ("str(value)", "native text output allocation failed"),
    ("hex(10)", "native allocation failed"),
])
def test_object_and_base_allocation_tracebacks_have_call_locations(tmp_path, expression, message):
    source = transpile_llvm(f'''from pyjs import llvm
class Box:
    pass
@llvm.inline("store i64 {{value}}, ptr @test.remaining")
def arm(value: int) -> None:
    pass
def main() -> int:
    value = Box()
    arm(1)
    return len({expression})
''', filename="object_failure.py")
    managed = "define ptr @pyjs.gc.new()" in source
    executable = LLVM().compile(_fail_allocations(source, managed), tmp_path, optimize=0)
    result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        f'  File "object_failure.py", line 10, in main\nMemoryError: {message}\n'
    )
