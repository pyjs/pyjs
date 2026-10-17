"""Heap-local literal defaults and module values, published only when complete."""

import ast
import inspect

from pyjs.analysis.ir import CollectionNew
from pyjs.analysis.lifetime import AllocationLifetime, LifetimeBoundary
from pyjs.analysis.objects import Instance, Module, _literal_state, _literal_value
from pyjs.analysis.value_representation import (
    analyzed_representation,
    set_analyzed_representation,
)
from pyjs.python import native as builtins

from . import collection_ops
from . import dataclasses as dataclass_ops
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported


def scalar_literal(node, origin=None):
    """Return an effect-free scalar constant, including signed numeric syntax."""
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) in {int, float}):
        constant = ast.copy_location(ast.Constant(value=ast.literal_eval(node)), node)
        constant.obj = NATIVE_ENVIRONMENT.builtins.search(type(constant.value).__name__)
        set_analyzed_representation(constant, analyzed_representation(node))
        return constant
    if isinstance(node, ast.Constant):
        if hasattr(node, "obj"):
            return node
        value = ast.copy_location(ast.Constant(value=node.value), origin or node)
        value.obj = NATIVE_ENVIRONMENT.builtins.search(type(node.value).__name__)
        return value
    return None


def literal(node, semantic, origin=None):
    """Validate effect-free initialization and reuse ordinary collection IR.

    Lazy initialization cannot repeat import-time effects or call user code.
    Nested allocations therefore cannot collect before the finished root is
    published; failure leaves its slot empty and partial copies collectible.
    """
    if constant := scalar_literal(node, origin):
        return constant
    name = getattr(semantic, "generic_name", None)
    if (name == "set" and isinstance(node, ast.Call) and not node.args and not node.keywords
            and getattr(getattr(node.func, "obj", None), "py_obj", None) is builtins._set):
        source = ast.copy_location(ast.Set(elts=[]), node)
    elif (name == "frozenset" and isinstance(node, ast.Call) and len(node.args) <= 1 and not node.keywords
            and getattr(getattr(node.func, "obj", None), "py_obj", None) is builtins._frozenset):
        # Reuse set storage without replaying arbitrary constructor effects.
        argument = node.args[0] if node.args else ast.Set(elts=[])
        argument = argument.source if isinstance(argument, CollectionNew) else argument
        if not isinstance(argument, (ast.List, ast.Tuple, ast.Set)):
            raise LLVMUnsupported("native persistent frozensets require literal items", node)
        source = ast.Set(elts=argument.elts)
    elif isinstance(node, ast.Dict):
        source = ast.Dict(keys=node.keys, values=node.values)
    elif isinstance(node, ast.List):
        source = ast.List(elts=node.elts, ctx=ast.Load())
    elif isinstance(node, ast.Tuple):
        source = ast.Tuple(elts=node.elts, ctx=ast.Load())
    elif isinstance(node, ast.Set) and name == "frozenset":
        # The shared storage shape does not authorize an implicit conversion
        # from a mutable source value. Only the checked constructor above does.
        raise LLVMUnsupported("native persistent frozenset literals require the frozenset constructor", node)
    elif isinstance(node, ast.Set):
        source = ast.Set(elts=node.elts)
    else:
        raise LLVMUnsupported("native persistent initializers must contain only literal values", node)
    if name == "dict" and isinstance(source, ast.Dict):
        if any(key is None for key in source.keys):
            raise LLVMUnsupported("native persistent literals do not support dictionary unpacking", node)
        key_type, item_type = semantic.generic_types.values()
        source.keys = [literal(key, key_type, origin) for key in source.keys]
        source.values = [literal(value, item_type, origin) for value in source.values]
    elif name in {"list", "set", "tuple", "frozenset"} and isinstance(source, {
            "list": ast.List, "set": ast.Set, "tuple": ast.Tuple, "frozenset": ast.Set}[name]):
        members = (list(semantic.generic_types.values()) if name == "tuple" and not semantic.tuple_variadic
                   else [collection_ops.item_type(semantic)] * len(source.elts))
        if len(source.elts) != len(members):
            raise LLVMUnsupported("native persistent tuple length does not match its annotation", node)
        source.elts = [literal(value, member, origin) for value, member in zip(source.elts, members, strict=True)]
    else:
        raise LLVMUnsupported("native persistent initializers must contain only literal values", node)
    ast.copy_location(source, origin or node)
    source.obj = semantic
    set_analyzed_representation(source, analyzed_representation(node))
    result = CollectionNew(source)
    set_analyzed_representation(result, analyzed_representation(node))
    result.lifetime = AllocationLifetime(-1, result, LifetimeBoundary.EXTERNAL)
    return ast.copy_location(result, origin or node)


class _LiteralSource(ast.NodeTransformer):
    def visit_CollectionNew(self, node):
        source = self.visit(node.source)
        if node.value_type.generic_name == "frozenset":
            return ast.Call(func=ast.Name(id="frozenset", ctx=ast.Load()), args=[source], keywords=[])
        return source


def prepare(emitter, functions, reached):
    entries = emitter.module.persistent_values
    imported_objects = set()
    for value in sorted((value for value in reached if isinstance(value, Instance)
                         and isinstance(value.container, Module)
                         and getattr(value.cls, "generic_name", None) in {"list", "tuple", "dict", "set", "frozenset"}),
                        key=lambda value: (value.container.name, value.name)):
        try:
            _literal_state(value.py_obj, imported_objects)
        except ValueError:
            raise LLVMUnsupported("native literal roots acquired aliases during import", value.static_value) from None
        entries[value] = len(entries), value.static_value, value.cls
    for function in functions:
        defaults = [*zip(function.params[len(function.params) - len(function.defaults):], function.defaults, strict=True),
                    *zip(function.kwonlyargs, function.kw_defaults, strict=True)]
        for parameter, default in defaults:
            if default is None or isinstance(default, ast.Constant) or dataclass_ops.is_missing(default):
                continue
            semantic = parameter.annotation.obj
            if getattr(semantic, "generic_name", None) not in {"list", "tuple", "dict", "set", "frozenset"}:
                continue
            # The source graph is safe to rebuild only while it still describes
            # the imported function's default. This also covers keyword-only
            # defaults and changes made indirectly by an import-time call.
            source = _LiteralSource().visit(literal(default, semantic))
            actual = inspect.signature(function.py_func).parameters[parameter.arg].default
            try:
                unchanged = _literal_state(_literal_value(source)) == _literal_state(actual, imported_objects)
            except (ValueError, TypeError):
                unchanged = False
            if not unchanged:
                raise LLVMUnsupported("native literal default changed during import", default)
            entries[function, parameter.arg] = len(entries), default, semantic
    for _key, source, semantic in entries.values():
        value = literal(source, semantic)
        emitter.module.uses_collections = True
        for node in ast.walk(value):
            if isinstance(node, CollectionNew):
                if isinstance(node.source, (ast.Dict, ast.Set)):
                    from .mapping_keys import prepare
                    # Reconstructed roots are outside function-body scanning;
                    # retain the same tuple/union-key hash and ordering helpers.
                    prepare(emitter, node)
                    emitter.module.uses_mappings = emitter.module.uses_strings = True
                elif isinstance(node.source, ast.Tuple) and not node.value_type.tuple_variadic:
                    emitter.tuple_type(node.value_type, node)
            elif isinstance(node, ast.Constant):
                emitter.module.uses_strings |= isinstance(node.value, (str, bytes))
                emitter.module.uses_float |= isinstance(node.value, float)


def load(emitter, entry, node):
    key, source, semantic = entry
    initializer = literal(source, semantic, node)
    heap = emitter.load_local("__heap")
    slot = emitter.allocated_value(f"call ptr @pyjs.gc.try.module.root(ptr {heap}, i64 {key})")
    previous = emitter.emit_value(f"load ptr, ptr {slot}")
    missing = emitter.emit_value(f"icmp eq ptr {previous}, null")
    initialize, ready = emitter.new_label("persistent.initialize"), emitter.new_label("persistent.ready")
    emitter.emit_line(f"br i1 {missing}, label %{initialize}, label %{ready}")
    emitter.emit_line(f"{initialize}:")
    _, value = emitter.expression(initializer)
    emitter.emit_line(f"store ptr {value}, ptr {slot}")
    emitter.emit_line(f"br label %{ready}")
    emitter.emit_line(f"{ready}:")
    return "ptr", emitter.emit_value(f"load ptr, ptr {slot}")
