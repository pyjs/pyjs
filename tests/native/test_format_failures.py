import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("status", [-1, 0], ids=["libc-error", "short-result"])
def test_float_formatter_failures_do_not_publish_results_and_can_retry(tmp_path, optimize, status):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def render(value: float, wrapped: bool) -> str:
            if wrapped:
                return f"prefix:{value:09.2f}:suffix"
            return format(value, "09.2f")

        def main() -> int:
            gc_set_threshold(1)
            for wrapped in [False, True]:
                expected = render(-1.25, wrapped)
                for stage in [1, 2]:
                    result = "unchanged"
                    caught = False
                    arm(stage)
                    try:
                        result = render(-1.25, wrapped)
                    except MemoryError:
                        caught = True
                    arm(0)
                    gc_collect()
                    if not caught or result != "unchanged":
                        return 1
                    if render(-1.25, wrapped) != expected:
                        return 2
            return 0
    ''')
    # Fail libc sizing/writing separately from allocation. Keep this wrapper
    # private to the executable, never interpose on the host Python formatter.
    declaration = "declare i32 @snprintf(ptr, i64, ptr, ...)"
    assert source.count(declaration) == 1
    assert source.count("@snprintf(") > 1
    source = source.replace("@snprintf(", "@test.snprintf(").replace(
        "declare i32 @test.snprintf(", "declare i32 @snprintf(")
    source += f'''
        @test.remaining = private global i64 0
        define private i32 @test.snprintf(ptr %data, i64 %size, ptr %format, i32 %precision, double %value) {{
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
          %result = call i32 (ptr, i64, ptr, ...) @snprintf(
              ptr %data, i64 %size, ptr %format, i32 %precision, double %value)
          ret i32 %result
        }}
    '''
    executable = LLVM().compile(source, tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, text=True, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize("optimize", [0, 2])
def test_print_conversion_failure_keeps_written_prefix_and_retries(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs import int64, float32
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        def union(value: int | float | None) -> None:
            print("prefix", value, "tail", sep="|", end="!\\n")

        def emit(mode: int) -> int:
            if mode == 0:
                union(-9223372036854775808)
            elif mode == 1:
                union(-0.0)
            elif mode == 2:
                union(42)
            elif mode == 3:
                union(1.25)
            elif mode == 4:
                print("prefix", int64(99), "tail", sep="|", end="!\\n")
            else:
                print("prefix", float32(1.5), "tail", sep="|", end="!\\n")
            return 1

        def main() -> int:
            gc_set_threshold(1)
            for mode in range(6):
                result = 17
                caught = False
                arm(1)
                try:
                    result = emit(mode)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result != 17:
                    return 2
                print("caught")
                if emit(mode) != 1:
                    return 3
            arm(1)
            print("text", True, False, None)
            union(None)
            if remaining() != 1:
                return 4
            arm(0)
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""
    assert result.stdout.decode() == "".join(
        f"prefix|caught\nprefix|{value}|tail!\n"
        for value in ("-9223372036854775808", "-0.0", "42", "1.25", "99", "1.5")
    ) + "text True False None\nprefix|None|tail!\n"
