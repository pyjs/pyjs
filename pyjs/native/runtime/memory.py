"""Arena allocation, tracing GC, and identity-map LLVM runtime."""

import textwrap
from functools import cache


@cache
def compiled_arena_runtime() -> tuple[str, ...]:
    from .arena import (
        allocate_collection,
        allocate_in_arena,
        destroy_arena,
        enter_repr,
        initialize,
        leave_repr,
        new_buffer,
        resize_buffer,
    )
    from .compiler import compile_runtime

    return compile_runtime({
        "pyjs.arena.buffer.try.resize": resize_buffer,
        "pyjs.arena.try.alloc": allocate_in_arena,
        "pyjs.arena.buffer.try.new": new_buffer,
        "pyjs.arena.destroy": destroy_arena,
        "pyjs.arena.init": initialize,
        "pyjs.collection.try.alloc": allocate_collection,
        "pyjs.repr.enter": enter_repr,
        "pyjs.repr.try.leave": leave_repr,
    })


@cache
def compiled_heap_runtime() -> tuple[str, ...]:
    from .arena import allocate_in_arena
    from .collector import (
        build_index_in,
        collection_due,
        compare_addresses,
        count_pins,
        disable,
        enable,
        find,
        initialize,
        is_enabled,
        maybe_collect,
        new_heap,
        pin,
        try_collect,
        try_set_threshold,
    )
    from .compiler import compile_runtime
    from .heap import allocate_described
    from .roots import (
        delete_heap,
        destroy_heap,
        module_root,
        push_frame,
        try_pin,
        try_pop_frame,
        unpin,
    )

    return compile_runtime({
        "pyjs.gc.try.alloc.described": allocate_described,
        "pyjs.gc.try.module.root": module_root,
        "pyjs.gc.frame.push": push_frame,
        "pyjs.gc.frame.try.pop": try_pop_frame,
        "pyjs.gc.try.pin": try_pin,
        "pyjs.gc.unpin": unpin,
        "pyjs.gc.destroy": destroy_heap,
        "pyjs.gc.init": initialize,
        "pyjs.gc.try.new": new_heap,
        "pyjs.gc.find": find,
        "pyjs.gc.try.index": build_index_in,
        "pyjs.gc.try.collect": try_collect,
        "pyjs.gc.collection.due": collection_due,
        "pyjs.gc.count": count_pins,
        "pyjs.gc.enable": enable,
        "pyjs.gc.disable": disable,
        "pyjs.gc.is.enabled": is_enabled,
        "pyjs.gc.try.set.threshold": try_set_threshold,
        "pyjs.gc.index.compare": compare_addresses,
        "pyjs.gc.delete": delete_heap,
        "pyjs.gc.maybe.collect": maybe_collect,
        "pyjs.gc.pin": pin,
    }, dependencies={"pyjs.arena.try.alloc": allocate_in_arena})


@cache
def compiled_identity_runtime() -> tuple[str, ...]:
    from .arena import allocate_in_arena
    from .compiler import compile_runtime
    from .identity import get, new_map, put, remove

    return compile_runtime({
        "pyjs.identity.try.new": new_map,
        "pyjs.identity.get": get,
        "pyjs.identity.remove": remove,
        "pyjs.identity.try.put": put,
    }, dependencies={"pyjs.arena.try.alloc": allocate_in_arena})


def identity_map_runtime() -> list[str]:
    return [
        "%pyjs.identity = type { i64, i64, ptr }",
        "%pyjs.identity.entry = type { ptr, ptr }",
        *compiled_identity_runtime(),
    ]


def _required_pointer(name: str, arguments: str, callee: str) -> list[str]:
    # These legacy entry points trap; catchable allocation paths call the
    # underlying try helper directly and retain their located exception edge.
    return [
        f"define ptr @{name}({arguments}) {{",
        "entry:",
        f"  %result = call ptr @{callee}({arguments})",
        "  %failed = icmp eq ptr %result, null",
        "  br i1 %failed, label %out.of.memory, label %done",
        "done:",
        "  ret ptr %result",
        "out.of.memory:",
        "  call void @llvm.trap()",
        "  unreachable",
        "}",
        "",
    ]


def arena_runtime() -> list[str]:
    return [
        "%pyjs.arena = type { ptr, i64, ptr, ptr }",
        "%pyjs.repr.frame = type { ptr, ptr }",
        "%pyjs.arena.chunk = type { ptr, i64, i64, [0 x i8] }",
        "%pyjs.arena.buffer = type { ptr, ptr }",
        "",
        "declare noalias ptr @malloc(i64)",
        "declare ptr @realloc(ptr, i64)",
        "declare void @free(ptr)",
        "",
        *compiled_arena_runtime(),
        *textwrap.dedent('''

                define void @pyjs.repr.leave(ptr %arena, ptr %frame) {
                entry:
                  %ok = call i1 @pyjs.repr.try.leave(ptr %arena, ptr %frame)
                  br i1 %ok, label %pop, label %invalid
                pop:
                  ret void
                invalid:
                  call void @llvm.trap()
                  unreachable
                }
            ''').strip().splitlines(),
        "",
        *_required_pointer("pyjs.collection.alloc",
            "ptr %arena, ptr %allocator, ptr %context, i64 %size", "pyjs.collection.try.alloc"),
        *_required_pointer("pyjs.arena.alloc",
            "ptr %arena, i64 %size, i64 %align", "pyjs.arena.try.alloc"),
        *_required_pointer("pyjs.arena.buffer.new",
            "ptr %arena, i64 %size", "pyjs.arena.buffer.try.new"),
        *_required_pointer("pyjs.arena.buffer.resize",
            "ptr %buffer, i64 %size", "pyjs.arena.buffer.try.resize"),
    ]

def gc_runtime() -> list[str]:
    """Emit a conservative non-moving heap for escaping native objects."""
    return textwrap.dedent(
        """
            %pyjs.gc = type { ptr, ptr, ptr, i64, i64, i1, ptr, i64, ptr, i64, i64 }
            %pyjs.gc.index = type { i64, i64, i64, i1, [0 x ptr] }
            %pyjs.gc.object = type { ptr, i64, i1, ptr, [0 x i8] }
            %pyjs.gc.pin = type { ptr, ptr }
            %pyjs.gc.frame = type { ptr, i64, ptr }
            %pyjs.gc.module.root = type { ptr, i64, ptr }
            %pyjs.gc.descriptor = type { i64, ptr }

            @pyjs.gc.descriptor.atomic = private constant %pyjs.gc.descriptor { i64 0, ptr null }
            @pyjs.gc.descriptor.references = private constant %pyjs.gc.descriptor { i64 -1, ptr @pyjs.gc.trace.references }

            define private ptr @pyjs.gc.trace.references(ptr %object, i64 %index) {
            entry:
              %slot = getelementptr ptr, ptr %object, i64 %index
              %value = load ptr, ptr %slot
              ret ptr %value
            }

            declare noalias ptr @calloc(i64, i64)
            declare void @qsort(ptr, i64, i64, ptr)

            define ptr @pyjs.gc.new() {
            entry:
              %heap = call ptr @pyjs.gc.try.new()
              %failed = icmp eq ptr %heap, null
              br i1 %failed, label %out.of.memory, label %return
            out.of.memory:
              call void @llvm.trap()
              unreachable
            return:
              ret ptr %heap
            }

            define void @pyjs.gc.frame.pop(ptr %heap, ptr %frame) {
            entry:
              %ordered = call i1 @pyjs.gc.frame.try.pop(ptr %heap, ptr %frame)
              br i1 %ordered, label %return, label %invalid
            invalid:
              call void @llvm.trap()
              unreachable
            return:
              ret void
            }

            define ptr @pyjs.gc.alloc.described(
                ptr %heap, i64 %payload.size, ptr %descriptor
            ) {
            entry:
              %result = call ptr @pyjs.gc.try.alloc.described(
                  ptr %heap, i64 %payload.size, ptr %descriptor
              )
              ret ptr %result
            }

            define ptr @pyjs.gc.alloc(ptr %heap, i64 %payload.size) {
            entry:
              %result = call ptr @pyjs.gc.alloc.described(
                  ptr %heap, i64 %payload.size, ptr null
              )
              ret ptr %result
            }

            define ptr @pyjs.gc.alloc.adapter(ptr %heap, i64 %payload.size) {
            entry:
              %result = call ptr @pyjs.gc.alloc(
                  ptr %heap, i64 %payload.size
              )
              ret ptr %result
            }

            define ptr @pyjs.gc.alloc.atomic.adapter(
                ptr %heap, i64 %payload.size
            ) {
            entry:
              %result = call ptr @pyjs.gc.alloc.described(
                  ptr %heap, i64 %payload.size,
                  ptr @pyjs.gc.descriptor.atomic
              )
              ret ptr %result
            }

            define ptr @pyjs.gc.alloc.references.adapter(
                ptr %heap, i64 %payload.size
            ) {
            entry:
              %result = call ptr @pyjs.gc.alloc.described(
                  ptr %heap, i64 %payload.size,
                  ptr @pyjs.gc.descriptor.references
              )
              ret ptr %result
            }

            define void @pyjs.gc.set.threshold(
                ptr %heap, i64 %threshold, i64 %byte.threshold
            ) {
            entry:
              %valid = call i1 @pyjs.gc.try.set.threshold(ptr %heap, i64 %threshold, i64 %byte.threshold)
              br i1 %valid, label %return, label %invalid
            invalid:
              call void @llvm.trap()
              unreachable
            return:
              ret void
            }

            define void @pyjs.gc.collect(ptr %heap) {
            entry:
              %collected = call i1 @pyjs.gc.try.collect(ptr %heap)
              br i1 %collected, label %return, label %failed
            failed:
              call void @llvm.trap()
              unreachable
            return:
              ret void
            }

            """
    ).strip().splitlines() + list(compiled_heap_runtime())
