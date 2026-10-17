"""Hash dispatch over concrete native values and checked application methods."""

import ast
from functools import cache

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import CallableClass, Class, Function, UnionType
from pyjs.analysis.type_relations import get_type_members
from pyjs.analysis.value_representation import (
    analyzed_representation,
    analyzed_value_object,
)

from . import (
    calls,
    collection_ops,
    dom_ops,
    dom_types,
    enum_ops,
    identity,
    iterator_ops,
    nullable,
    tagged,
)
from . import protocols as iterable_protocols
from .errors import LLVMUnsupported
from .runtime.hashing import NONE_HASH


@cache
def runtime():
    from .runtime import hashing
    from .runtime.compiler import compile_runtime
    return compile_runtime({"pyjs.hash.int": hashing.integer, "pyjs.hash.float": hashing.floating,
                            "pyjs.hash.ordered": hashing.ordered, "pyjs.hash.unordered": hashing.unordered,
                            "pyjs.hash.cached.unordered": hashing.cached_unordered,
                            "pyjs.hash.triple": hashing.triple,
                            "pyjs.hash.range": hashing.range_value})


def protocols(semantic):
    if isinstance(semantic, UnionType):
        members = semantic.types
    elif semantic.container.scope.is_builtins and semantic.generic_name in {"tuple", "frozenset"}:
        members = semantic.generic_types.values()
    elif iterator_ops.is_iterator(semantic) or dom_types.is_opaque_type(semantic):
        return ((semantic, ("__hash__",)),)
    else:
        # Application subclasses can inherit Python-side builtin markers from
        # browser declarations. Their authored hash still needs reachability.
        return ((semantic, ("__hash__",)),) if not semantic.container.scope.is_builtins else ()
    return tuple(protocol for member in members for protocol in protocols(member))


def call(e, node):
    if len(node.args) != 1 or node.keywords:
        raise LLVMUnsupported("LLVM hash takes one positional argument", node)
    source = node.args[0]
    kind, value = e.expression(source)
    return "i64", hash_value(e, analyzed_value_type(source), kind, value, node)


def normalize(e, value):
    reserved = e.emit_value(f"icmp eq i64 {value}, -1")
    return e.emit_value(f"select i1 {reserved}, i64 -2, i64 {value}")


def hash_value(e, semantic, kind, value, node):
    semantic = tagged.effective_type(tagged.runtime_type(semantic), kind)
    if nullable.is_object(semantic):
        raise LLVMUnsupported("LLVM erased object hashing requires narrowing the value", node)
    if tagged.members(semantic):
        return tagged.dispatch(e, semantic, value, "i64",
                               lambda member, storage, item: hash_value(e, member, storage, item, node))
    if nullable.member(semantic):
        return nullable.dispatch(e, semantic, kind, value, "i64", str(NONE_HASH),
                                 lambda member, storage, item: hash_value(e, member, storage, item, node))
    if isinstance(semantic, CallableClass):
        from .callables import hash_value as callable_hash
        return callable_hash(e, semantic, value)
    if (result := reference(e, semantic, kind, value, node)) is not None:
        return result
    # Application names never select builtin physical layouts or hash rules.
    name = enum_ops.scalar_name(semantic) or (None if semantic in e.module.classes else semantic.generic_name)
    if name == "bool":
        return e.emit_value(f"zext i1 {value} to i64")
    if name in {"int", "float"}:
        return e.emit_value(f"call i64 @pyjs.hash.{name}({kind} {value})")
    if name in {"str", "bytes"}:
        return normalize(e, e.emit_value(f"call i64 @pyjs.string.hash(ptr {value})"))
    if name == "NoneType":
        return str(NONE_HASH)
    if name == "range":
        start, stop, step = e.range_values(value)
        return e.emit_value(f"call i64 @pyjs.hash.range(i64 {start}, i64 {stop}, i64 {step})")
    if name == "slice":
        from . import slices
        fields = [hash_value(e, slices.bound_type(), tagged.STORAGE, slices.field(e, value, index), node)
                  for index in range(3)]
        return e.emit_value(f"call i64 @pyjs.hash.triple({', '.join('i64 ' + item for item in fields)})")
    if name in {"tuple", "frozenset"}:
        return container(e, semantic, value, node)
    if name in {"list", "dict", "set"}:
        e.guard_exception(node, "false", "TypeError", f"unhashable type: '{name}'")
        return "0"
    if semantic not in e.module.classes:
        raise LLVMUnsupported(f"LLVM hash is not implemented for {semantic.name}", node)
    return calls.runtime_protocol(e, semantic, value, "i64", lambda candidate: method(e, candidate, node),
                                  lambda method: application(e, method, semantic, value, node), node)


def method(e, candidate, node):
    if candidate.py_obj.__hash__ is None:
        return candidate
    declared = candidate.find_attrs("__hash__")
    if isinstance(declared, Function):
        if declared.is_static:
            raise LLVMUnsupported("LLVM hash requires instance special methods", node)
        # Generated dataclass methods are not analyzed Functions. An inherited
        # Function must not stand in for the generated override Python selects.
        if candidate.py_obj.__hash__ is declared.py_func:
            if declared not in e.module.functions:
                raise LLVMUnsupported("LLVM hash requires a reached __hash__ method", node)
            return declared
    if candidate.py_obj.__hash__ is not object.__hash__:
        # Decorator-generated methods (notably frozen/unsafe dataclasses)
        # are not necessarily modeled Functions. Identity is valid only
        # for the actual object default, never as a missing-body fallback.
        raise LLVMUnsupported("LLVM hash requires a lowered __hash__ method; generated dataclass hashing is not implemented", node)
    return None


def checked_attribute(candidate, node):
    """Reject a generated override absent from the analyzed method table."""
    selected = candidate.py_obj.__hash__
    declared = candidate.find_attrs("__hash__")
    # Function retains static/class descriptors; compare their underlying
    # functions, not a descriptor wrapper or a freshly bound class method.
    if (selected is not None and isinstance(declared, Function)
            and getattr(selected, "__func__", selected) is not getattr(declared.py_func, "__func__", declared.py_func)):
        raise LLVMUnsupported(
            "LLVM hash requires a lowered __hash__ method; generated dataclass hashing is not implemented", node)
    return selected


def check_method_reference(e, node):
    # Unlike calling None, merely retrieving it must not raise TypeError.
    # A stale analyzed Function cannot represent that value in a callable ABI;
    # diagnose the unsupported capture instead of binding its ancestor body.
    semantic = analyzed_value_object(node.value)
    if isinstance(semantic, Class):
        candidates = (semantic,)
    elif e.is_super_call(node.value):
        candidates = (analyzed_value_type(node.value),)
    else:
        members = get_type_members(analyzed_value_type(node.value))
        candidates = (candidate for candidate in e.module.classes
                      if any(collection_ops.is_layout_subclass(candidate, member) for member in members))
    for candidate in candidates:
        if checked_attribute(candidate, node) is None:
            raise LLVMUnsupported("LLVM disabled __hash__ method values require a nullable callable representation", node)


def guard_disabled_method(e, semantic, receiver, node, *, dynamic, positional=None):
    """An analyzed ancestor method does not undo a subclass's disabled hash.

    Keep ordinary binding, defaults and result representations intact. Only
    calls with a possible disabled receiver need a guard; capture supplied
    operands first because calling None still evaluates its arguments.
    """
    def disabled(candidate):
        return checked_attribute(candidate, node) is None

    candidates = (candidate for candidate in e.module.classes
                  if collection_ops.is_layout_subclass(candidate, semantic)) if dynamic else (semantic,)
    if not any(disabled(candidate) for candidate in candidates):
        return node
    captured = calls.capture_operands(e, node, positional)

    def check(is_disabled):
        if is_disabled:
            e.guard_exception(node, "false", "TypeError", "'NoneType' object is not callable")
        return ""

    if dynamic:
        calls.runtime_protocol(e, semantic, receiver, "void", disabled, check, node,
                               compatible=collection_ops.is_layout_subclass)
    else:
        check(disabled(semantic))
    return captured


def explicit_default(e, semantic, kind, value, node, *, base_implementation=False):
    """A selected object method still dispatches normally, except through super."""
    if base_implementation:
        # The lexical parent may disable hashing or inherit a generated method.
        # Bypassing dynamic dispatch is not permission to substitute identity.
        selected = method(e, semantic, node) if semantic in e.module.classes else None
        return "i64", application(e, selected, semantic, value, node, direct=True)
    semantic = tagged.effective_type(tagged.runtime_type(semantic), kind)
    if tagged.members(semantic):
        return "i64", tagged.dispatch(e, semantic, value, "i64",
            lambda member, storage, item: explicit_default(e, member, storage, item, node)[1])
    if nullable.member(semantic):
        return "i64", nullable.dispatch(e, semantic, kind, value, "i64", str(NONE_HASH),
            lambda member, storage, item: explicit_default(e, member, storage, item, node)[1])
    if (result := reference(e, semantic, kind, value, node, direct=True)) is not None:
        return "i64", result
    if semantic in e.module.classes:
        return "i64", calls.runtime_protocol(e, semantic, value, "i64",
            lambda candidate: method(e, candidate, node),
            lambda selected: application(e, selected, semantic, value, node, direct=True), node)
    if collection_ops.builtin_name(semantic) in {"list", "dict", "set"}:
        e.guard_exception(node, "false", "TypeError", "'NoneType' object is not callable")
        return "i64", "0"
    return "i64", hash_value(e, semantic, kind, value, node)


def reference(e, semantic, kind, value, node, *, direct=False):
    """Identity domains retain original objects, not their transport wrappers."""
    if collection_ops.builtin_name(semantic) in {"ValuesView", "WebTokenList", "NotImplementedType"}:
        return application(e, None, semantic, value, node)
    opaque = e.is_opaque_web_element_type(semantic)
    cursor = iterator_ops.is_iterator(semantic)
    if not opaque and not cursor:
        return None
    frame = calls.root_values(e, value)
    candidates = e.module.custom_element_types if opaque else e.module.application_iterators

    def dispatch(source):
        def unknown():
            e.guard_exception(node, "false", "TypeError", "unknown application hash source")
            return "0"

        return calls.runtime_protocol(e, semantic, source, "i64",
            lambda candidate: (method(e, candidate, node), candidate),
            lambda selected: application(e, selected[0], selected[1], source, node, direct=direct), node,
            fallback=(lambda: application(e, None, semantic, source, node)) if opaque else unknown,
            compatible=lambda candidate, target: candidate in candidates
            and iterable_protocols.compatible_source(e, candidate, target))

    result = (iterable_protocols.dispatch_source(e, value, "i64", dispatch,
                lambda: application(e, None, semantic,
                    identity.pointer(e, semantic, kind, value, node), node)) if cursor else dispatch(value))
    calls.pop_roots(e, frame)
    return result


def application(e, method, semantic, value, node, *, direct=False):
    if isinstance(method, Class):
        message = "'NoneType' object is not callable" if direct else f"unhashable type: '{method.name}'"
        e.guard_exception(node, "false", "TypeError", message)
        return "0"
    if method is not None:
        if direct:
            collection_ops.require_declaration_layout(
                method.return_type, analyzed_value_type(node), node,
                actual_representation=method.return_representation,
                expected_representation=analyzed_representation(node))
        invocation = ast.copy_location(ast.Call(func=getattr(node, "func", ast.Name(id=method.name)),
                                               args=[], keywords=[]), node)
        with calls.bind(e, method, invocation) as bound:
            kind, result = calls.invoke(e, method, bound, node, receiver=value)
        if kind == "i1":
            if direct:
                # Ordinary virtual methods reject bool/int signature changes.
                # The builtin object declaration has no emitted vtable slot,
                # so enforce that boundary here instead of erasing True to 1.
                raise LLVMUnsupported("LLVM explicit __hash__ overrides must preserve the int return signature", node)
            result = e.emit_value(f"zext i1 {result} to i64")
        elif kind != "i64":
            raise LLVMUnsupported("LLVM __hash__ must return int", node)
        # Explicit method calls expose the user's return unchanged. Only the
        # hash() protocol reserves -1 and normalizes it to -2.
        return result if direct else normalize(e, result)
    original = dom_ops.pointer(e, semantic, value)
    bits = e.emit_value(f"ptrtoint ptr {original} to i64")
    return normalize(e, e.emit_value(f"lshr i64 {bits}, 4"))


def container(e, semantic, value, node):
    # Hash values are runtime-local (as for randomized Python string hashes).
    # Ordered and commutative kernels preserve the equality/hash invariant.
    from .runtime.sequences import HASH_CACHE

    ordered = semantic.generic_name == "tuple"
    if not ordered:
        from .mapping_keys import uses_callbacks
        from .runtime.mappings import HASHES

        if uses_callbacks(collection_ops.item_type(semantic)):
            # A frozen set hashes the values saved during insertion, not the
            # current state of its members' possibly mutable __hash__ methods.
            address = e.emit_value(f"getelementptr i8, ptr {value}, i64 {HASHES}")
            hashes = e.emit_value(f"load ptr, ptr {address}")
            length = e.emit_value(f"load i64, ptr {value}")
            return e.emit_value(f"call i64 @pyjs.hash.cached.unordered(ptr {hashes}, i64 {length})")
    # Python 3.14 also caches tuple hashes (CPython gh-131525), including
    # tuples with application members; this is not a claim about immutability
    # of those members. A failed callback must leave the cache unpublished.
    cache = e.emit_value(f"getelementptr i8, ptr {value}, i64 {HASH_CACHE}") if ordered else None
    done = e.new_label("hash.done")
    if cache is not None:
        encoded = e.emit_value(f"load i64, ptr {cache}")
        compute = e.new_label("hash.compute")
        e.emit_line(f"br i1 {e.emit_value(f'icmp eq i64 {encoded}, 0')}, label %{compute}, label %{done}")
        e.emit_line(f"{compute}:")
    accumulator = e.emit_value("alloca i64")
    initial = 1469598103934665603 if ordered else 1927868237
    e.emit_line(f"store i64 {initial}, ptr {accumulator}")

    def item(member, current):
        hashed = hash_value(e, member, e.value_type(member), current, node)
        previous = e.emit_value(f"load i64, ptr {accumulator}")
        kernel = "ordered" if ordered else "unordered"
        mixed = e.emit_value(f"call i64 @pyjs.hash.{kernel}(i64 {previous}, i64 {hashed})")
        e.emit_line(f"store i64 {mixed}, ptr {accumulator}")

    collection_ops.loop(e, semantic, value, item, node)
    previous = e.emit_value(f"load i64, ptr {accumulator}")
    length = e.emit_value(f"load i64, ptr {value}")
    result = normalize(e, e.emit_value(f"xor i64 {previous}, {length}"))
    if cache is not None:
        # Publish only after every callback succeeds; zero means uncomputed.
        encoded = e.emit_value(f"add i64 {result}, 1")
        e.emit_line(f"store i64 {encoded}, ptr {cache}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
        return e.emit_value(f"sub i64 {e.emit_value(f'load i64, ptr {cache}')}, 1")
    return result
