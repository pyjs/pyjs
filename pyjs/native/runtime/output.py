"""Buffered and descriptor output LLVM runtime."""

import sys
from functools import cache

from pyjs.native.platform import errno_symbol


@cache
def compiled_write_runtime() -> tuple[str, ...]:
    from .buffers import write_all
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.write.all": write_all})


@cache
def compiled_print_runtime() -> tuple[str, ...]:
    from .buffers import write_all
    from .compiler import compile_runtime
    from .traces import write_string

    return compile_runtime({"pyjs.print.string": write_string}, dependencies={
        "pyjs.write.all": write_all,
    })


@cache
def compiled_output_runtime() -> tuple[str, ...]:
    from .arena import allocate_in_arena, new_buffer, resize_buffer
    from .buffers import (
        append_bytes,
        append_string,
        finish_memory,
        flush,
        new_output,
        reserve_memory,
        write_all,
    )
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.native.output.append.bytes": append_bytes,
        "pyjs.native.output.flush": flush,
        "pyjs.native.output.try.new": new_output,
        "pyjs.native.output.append.string": append_string,
        "pyjs.native.output.try.finish.memory": finish_memory,
        "pyjs.native.output.reserve.memory": reserve_memory,
    }, dependencies={
        "pyjs.arena.buffer.try.resize": resize_buffer,
        "pyjs.write.all": write_all,
        "pyjs.arena.try.alloc": allocate_in_arena,
        "pyjs.arena.buffer.try.new": new_buffer,
    })


def write_all_runtime() -> list[str]:
    # _write uses unsigned 32-bit counts and signed 32-bit results, unlike
    # POSIX ssize_t/size_t. Keep the algorithm's i64 interface and cap each
    # partial write; write_all already handles progress and retries.
    write = ["declare i64 @write(i32, ptr, i64)"]
    if sys.platform == "win32":
        write = [
            "declare i32 @_write(i32, ptr, i32)",
            "declare ptr @_set_thread_local_invalid_parameter_handler(ptr)",
            # UCRT otherwise terminates the process on an invalid descriptor.
            # Scope the handler to this call/thread and restore both it and
            # errno; never replace the embedding application's global handler.
            "define private void @pyjs.write.invalid(ptr %expression, ptr %function, ptr %file, i32 %line, i64 %reserved) {",
            "  ret void",
            "}",
            "define internal i64 @write(i32 %fd, ptr %data, i64 %size) {",
            "  %large = icmp ugt i64 %size, 2147483647",
            "  %bounded = select i1 %large, i64 2147483647, i64 %size",
            "  %count = trunc i64 %bounded to i32",
            "  %previous = call ptr @_set_thread_local_invalid_parameter_handler(ptr @pyjs.write.invalid)",
            "  %result = call i32 @_write(i32 %fd, ptr %data, i32 %count)",
            "  %errno = call ptr @_errno()",
            "  %saved = load i32, ptr %errno",
            "  %ignored = call ptr @_set_thread_local_invalid_parameter_handler(ptr %previous)",
            "  store i32 %saved, ptr %errno",
            "  %wide = sext i32 %result to i64",
            "  ret i64 %wide",
            "}",
        ]
    return [
        *write,
        f"declare ptr @{errno_symbol()}()",
        *compiled_write_runtime(),
    ]


@cache
def exception_runtime() -> tuple[str, ...]:
    from .arena import allocate_in_arena
    from .buffers import write_all
    from .compiler import compile_runtime
    from .traces import prepend, write_trace

    return compile_runtime({
        "pyjs.exception.prepend": prepend,
        "pyjs.exception.write.trace": write_trace,
    }, dependencies={
        "pyjs.arena.try.alloc": allocate_in_arena,
        "pyjs.write.all": write_all,
    })


@cache
def exception_message_runtime() -> tuple[str, ...]:
    from .compiler import compile_runtime
    from .error_messages import repr_string
    from .text_operations import new_owned

    return compile_runtime({"pyjs.exception.key.repr": repr_string}, dependencies={
        "pyjs.string.new.owned": new_owned,
    })


def output_runtime() -> list[str]:
    return [
        "%pyjs.native.output = type { ptr, ptr, i64, i64, i32, i32, ptr }",
        *compiled_output_runtime(),
    ]
