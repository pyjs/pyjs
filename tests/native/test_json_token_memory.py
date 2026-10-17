"""Numeric serialization needs bounded scratch, not a string per item."""

import shutil
import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal,width", [("7", 1), ("0.5", 3)])
def test_json_numeric_tokens_do_not_accumulate(tmp_path, optimize, literal, width):
    limiter = shutil.which("prlimit")
    if limiter is None:
        pytest.skip("requires prlimit for an isolated executable memory bound")
    source = f'''
        import json
        from pyjs.native import gc_is_enabled
        def main() -> int:
            assert gc_is_enabled()
            values = [{literal}] * 1000000
            encoded = json.dumps(values)
            assert len(encoded) == {(width + 2) * 1000000}
            assert encoded.count("{literal}") == 1000000
            assert encoded.startswith("[{literal}, ") and encoded.endswith("{literal}]")
            return 0
    '''
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=optimize)
    # Input and final output fit in 32 MiB; per-number allocations do not.
    # This is intentionally unsanitized: ASan needs a much larger address space.
    result = subprocess.run([limiter, "--as=33554432", "--core=0", str(executable)],
                            capture_output=True, timeout=15)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("key", ["index", "float(index)"])
def test_numeric_key_tokens_do_not_allocate_per_entry(tmp_path, optimize, key):
    source = transpile_llvm(f'''
        import json
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining
        def main() -> int:
            gc_collect()
            small_count = 0
            for size in [10, 1000]:
                values = {{{key}: index for index in range(size)}}
                expected = json.dumps(values, sort_keys=True)
                arm(100000)
                actual = json.dumps(values, sort_keys=True)
                allocations = 100000 - remaining()
                arm(0)
                assert actual == expected
                if size == 10:
                    small_count = allocations
                else:
                    # Growing output buffers need a few reallocations, not
                    # one string allocation for every key and every value.
                    assert allocations < small_count + 20
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("status", [-1, 0, 64], ids=["libc-error", "empty", "truncated"])
def test_numeric_token_failure_does_not_publish_and_can_retry(tmp_path, optimize, status):
    source = transpile_llvm('''
        import json
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        def main() -> int:
            values = {1: 2, 3: 4}
            expected = json.dumps(values)
            for stage in [1, 2, 3, 4]:
                result = "unchanged"
                caught = False
                arm(stage)
                try:
                    result = json.dumps(values)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result != "unchanged":
                    return 1
                if json.dumps(values) != expected:
                    return 2
            return 0
    ''')
    # This fixture reaches only integer snprintf calls. Inject formatting
    # status rather than allocator failures, including key and value tokens.
    call = "call i32 (ptr, i64, ptr, ...) @snprintf("
    assert call in source
    source = source.replace(call, "call i32 (ptr, i64, ptr, ...) @test.snprintf(")
    source += f'''
@test.remaining = private global i64 0
define private i32 @test.snprintf(ptr %data, i64 %size, ptr %format, i64 %value) {{
  %remaining = load i64, ptr @test.remaining
  %active = icmp sgt i64 %remaining, 0
  br i1 %active, label %count, label %formatting
count:
  %next = sub i64 %remaining, 1
  store i64 %next, ptr @test.remaining
  %deny = icmp eq i64 %next, 0
  br i1 %deny, label %failed, label %formatting
failed:
  ret i32 {status}
formatting:
  %result = call i32 (ptr, i64, ptr, ...) @snprintf(ptr %data, i64 %size, ptr %format, i64 %value)
  ret i32 %result
}}
'''
    executable = LLVM().compile(source, tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, timeout=10)
    actual = result.returncode, result.stdout, result.stderr
    assert actual == (0, b"", b""), actual
