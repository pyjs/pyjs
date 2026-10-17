import subprocess

from pyjs import llvm
from pyjs.tooling.llvm import LLVM


@llvm.inline("store i64 {value}, ptr @test.remaining")
def arm(value: int) -> None:
    """Fail the nth subsequent allocation once; zero disables injection."""
    raise RuntimeError("allocation injection requires the instrumented LLVM runtime")


@llvm.inline("load i64, ptr @test.remaining")
def remaining() -> int:
    """Read the allocation countdown without allocating or adding a frame."""
    raise RuntimeError("allocation injection requires the instrumented LLVM runtime")


def _fail_allocations(source, managed, *, extra=(), only=None):
    allocators = [
        ("pyjs.arena.try.alloc", "ptr %arena, i64 %size, i64 %align"),
        ("realloc", "ptr %data, i64 %size"),
    ]
    # Escape inference can enable the heap without an explicit gc_* call.
    # Inject into the allocator actually emitted, including that inferred case.
    if managed or "define ptr @pyjs.gc.try.alloc.described(" in source:
        allocators.append((
            "pyjs.gc.try.alloc.described", "ptr %heap, i64 %size, ptr %descriptor",
        ))
    allocators.extend(extra)
    if only is not None:
        selected = set(only)
        if not selected or selected - {name for name, _parameters in allocators}:
            raise ValueError("allocation selection must name at least one known allocator")
        allocators = [(name, parameters) for name, parameters in allocators if name in selected]
    wrappers = []
    for name, parameters in allocators:
        source = source.replace(f"call ptr @{name}(", f"call ptr @test.{name}(")
        wrappers.append(f'''
            define private ptr @test.{name}({parameters}) {{
              %remaining = load i64, ptr @test.remaining
              %active = icmp sgt i64 %remaining, 0
              br i1 %active, label %count, label %allocate
            count:
              %next = sub i64 %remaining, 1
              store i64 %next, ptr @test.remaining
              %deny = icmp eq i64 %next, 0
              br i1 %deny, label %failed, label %allocate
            allocate:
              %result = call ptr @{name}({parameters})
              ret ptr %result
            failed:
              ret ptr null
            }}
        ''')
    return source + "\n".join(wrappers) + "\n@test.remaining = private global i64 0\n"


def run_allocation_case(source, directory, *, managed, optimize, only=None):
    try:
        executable = LLVM().compile(
            _fail_allocations(source, managed, only=only), directory, optimize=optimize,
        )
    except subprocess.CalledProcessError as error:
        error.add_note(f"LLVM: {directory / 'program.ll'}\n{error.stderr}")
        raise
    result = subprocess.run([executable], capture_output=True, timeout=5)
    assert result.returncode == 0, (
        f"native allocation scenario exited {result.returncode} "
        f"({('gc' if managed else 'arena')}, O{optimize})\n"
        f"LLVM: {executable.with_suffix('.ll')}\nExecutable: {executable}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return result
