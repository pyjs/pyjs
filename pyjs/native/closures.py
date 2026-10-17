"""Lexical cells and lambda bodies using the ordinary native function ABI.

Cells have a typed value lane followed by an initialization flag. The
owning cell pointer is rooted; local slots are redirected to its value lane.
Closure descriptors embed the callable header followed by captured cell
pointers. Typed tracing retains closure cycles without tracing numeric cells.
"""

import ast
from copy import copy
from dataclasses import dataclass

from pyjs.analysis.ir import Lambda
from pyjs.analysis.lifetime import infer_lifetimes, lambda_captures
from pyjs.analysis.objects import Function, Module
from pyjs.analysis.type_relations import is_subclass
from pyjs.analysis.value_representation import analyzed_numeric_format

from . import callables, gc_layouts, tagged
from .bindings import local_storage_binding
from .errors import LLVMUnsupported


@dataclass
class Cell:
    """Shared compiler metadata for one lexical cell, not a runtime object."""

    owner: Function
    value_type: object
    numeric: object
    storage: str | None = None


@dataclass
class Closure:
    function: Function
    captures: dict[str, Cell]


def walk(node):
    """Walk one executable scope without entering nested lambda bodies."""
    yield node
    if not isinstance(node, ast.Lambda):
        for child in ast.iter_child_nodes(node):
            yield from walk(child)


def prepare(emitter, functions):
    # Appending lifted functions lets all existing preparation passes inspect
    # lambda bodies, including nested lambdas, without another emission path.
    for owner in functions:
        for block in owner.ir.blocks:
            for statement in getattr(block, "body", ()):
                for node in walk(statement):
                    if not isinstance(node, Lambda) or node in emitter.module.lambdas:
                        continue
                    record = getattr(node, "native_replaced_record", None)
                    if record is not None and any(candidate is not record and is_subclass(candidate, record)
                                                  for candidate in emitter.module.classes):
                        raise LLVMUnsupported("native dataclass replacement requires a non-polymorphic record", node)
                    args = node.args
                    if args.defaults or args.kw_defaults or args.kwonlyargs or args.vararg or args.kwarg:
                        raise LLVMUnsupported("LLVM lambdas require fixed positional parameters without defaults", node)
                    callables.signature(emitter, node.obj, node)
                    module = owner.container if isinstance(owner.container, Module) else owner.container.container
                    function = Function(owner.py_func, module)
                    function.name = f"lambda.{len(emitter.module.lambdas)}"
                    function.cls = None
                    function.scope = node.scope
                    function.ir = node.ir
                    function.original_node = node
                    function.lineno = owner.lineno
                    function.return_type = node.obj.return_type
                    function.is_generator = getattr(node, "is_generator", False)
                    function.set_return_representation(node.obj.return_representation)
                    for parameter, value_type, representation in zip(
                        (*args.posonlyargs, *args.args), node.obj.parameter_types,
                        node.obj.parameter_representations, strict=True,
                    ):
                        parameter = copy(parameter)
                        parameter.annotation = value_type.annotation
                        # Lifted parameters already have a resolved type. Keep
                        # it instead of re-resolving synthetic annotation names.
                        parameter.annotation.obj = value_type
                        parameter.representation = representation
                        function.params.append(parameter)
                    captures = {}
                    for name, source in lambda_captures(node).items():
                        # A closure shares its owner's cell, not the narrowed
                        # type visible at the lambda's construction site.
                        inherited = emitter.module.closures.get(owner)
                        cells = emitter.module.cells.setdefault(owner, {})
                        if inherited is not None and name in inherited.captures:
                            cells[name] = inherited.captures[name]
                        elif name not in cells:
                            target = local_storage_binding(owner, source)
                            cells[name] = Cell(owner, target.cls, analyzed_numeric_format(target))
                        # Nested readers share the original cell's physical
                        # layout as well as its semantic declaration.
                        captures[name] = cells[name]
                    closure = Closure(function, captures)
                    emitter.module.lambdas[node] = closure
                    emitter.module.closures[function] = closure
                    emitter.module.function_names[function] = f"pyjs.{function.name}"
                    functions.append(function)
                    emitter.module.functions.add(function)
    if not emitter.module.lambdas:
        return
    # Emitted bodies omit external declarations, but those reached overrides
    # still supply lifetime contracts just as they do for ordinary functions.
    reached = emitter.module.functions | {
        value for value in emitter.module.entry_function.compilation_objects
        if isinstance(value, Function)
    }
    for function in emitter.module.closures:
        function.ir.lifetime = infer_lifetimes(function, function.ir, reached)
    emitter.module.uses_collections = True


def cell_name(name):
    return f"__cell.{name}"


def bindings(emitter):
    function = emitter.current_function
    closure = emitter.module.closures.get(function)
    result = dict(emitter.module.cells.get(function, {}))
    if closure is not None:
        result.update(closure.captures)
    return result


def prepare_locals(emitter):
    for name, cell in bindings(emitter).items():
        if cell.owner is emitter.current_function:
            emitter.slot_types.setdefault(name, emitter.storage_type(cell.value_type, cell.numeric))
        else:
            # prepare() appends lifted readers after their lexical owners.
            # Collection preparation plans them in that order, before emission,
            # so even nested readers see the owner's finalized cell layout.
            assert cell.storage is not None
            emitter.slot_types[name] = cell.storage
        emitter.slot_types[cell_name(name)] = "ptr"
        if cell.numeric is not None:
            emitter.slot_numeric_formats[name] = cell.numeric


def record_storage(emitter):
    for name, cell in bindings(emitter).items():
        if cell.owner is emitter.current_function:
            storage = emitter.slot_types[name]
            # Preparation and emission must not disagree after readers have
            # planned their accesses, including a generator's resume body.
            assert cell.storage is None or cell.storage == storage
            cell.storage = storage


def initialize(emitter, parameters):
    closure = emitter.module.closures.get(emitter.current_function)
    captures = closure.captures if closure is not None else {}
    positions = {name: index for index, name in enumerate(captures, 2)}
    parameters = dict(parameters)
    for name in bindings(emitter):
        kind = emitter.slot_types[name]
        layout = "{ " + ("i8" if kind == "void" else kind) + ", i1 }"
        if name in captures:
            field = emitter.emit_value(
                f"getelementptr ptr, ptr {emitter.load_local('__closure.context')}, i64 {positions[name]}")
            cell = emitter.emit_value(f"load ptr, ptr {field}")
        else:
            cell = gc_layouts.allocate(emitter, ("i8" if kind == "void" else kind, "i1"))
            if kind != "void":
                value = emitter.load_local(name) if name in parameters else "zeroinitializer"
                emitter.emit_line(f"store {kind} {value}, ptr {cell}")
        flag = emitter.emit_value(f"getelementptr {layout}, ptr {cell}, i32 0, i32 1")
        emitter.cell_flags[name] = flag
        if name not in captures and name in parameters:
            emitter.emit_line(f"store i1 true, ptr {flag}")
        emitter.emit_line(f"store ptr {cell}, ptr {emitter.slots[cell_name(name)]}")
        # The collector roots the owning cell, never a stack-local copy of its
        # contents. All subsequent ordinary loads/stores address that cell.
        if kind in {"ptr", tagged.STORAGE}:
            emitter.emit_line(f"store {kind} zeroinitializer, ptr {emitter.slots[name]}")
        emitter.slots[name] = cell
    if closure is not None:
        # Comprehension locals need checked reads even when no nested lambda
        # captures them. Keep their flags on the stack, without allocating cells.
        for name in sorted(getattr(closure.function.original_node, "local_names", ())):
            if name not in emitter.cell_flags and name not in parameters:
                flag = emitter.emit_value("alloca i1")
                emitter.emit_line(f"store i1 false, ptr {flag}")
                emitter.cell_flags[name] = flag


def restore(emitter):
    """Redirect resumed locals to their previously allocated lexical cells."""
    for name in bindings(emitter):
        kind = emitter.slot_types[name]
        layout = "{ " + ("i8" if kind == "void" else kind) + ", i1 }"
        cell = emitter.load_local(cell_name(name))
        emitter.cell_flags[name] = emitter.emit_value(f"getelementptr {layout}, ptr {cell}, i32 0, i32 1")
        emitter.slots[name] = cell


def mark_initialized(emitter, name):
    if name in emitter.cell_flags:
        emitter.emit_line(f"store i1 true, ptr {emitter.cell_flags[name]}")


def check_initialized(emitter, name):
    if name not in emitter.cell_flags:
        return
    closure = emitter.module.closures.get(emitter.current_function)
    captured = closure is not None and name in closure.captures
    kind = "free" if captured else "local"
    message = f"cannot access {kind} variable '{name}' where it is not associated with a value"
    if captured:
        message += " in enclosing scope"
    valid = emitter.emit_value(f"load i1, ptr {emitter.cell_flags[name]}")
    emitter.guard_exception(
        getattr(emitter, "allocation_node", None), valid,
        "NameError" if captured else "UnboundLocalError", message,
    )


def reference(emitter, node):
    closure = emitter.module.lambdas[node]
    value = gc_layouts.allocate(emitter, ("ptr",) * (2 + len(closure.captures)))
    emitter.emit_line(f"store ptr @{emitter.function_name(closure.function)}, ptr {value}")
    context = emitter.emit_value(f"getelementptr ptr, ptr {value}, i64 1")
    emitter.emit_line(f"store ptr {value}, ptr {context}")
    for index, name in enumerate(closure.captures, 2):
        field = emitter.emit_value(f"getelementptr ptr, ptr {value}, i64 {index}")
        emitter.emit_line(f"store ptr {emitter.load_local(cell_name(name))}, ptr {field}")
    return "ptr", value
