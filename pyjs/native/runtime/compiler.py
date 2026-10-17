"""Compile runtime algorithms without implicit managed contexts or effects."""

import inspect
import re

from pyjs.native.llvm import LLVMUnsupported


def compile_runtime(roots, *, dependencies=None):
    """Compile runtime roots, optionally linking helpers from other libraries."""
    # Imports stay lazy: native builtin declarations import the algorithms
    # while the analyzer itself is still initializing.
    from pyjs.analysis.analyzer import analyze_module, release_compilation
    from pyjs.analysis.objects import Function
    from pyjs.decorators import get_native_decoration, is_declaration
    from pyjs.native.analysis import NATIVE_ENVIRONMENT
    from pyjs.native.llvm import FunctionEmitter, ModuleState

    dependencies = dependencies or {}
    if roots.keys() & dependencies.keys():
        raise LLVMUnsupported("runtime library roots and dependencies must have distinct symbols")
    exports = dependencies | roots
    if not roots or any(
        not inspect.isfunction(function)
        or (decoration := get_native_decoration(function)) is None
        or decoration.kind != "runtime"
        for function in exports.values()
    ):
        raise LLVMUnsupported("runtime library roots require compiled runtime functions")
    first, *remaining = roots.values()
    entry, _ = analyze_module(
        inspect.getmodule(first), entry_point=first,
        additional_entry_points=tuple(remaining), environment=NATIVE_ENVIRONMENT,
    )
    try:
        reached = {
            function
            for root in entry.compilation_entry_points
            for function in root.compilation_objects
            if isinstance(function, Function) and function.ir is not None
        }
        functions = {function for function in reached if FunctionEmitter.is_runtime_helper(function)}
        module = ModuleState("main", "executable", False)
        module.entry_module = entry.container
        module.functions = functions
        module.native_functions = {
            function for function in reached if is_declaration(function.py_func, "native")
        }
        names = {function: name for name, function in exports.items()}
        if len(names) != len(exports):
            raise LLVMUnsupported("runtime functions must have one linker symbol")
        emitter = FunctionEmitter(module)
        namespace = next(iter(roots))
        module.literal_namespace = f"pyjs.runtime.{namespace}"
        module.function_names = {
            function: names.get(function.py_func, f"pyjs.runtime.{namespace}.{emitter.function_name(function)}")
            for function in functions
        }
        definitions = {}
        for function in sorted(functions, key=module.function_names.__getitem__):
            emitter = FunctionEmitter(module)
            lines = emitter.function(function)
            if module.function_names[function] not in exports:
                # Only named library entry points cross the linker boundary.
                # Internal linkage also lets LLVM specialize and eliminate
                # private algorithms rather than treating them as public ABI.
                lines[0] = lines[0].replace("define ", "define internal ", 1)
            # Linked helpers use the same checked ABI; validate their bodies
            # too, but keep their definitions in the supplying library.
            definitions[module.function_names[function]] = lines, emitter.runtime_helper_calls
        # Stop at linked symbols: their private callees belong to the supplying
        # library. Locally needed private helpers have library-specific names.
        pending = list(roots)
        needed = set()
        while pending:
            name = pending.pop()
            if name not in needed and name not in dependencies:
                needed.add(name)
                pending.extend(definitions[name][1])
        # Retain only immutable LLVM text, never an analyzer graph.
        return (*emitter.string_literal_definitions(),
                *(line for name in sorted(needed) for line in definitions[name][0]))
    finally:
        release_compilation(entry)


def validate_runtime_helper(function, emitter, lines=None):
    from .pointers import Pointer

    def reject(reason):
        raise LLVMUnsupported(
            f"runtime helper {function.name}: {reason}", function.original_node,
        )

    if (
        function.cls is not None or function.is_generator or function.is_async
        or function.vararg is not None or function.kwarg is not None
        or function.defaults
        or any(default is not None for default in function.kw_defaults)
        or function is emitter.module.entry_function
    ):
        reject("requires a direct, non-entry function without defaults or captured state")

    def is_unmanaged_scalar(value_type):
        from .wide import WideInt

        return getattr(value_type, "py_obj", None) in {Pointer, WideInt}

    result_kind = getattr(function.return_type, "generic_name", None)
    if result_kind not in {"int", "float", "bool", "NoneType"} and not is_unmanaged_scalar(function.return_type):
        reject("requires a scalar int, float or bool result, raw pointer, or None")
    if any(
        not is_unmanaged_scalar(argument.annotation.obj)
        and getattr(argument.annotation.obj, "generic_name", None) not in {"int", "float", "bool", "bytes", "str"}
        for argument in (*function.params, *function.kwonlyargs)
    ):
        reject("parameters must be scalars, borrowed immutable text, or raw pointers")
    if lines is None:
        return

    # A declaration alone cannot establish absence of implicit managed state.
    # Explicit pointer helpers include the collector itself; callers of that
    # private API must supply valid roots. Check the emitted
    # instructions too, including opaque inline expansions. Except for explicit
    # unmanaged primitives, only direct stack allocations may be written.
    # Short-circuit expressions have scratch slots outside named locals.
    # This intentionally rejects unfamiliar operations rather than silently
    # widening a convention relied on by callers without GC/exception state.
    instructions = "\n".join(lines[2:-1]).splitlines()
    local_slots = {
        match[1] for line in instructions
        if (match := re.match(r"\s*(%[\w.$-]+) = alloca ", line))
    }
    helpers = emitter.runtime_helper_calls | {
        "memcmp", "pyjs.string.length", "llvm.ctlz.i64", "llvm.ctpop.i64", "pow",
        "llvm.fabs.f64", "llvm.copysign.f64", "llvm.floor.f64", "llvm.roundeven.f64",
        "llvm.sqrt.f64", "fma",
    }
    for line in instructions:
        instruction = line.strip()
        if not instruction or instruction.endswith(":"):
            continue
        operation = instruction.split(" = ", 1)[-1]
        if operation in emitter.runtime_primitive_instructions:
            continue
        opcode = operation.split(" ", 1)[0]
        if opcode == "store":
            if operation.rsplit(", ptr ", 1)[-1] not in local_slots:
                reject("cannot write outside local slots")
        elif opcode == "call":
            target = re.fullmatch(r"call (?:void|ptr|float|double|i(?:1|8|16|32|64|128)) @([\w.$-]+)\(.*\)", operation)
            if target is None or target[1] not in helpers:
                reject(f"cannot call an unvalidated runtime dependency: {operation}")
        elif opcode not in {
            "alloca", "load", "getelementptr", "add", "sub", "mul", "udiv", "sdiv", "urem",
            "and", "or", "xor", "shl", "lshr", "ashr", "icmp", "select",
            "zext", "sext", "trunc", "phi", "br", "ret",
            "ptrtoint",
            "inttoptr", "bitcast", "fcmp", "fadd", "fsub", "fmul", "fneg", "fdiv", "frem",
            "sitofp", "uitofp", "fptosi", "fptoui", "fptrunc", "fpext",
        }:
            reject(f"unsupported instruction {opcode!r}")
