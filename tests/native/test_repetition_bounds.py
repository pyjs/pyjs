"""Oversized repetition fails before allocating or mutating its receiver."""

import shutil
import subprocess
import sys
import textwrap

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_repetition_overflow_and_allocation_failure_keep_python_distinction(tmp_path, optimize):
    limiter = shutil.which("prlimit")
    if limiter is None:
        pytest.skip("requires prlimit for deliberately oversized allocations")
    source = textwrap.dedent('''
        from operator import imul, mul
        def main() -> int:
            maximum = 9223372036854775807
            for text in ("ab", "éé", "😀😀"):
                try:
                    print(text * maximum)
                except OverflowError as error:
                    print(str(error))
            for text in ("é", "😀"):
                try:
                    print(text.__rmul__(maximum))
                except MemoryError:
                    print("byte capacity")
            try:
                print(mul(b"ab", maximum))
            except OverflowError as error:
                print(str(error))
            values = [1, 2]
            alias = values
            for mode in range(4):
                try:
                    if mode == 0: values *= maximum
                    elif mode == 1: values = imul(values, maximum)
                    elif mode == 2: values = maximum * values
                    else: print((1, 2) * maximum)
                except MemoryError:
                    print("sequence capacity", alias is values, values == [1, 2])
            values *= 2
            print(alias == [1, 2, 1, 2], "é" * 2, b"ab" * 2)
            print("😀" * -maximum, b"a" * -maximum, values * -maximum)
            empty: list[int] = []
            print("" * maximum, b"" * maximum, empty * maximum)
            return 0
    ''')
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=optimize)
    # Never combine an address-space cap with ASan. Both unsanitized processes
    # have bounded address space and CPU; a missing guard cannot exhaust RAM.
    cap = [limiter, "--as=268435456", "--cpu=5", "--core=0"]
    expected = subprocess.run([*cap, sys.executable, "-c", source + "\nmain()"],
                              capture_output=True, text=True, timeout=10)
    actual = subprocess.run([*cap, str(executable)], capture_output=True, text=True, timeout=10)
    assert expected.returncode == 0, expected.stderr
    assert actual.returncode == 0, actual.stderr
    assert not expected.stderr and not actual.stderr
    assert actual.stdout == expected.stdout
