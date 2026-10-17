"""Checked, call-local buffered output shared by text encoders."""

import ast
import errno

from pyjs.analysis.analyzer import analyzed_value_type

from . import calls, collection_ops
from .errors import LLVMUnsupported
from .runtime.arena import BUFFER_SIZE
from .runtime.buffers import ERROR_OFFSET, OUTPUT_SIZE


def print_call(e, node):
    from . import nullable, representation

    if calls.expands_arguments(node):
        raise LLVMUnsupported("LLVM print argument expansion is not implemented", node)
    sources = [*node.args, *(keyword.value for keyword in node.keywords)]
    kinds = [e.expression_type(source) for source in sources]
    slots, frame = calls.value_slots(e, [kind if kind != "void" else "ptr" for kind in kinds])
    outer, cleanup, done = e.exception_target, e.new_label("print.cleanup"), e.new_label("print.done")
    e.exception_target = cleanup
    try:
        values = []
        # Evaluate every argument, including options, before any conversion or
        # output. Root each value before evaluating the next collecting callback.
        for source, slot in zip(sources, slots, strict=True):
            empty = representation.empty_literal(source)
            kind, value = ("ptr", "@" + e.string_constant(empty)) if empty is not None else e.expression(source)
            values.append((kind, value))
            if kind != "void":
                e.emit_line(f"store {kind} {value}, ptr {slot}")
        options = {"sep": "@" + e.string_constant(" "), "end": "@" + e.string_constant("\n")}
        for keyword, (kind, value) in zip(node.keywords, values[len(node.args):], strict=True):
            semantic = analyzed_value_type(keyword.value)
            name = getattr(semantic, "generic_name", None)
            if keyword.arg == "file":
                if not isinstance(keyword.value, ast.Constant) or keyword.value.value is not None:
                    raise LLVMUnsupported("LLVM print supports only file=None (standard output)", keyword.value)
            elif keyword.arg == "flush":
                if kind != "i1":
                    raise LLVMUnsupported("LLVM print flush must be bool", keyword.value)
                # Descriptor writes are unbuffered; flush still has its ordinary
                # argument evaluation effects, but requires no extra operation.
            elif keyword.arg in options:
                if name == "NoneType":
                    continue
                if name == "str":
                    options[keyword.arg] = value
                elif (member := nullable.member(semantic)) and member.generic_name == "str":
                    present = e.emit_value(f"icmp ne ptr {value}, null")
                    options[keyword.arg] = e.emit_value(f"select i1 {present}, ptr {value}, ptr {options[keyword.arg]}")
                else:
                    raise LLVMUnsupported(f"LLVM print {keyword.arg} requires str or None", keyword.value)
            else:
                raise LLVMUnsupported(f"LLVM print does not support {keyword.arg}=", keyword)

        write_failed, written = e.new_label("print.failed"), e.new_label("print.written")
        failures = []

        def write(value):
            status = e.emit_value(f"call i32 @pyjs.print.string(i32 1, ptr {value})")
            valid = e.emit_value(f"icmp eq i32 {status}, 0")
            failed, checked = e.new_label("print.write.failed"), e.new_label("print.write.checked")
            e.emit_line(f"br i1 {valid}, label %{checked}, label %{failed}")
            e.emit_line(f"{failed}:")
            e.emit_line(f"br label %{write_failed}")
            failures.append(f"[ {status}, %{failed} ]")
            e.emit_line(f"{checked}:")

        for index, (source, (kind, value)) in enumerate(zip(node.args, values[:len(node.args)], strict=True)):
            if index:
                write(options["sep"])
            rendered = (value if representation.empty_literal(source) is not None else
                        representation.render(e, analyzed_value_type(source), kind, value, node, representation=False)[1])
            # Write immediately: if a later conversion raises, Python retains
            # the already written prefix (including the next separator).
            write(rendered)
        write(options["end"])
        e.emit_line(f"br label %{written}")
        e.emit_line(f"{write_failed}:")
        # Share cold activation/trace/root-unwind code across all argument,
        # separator and ending writes. A phi retains the captured errno without
        # stack storage or consulting libc's possibly stale thread-local errno.
        status = e.emit_value(f"phi i32 {', '.join(failures)}")
        e.guard_exception(node, e.emit_value(f"icmp ne i32 {status}, {errno.EPIPE}"),
                          "BrokenPipeError", "[Errno 32] Broken pipe")
        e.raise_error(node, "OSError", "native standard output write failed")
        e.emit_line(f"{written}:")
    finally:
        e.exception_target = outer
    calls.pop_roots(e, frame)
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{e.name(cleanup, 'block')}:")
    calls.restore_roots(e, frame)
    calls.pop_roots(e, frame)
    e.branch_to_exception_target()
    e.emit_line(f"{done}:")
    return "void", ""


class Buffer:
    def __init__(self, emitter, node, *, output=None):
        self.e, self.node = emitter, node
        self.borrowed = output is not None
        if self.borrowed:
            self.output = output
            return
        self.output = emitter.emit_value(f"alloca [{OUTPUT_SIZE} x i8], align 8")
        owner = emitter.emit_value(f"alloca [{BUFFER_SIZE} x i8], align 8")
        emitter.emit_line(f"call void @pyjs.text.output.initialize(ptr {self.output}, ptr {owner})")

    def literal(self, text):
        return "@" + self.e.string_constant(text)

    def append(self, value):
        self.e.emit_line(f"call i32 @pyjs.native.output.append.string(ptr {self.output}, ptr {value})")
        self.check_output()

    def check_output(self):
        slot = self.e.emit_value(f"getelementptr i8, ptr {self.output}, i64 {ERROR_OFFSET}")
        status = self.e.emit_value(f"load i32, ptr {slot}")
        self.e.guard_exception(self.node, self.e.emit_value(f"icmp eq i32 {status}, 0"),
                               "MemoryError", "native text output allocation failed")

    def render(self, write, *roots):
        if self.borrowed:
            raise ValueError("a borrowed output buffer is finished by its owner")
        e = self.e
        frame = calls.root_values(e, *roots)
        outer = e.exception_target
        cleanup, done = e.new_label("output.cleanup"), e.new_label("output.done")
        e.exception_target = cleanup
        try:
            write()
            result = e.allocated_value(f"call ptr @pyjs.text.output.finish(ptr {self.output}, {collection_ops.owner(e)})")
        finally:
            e.exception_target = outer
        e.emit_line(f"call void @pyjs.text.output.destroy(ptr {self.output})")
        calls.pop_roots(e, frame)
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{e.name(cleanup, 'block')}:")
        e.emit_line(f"call void @pyjs.text.output.destroy(ptr {self.output})")
        # Nested callback/root frames may be bypassed by a checked error edge.
        calls.restore_roots(e, frame)
        calls.pop_roots(e, frame)
        e.branch_to_exception_target()
        e.emit_line(f"{done}:")
        return result
