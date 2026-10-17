"""Native object boundaries: application identity and scalar/reference boxes."""

import ast
from contextlib import contextmanager

from pyjs.analysis.analyzer import (
    analyzed_value_object,
    analyzed_value_type,
    get_type_members,
)
from pyjs.analysis.iterable_protocol import is_abstract_iterable, is_abstract_iterator
from pyjs.analysis.objects import (
    CallableClass,
    Class,
    Function,
    GenericClass,
    Instance,
    StaticCast,
    UnionType,
)
from pyjs.analysis.type_relations import is_subclass, same_analyzer_type
from pyjs.analysis.value_representation import (
    analyzed_representation,
    representation_for_member,
    representations_conflict,
)
from pyjs.python import native as native_builtins

from . import calls, collection_ops, enum_ops, gc_layouts, nullable, tagged
from .bindings import local_storage_binding
from .errors import LLVMUnsupported

REFERENCES = ("str", "bytes", "list", "tuple", "dict", "set", "frozenset", "range", "dom", "slice")


def runtime_name(semantic):
    from .dom_types import is_opaque_type

    # Opaque DOM nodes have an arena layout, not an application type header.
    # Box them at erased boundaries just like builtin reference payloads.
    return "dom" if is_opaque_type(semantic) else collection_ops.builtin_name(semantic)


def check_static_cast(node, *, classes=None):
    """Validate finalized cast types; emission also requires available layouts."""
    actual, expected = analyzed_value_type(node.value), analyzed_value_type(node)
    if nullable.is_object(actual) and runtime_name(expected) == "dom":
        from pyjs.web.dom import Element
        if getattr(node, "native_dom_cast", None) is not Element:
            raise LLVMUnsupported("LLVM erased DOM narrowing supports Element, not concrete DOM interfaces", node)
    if nullable.is_object(actual) or nullable.is_object(expected):
        return  # Boxing and checked runtime narrowing are handled by emission.
    collection_ops.require_matching_layout(actual, expected, node)
    if isinstance(actual, UnionType):
        if representations_conflict(((actual, analyzed_representation(node.value)),
                                     (expected, analyzed_representation(node)))):
            raise LLVMUnsupported("native union casts require matching representations", node)
        return  # Emission checks the selected runtime tag and payload layout.
    upcast = isinstance(actual, Class) and isinstance(expected, Class) and is_subclass(actual, expected)
    if classes is None:
        upcast = upcast and not actual.container.scope.is_builtins
    else:
        from .dom_types import is_opaque_type
        upcast = upcast and actual in classes and (expected in classes or is_opaque_type(expected))
    upcast |= is_abstract_iterator(actual) and is_abstract_iterator(expected)
    if not same_analyzer_type(actual, expected) and not upcast:
        raise LLVMUnsupported("native concrete casts require matching types or an application upcast", node)
    if analyzed_representation(node.value) != analyzed_representation(node):
        raise LLVMUnsupported("native concrete casts require matching representations", node)


def needs_result_check(actual, expected):
    """A selected signature alone does not prove its erased/union result type."""
    return ((nullable.is_object(actual) and not nullable.is_object(expected))
            or isinstance(actual, UnionType) and not same_analyzer_type(actual, expected))


class ResultProjection(ast.expr):
    """A compiler-declared result recovered from object transport, not a cast."""

    _fields = ("value",)

    def __init__(self, value, expected, representation):
        self.value = value
        self.obj = expected
        self.representation = representation


def instance_type(node):
    """Return an instance's semantic type, or None for a class-valued name.

    Exception class tokens have a separate native ABI, not an erased-object
    box. Querying their type would lazily construct type[T] after analysis has
    finished, making emission depend on previous compilations in this process.
    Other class values are rejected by expression emission, not materialized.
    """
    if (isinstance(node, (ast.Name, ast.Attribute))
            and isinstance(analyzed_value_object(node), (Class, GenericClass))):
        return None
    return analyzed_value_type(node)


@contextmanager
def converted_values(e, items, representations=None):
    """Convert into declared slots and root new boxes/views across later items.

    Target representations are separate from each expression's source witness:
    a generator view can change its send contract while retaining its yields.
    """
    items = tuple(items)
    representations = (None,) * len(items) if representations is None else tuple(representations)
    roots, frame = calls.object_argument_roots(e, (expected for _, expected in items))
    values = []
    for index, ((source, expected), representation) in enumerate(zip(items, representations, strict=True)):
        kind, value = e.coerce_value(*e.expression(source), e.value_type(expected), source,
                                     semantic=expected, representation=representation)
        if index in roots:
            e.emit_line(f"store ptr {value}, ptr {roots[index]}")
        values.append((kind, value))
    yield values
    calls.pop_roots(e, frame)


def projects_result(node):
    """Intrinsic calls whose typed result crosses an implicit object boundary."""
    return isinstance(node, ResultProjection) or (isinstance(node, ast.Call)
            and getattr(analyzed_value_object(node.func), "py_func", None) is native_builtins._Generator.close
            and collection_ops.builtin_name(analyzed_value_type(node)) != "NoneType")


def needed(classes, functions):
    types = (
        *(field.value_type for layout in classes for field in layout.fields),
        *(function.return_type for function in functions),
        *(parameter.annotation.obj for function in functions for parameter in calls.parameters(function)),
        *(value.cls for function in functions for value in function.scope.names.values()
          if isinstance(value, Instance)),
    )
    return (any(nullable.contains(semantic, "object") for semantic in types)
            or any(projects_result(node)
                   or (isinstance(node, ast.Call)
                       and getattr(analyzed_value_object(node.func), "py_func", None) is native_builtins._type_is)
                   # A temporary opaque result (e.g. a dataclass factory's
                   # missing sentinel) needs identity helpers without a slot.
                   or (isinstance(node, ast.Call) and nullable.is_object(analyzed_value_type(node)))
                   or (isinstance(node, StaticCast) and nullable.contains(analyzed_value_type(node), "object"))
                   or (isinstance(node, (ast.Name, ast.arg))
                       and nullable.contains(getattr(local_storage_binding(function, node), "cls", None), "object"))
                   or any(nullable.is_object(semantic) for semantic, _ in getattr(node, "runtime_protocols", ()))
                   for function in functions for node in nodes((function,))))


def nodes(functions):
    for function in functions:
        for block in function.ir.blocks:
            for statement in getattr(block, "body", ()):
                yield from ast.walk(statement)


def needs_headers(functions):
    from .type_queries import query_callable

    # Passing an opaque pointer or boxing a scalar does not inspect application
    # headers. Keep borrowed host records headerless unless a runtime type
    # consumer actually needs identity (the same policy as virtual dispatch).
    for node in nodes(functions):
        if projects_result(node):
            return True
        # Every protocol on an erased receiver dispatches by runtime identity,
        # including __index__ on classes with no inheritance hierarchy.
        if any(nullable.is_object(semantic)
               for semantic, _ in getattr(node, "runtime_protocols", ())):
            return True
        if isinstance(node, StaticCast) and nullable.is_object(instance_type(node.value)):
            return True
        if not isinstance(node, ast.Call):
            continue
        target = analyzed_value_object(node.func)
        if isinstance(target, Function):
            from pyjs.decorators import get_native_decoration
            decoration = get_native_decoration(target.py_func)
            if ((decoration is not None and decoration.operation in {"element", "tag"}
                 or target.py_func in {native_builtins._WebElement.append, native_builtins._WebElement.replaceChildren})
                    and any(nullable.contains(instance_type(arg.value if isinstance(arg, ast.Starred) else arg), "object")
                            for arg in node.args)):
                return True  # Erased builder/mutation children dispatch application headers.
        if (target in functions and nullable.is_object(target.return_type)
                and not nullable.is_object(analyzed_value_type(node))):
            return True
        if (getattr(target, "py_obj", None) is native_builtins._bool and node.args
                and nullable.is_object(instance_type(node.args[0]))):
            return True
        if not isinstance(target, Function):
            continue
        if target.py_func in {native_builtins._same_dataclass_type, native_builtins._type_is}:
            return True
        if (target.py_func in {native_builtins._id, query_callable} and node.args
                and nullable.contains(instance_type(node.args[0]), "object")):
            return True
        if (target.name in {"__is__", "__is_not__"} and isinstance(node.func, ast.Attribute)
                and any(nullable.contains(instance_type(value), "object")
                        for value in (node.func.value, *node.args))):
            return True
        if (target.py_func is native_builtins._isinstance and node.args
                and nullable.contains(instance_type(node.args[0]), "object")):
            return True
    return False


def definitions(e):
    if not e.module.uses_erased_objects:
        return []
    from .runtime.objects import compiled_object_runtime

    types = runtime_types(e)
    return [
        "%pyjs.object.scalar = type { ptr, i64 }",
        "%pyjs.object.reference = type { ptr, ptr, i64, i64 }",
        "@pyjs.object.type.int = private constant { ptr } { ptr null }",
        "@pyjs.object.type.bool = private constant { ptr } { ptr @pyjs.object.type.int }",
        "@pyjs.object.type.float = private constant { ptr } { ptr null }",
        "@pyjs.object.type.NotImplementedType = private constant { ptr } { ptr null }",
        *(f"@pyjs.object.type.{name} = private constant {{ ptr }} {{ ptr null }}" for name in REFERENCES),
        "@pyjs.object.bool.false = private constant %pyjs.object.scalar { ptr @pyjs.object.type.bool, i64 0 }",
        "@pyjs.object.bool.true = private constant %pyjs.object.scalar { ptr @pyjs.object.type.bool, i64 1 }",
        f"@pyjs.object.types = private constant [{len(types)} x ptr] [{', '.join(types)}]",
        f"@pyjs.object.references = private constant [{len(REFERENCES)} x ptr] "
        f"[{', '.join(f'ptr @pyjs.object.type.{name}' for name in REFERENCES)}]",
        *compiled_object_runtime(),
    ]


def runtime_types(e):
    return [*(f"ptr @pyjs.object.type.{name}" for name in ("bool", "int", "float", "NotImplementedType", *REFERENCES)),
            *(f"ptr @{e.vtable_name(value)}" for value in e.module.vtable_roots)]


def instancecheck(e, value, expected, node):
    name = runtime_name(expected)
    if name == "object":
        return "true"
    if name == "NoneType":
        return e.emit_value(f"icmp eq ptr {value}, null")
    if name in {"bool", "int", "float", "NotImplementedType", *REFERENCES}:
        symbol = f"pyjs.object.type.{name}"
    elif expected in e.module.vtable_roots:
        symbol = e.vtable_name(expected)
    else:
        raise LLVMUnsupported("LLVM erased isinstance requires a supported scalar, reference or application class", node)
    matched = e.emit_value(
        f"call i1 @pyjs.runtime.isinstance.with.types(ptr {value}, "
        f"ptr @{symbol}, ptr @pyjs.object.types, i64 {len(runtime_types(e))})"
    )
    if name == "dom":
        if expected.py_obj is not native_builtins._WebElement:
            raise LLVMUnsupported("LLVM erased DOM narrowing supports Element, not concrete DOM interfaces", node)
        for cls in e.module.custom_element_types:
            if cls not in e.module.vtable_roots:
                continue
            custom = e.emit_value(f"call i1 @pyjs.runtime.isinstance.with.types(ptr {value}, "
                                  f"ptr @{e.vtable_name(cls)}, ptr @pyjs.object.types, i64 {len(runtime_types(e))})")
            matched = e.emit_value(f"or i1 {matched}, {custom}")
    return matched


def runtime_identity(e, value):
    return e.emit_value(
        f"call ptr @pyjs.runtime.typeof.with.types(ptr {value}, "
        f"ptr @pyjs.object.types, i64 {len(runtime_types(e))})")


def same_type(e, left, right):
    a, b = runtime_identity(e, left), runtime_identity(e, right)
    known = e.emit_value(f"icmp ne ptr {a}, null")
    equal = e.emit_value(f"icmp eq ptr {a}, {b}")
    return e.emit_value(f"and i1 {known}, {equal}")


def truth(e, value, node):
    from .analysis import NATIVE_ENVIRONMENT

    # The type helper is null-safe. A scalar/reference fallback must still run
    # when all application classes share one protocol implementation.
    identity = e.emit_value(
        f"call ptr @pyjs.runtime.typeof.with.types(ptr {value}, "
        f"ptr @pyjs.object.types, i64 {len(runtime_types(e))})")

    def builtin():
        permitted = e.emit_value(f"icmp ne ptr {identity}, @pyjs.object.type.NotImplementedType")
        e.guard_exception(node, permitted, "TypeError", "NotImplemented should not be used in a boolean context")
        return e.emit_value(
            f"call i1 @pyjs.object.scalar.truth.with.types(ptr {value}, "
            f"ptr @pyjs.object.type.bool, ptr @pyjs.object.type.int, ptr @pyjs.object.type.float, "
            f"ptr @pyjs.object.references, i64 {len(REFERENCES)})")

    return calls.runtime_protocol(e, NATIVE_ENVIRONMENT.builtins.search("object"), value, "i1",
        lambda candidate: e.truth_method(candidate, node),
        lambda method: e.application_truth(method, value, node), node,
        identity=identity, fallback=builtin)


def check_narrowing(e, value, expected, node, *, check_layout=True):
    if nullable.is_object(expected):
        return
    valid = (e.emit_value(f"icmp eq ptr {value}, null") if collection_ops.builtin_name(expected) == "NoneType"
             else instancecheck(e, value, expected, node))
    e.guard_exception(node, valid, "TypeError", "object value changed after narrowing")
    if (check_layout and collection_ops.builtin_name(expected) in REFERENCES
            and expected.generic_types is not None):
        # The root kind alone is insufficient: list[bool] and list[int] have
        # different strides, as do fixed tuple shapes and represented items.
        # The empty tuple's concrete token is zero, not a bare-container cast.
        expected_layout = layout_token(e, expected, analyzed_representation(node)) if expected.generic_types else 0
        slot = e.emit_value(f"getelementptr %pyjs.object.reference, ptr {value}, i32 0, i32 3")
        actual_layout = e.emit_value(f"load i64, ptr {slot}")
        e.guard_exception(node, e.emit_value(f"icmp eq i64 {actual_layout}, {expected_layout}"),
                          "TypeError", "erased reference has a different declared layout")


def layout_token(e, semantic, representation):
    key = semantic, representation
    return e.module.erased_layouts.setdefault(key, len(e.module.erased_layouts) + 1)


def convert(e, kind, value, expected, node, *, actual=None, representation=None):
    if not nullable.is_object(expected):
        return None
    if kind == "void":
        return "ptr", "null"
    if actual is None:
        actual = e.value_semantics.get((kind, value))
        representation = e.value_representations.get((kind, value))
    # Callable and iteration descriptors are not ordinary object boxes. Keep
    # their exclusions here so direct consumers cannot bypass the adapters
    # and interpret descriptor fields as an erased object's type header.
    # Check the value's semantic, not the fallback location node: synthesized
    # callbacks use an enclosing map/filter/groupby call to locate diagnostics,
    # but their already-boxed result is not that call's Iterator descriptor.
    for member in get_type_members(actual) if actual is not None else ():
        if isinstance(member, CallableClass):
            raise LLVMUnsupported("LLVM callable erasure to object is not implemented", node)
        if is_abstract_iterator(member):
            raise LLVMUnsupported("LLVM iterator handles cannot yet be erased to object; keep Iterator typing", node)
        if is_abstract_iterable(member):
            raise LLVMUnsupported("LLVM Iterable views cannot yet be erased to object", node)
    if actual is None and hasattr(node, "obj"):
        actual = instance_type(node)
        representation = analyzed_representation(node)
    enum_ops.check_type_conversion(actual, expected, node)
    if representation is not None and representation.direct_numeric_formats:
        raise LLVMUnsupported("native object boxing requires explicit int() or float() conversion of represented scalars", node)
    if kind in {"i1", "i64", "double"}:
        # Storage determines a scalar box's runtime type even when the caller
        # supplies an annotated destination rather than its source expression.
        # Register the same type that the boxing branch below writes.
        from .analysis import NATIVE_ENVIRONMENT
        actual = NATIVE_ENVIRONMENT.builtins.search({"i1": "bool", "i64": "int", "double": "float"}[kind])
    if actual is not None and not nullable.is_object(actual) and not isinstance(actual, UnionType):
        e.module.erased_candidates[actual, representation] = None
    if kind == "ptr":
        if nullable.member(actual) is not None:
            return "ptr", nullable.dispatch(e, actual, kind, value, "ptr", "null",
                lambda member, storage, payload: convert(e, storage, payload, expected, node, actual=member,
                    representation=representation_for_member(actual, representation, member))[1])
        name = runtime_name(tagged.runtime_type(actual)) if actual is not None else None
        if name in REFERENCES:
            joined = None
            if name == "dom" and e.module.custom_element_types:
                # Opaque DOM transport may already contain an ordinary managed
                # application object. Preserve its header/protocols; only plain
                # arena nodes need an erased reference box.
                identity = e.emit_value(f"call ptr @pyjs.native.element.type(ptr {value}, "
                                        f"ptr @pyjs.dom.types, i64 {len(e.module.custom_element_types)})")
                custom = e.emit_value(f"icmp ne ptr {identity}, null")
                joined = e.emit_value("alloca ptr")
                done, box = e.new_label("dom.object.done"), e.new_label("dom.object.box")
                e.emit_line(f"store ptr {value}, ptr {joined}")
                e.emit_line(f"br i1 {custom}, label %{done}, label %{box}")
                e.emit_line(f"{box}:")
            # Keep payload identity separate from its erased type header.
            # The box traces the payload; -1 reads its live length header.
            roots = calls.root_values(e, value)
            pointer = gc_layouts.allocate(e, ("ptr", "ptr", "i64", "i64"), layout="%pyjs.object.reference")
            e.emit_line(f"store ptr @pyjs.object.type.{name}, ptr {pointer}")
            layout = layout_token(e, actual, representation) if actual.generic_types else 0
            length = "1" if name in {"dom", "slice"} else "-1"
            if name == "range":
                arguments = ", ".join(f"i64 {part}" for part in e.range_values(value))
                count = e.emit_value(f"call i128 @pyjs.range.length.i128({arguments})")
                # Ranges are immutable and may exceed i64 length. Cache only
                # empty/nonempty truth, never truncate their logical count.
                present = e.emit_value(f"icmp ne i128 {count}, 0")
                length = e.emit_value(f"zext i1 {present} to i64")
            for index, storage, payload in ((1, "ptr", value), (2, "i64", length), (3, "i64", str(layout))):
                slot = e.emit_value(f"getelementptr %pyjs.object.reference, ptr {pointer}, i32 0, i32 {index}")
                e.emit_line(f"store {storage} {payload}, ptr {slot}")
            calls.pop_roots(e, roots)
            if joined is not None:
                e.emit_line(f"store ptr {pointer}, ptr {joined}")
                e.emit_line(f"br label %{done}")
                e.emit_line(f"{done}:")
                pointer = e.emit_value(f"load ptr, ptr {joined}")
            return "ptr", pointer
        return kind, value
    if kind == tagged.STORAGE:
        actual = tagged.effective_type(actual, kind)
        return "ptr", tagged.dispatch(e, actual, value, "ptr",
            lambda member, storage, payload: convert(e, storage, payload, expected, node, actual=member,
                representation=representation_for_member(actual, representation, member))[1])
    if nullable.payload_kind(kind):
        return "ptr", nullable.dispatch(e, actual, kind, value, "ptr", "null",
            lambda member, storage, payload: convert(e, storage, payload, expected, node, actual=member,
                representation=representation_for_member(actual, representation, member))[1])
    if kind == "i1":
        return "ptr", e.emit_value(
            f"select i1 {value}, ptr @pyjs.object.bool.true, ptr @pyjs.object.bool.false")
    if kind not in {"i64", "double"}:
        raise LLVMUnsupported("LLVM object boxing requires a concrete scalar or reference", node)
    # Only the erased boundary allocates; typed arithmetic remains unboxed.
    pointer = gc_layouts.allocate(e, ("ptr", "i64"), layout="%pyjs.object.scalar")
    name = "int" if kind == "i64" else "float"
    bits = value if kind == "i64" else e.emit_value(f"bitcast double {value} to i64")
    e.emit_line(f"store ptr @pyjs.object.type.{name}, ptr {pointer}")
    slot = e.emit_value(f"getelementptr %pyjs.object.scalar, ptr {pointer}, i32 0, i32 1")
    e.emit_line(f"store i64 {bits}, ptr {slot}")
    return "ptr", pointer


def narrow(e, value, expected, node, *, check_layout=True, check_representation=True):
    if isinstance(expected, UnionType) and not nullable.is_object(expected):
        return project(e, value, expected, node, check_layout=check_layout)
    representation = analyzed_representation(node)
    if check_representation and representation is not None and representation.direct_numeric_formats:
        # Ordinary scalar boxes record kind, not portable width. Authored casts
        # cannot invent that width; compiler-declared completion transport has
        # already validated it before erasing scalar arithmetic for boxing.
        raise LLVMUnsupported("LLVM erased scalar casts cannot introduce a portable representation", node)
    check_narrowing(e, value, expected, node, check_layout=check_layout)
    if nullable.is_object(expected):
        return "ptr", value
    name = runtime_name(expected)
    if name == "NoneType":
        return "void", ""
    if name in REFERENCES:
        return "ptr", unbox_reference(e, value)
    if name not in {"bool", "int", "float"}:
        return "ptr", value
    slot = e.emit_value(f"getelementptr %pyjs.object.scalar, ptr {value}, i32 0, i32 1")
    bits = e.emit_value(f"load i64, ptr {slot}")
    if name == "int":
        # An isinstance(int) proof includes bool. Reuse the tagged numeric
        # representation until the consumer requests numeric conversion.
        identity = e.emit_value(f"load ptr, ptr {value}")
        boolean = e.emit_value(f"icmp eq ptr {identity}, @pyjs.object.type.bool")
        tag = e.emit_value(f"select i1 {boolean}, i64 1, i64 2")
        result = e.emit_value(f"insertvalue {tagged.STORAGE} zeroinitializer, i64 {tag}, 0")
        return tagged.STORAGE, e.emit_value(f"insertvalue {tagged.STORAGE} {result}, i64 {bits}, 1")
    kind, operation = ("i1", "trunc") if name == "bool" else ("double", "bitcast")
    return kind, e.emit_value(f"{operation} i64 {bits} to {kind}")


def project(e, value, expected, node, *, check_layout=True, on_mismatch=None):
    """Recover a checked union or compiler-declared result from object transport.

    Check each member's kind and layout before exposing its payload in typed
    storage, for both authored casts and compiler-declared result contracts.
    """
    if nullable.is_object(expected):
        return "ptr", value
    storage = e.value_type(expected)
    result = e.emit_value(f"alloca {storage}")
    done = e.new_label("object.result")
    representation = analyzed_representation(node)
    for member in get_type_members(expected):
        member_representation = representation_for_member(expected, representation, member)
        selected, other = e.new_label("object.member"), e.new_label("object.other")
        valid = instancecheck(e, value, member, node)
        e.emit_line(f"br i1 {valid}, label %{selected}, label %{other}")
        e.emit_line(f"{selected}:")
        source = tagged.Value(node, member, "ptr", value)
        source.representation = member_representation
        kind, item = narrow(e, value, member, source, check_layout=check_layout,
                            check_representation=not projects_result(node))
        if kind == tagged.STORAGE and storage != tagged.STORAGE:
            # isinstance(int) also accepts bool, but integer-only storage cannot
            # preserve its identity. Do not turn True into 1 at this boundary;
            # use a bool | int result contract or an explicit int() in the body.
            number, _ = tagged.parts(e, item)
            valid = e.emit_value(f"icmp eq i64 {number}, {tagged.TAGS['int']}")
            e.guard_exception(node, valid, "TypeError", tagged.INTEGER_BOUNDARY)
            kind, item = tagged.numeric(e, source, kind, item)
        e.value_semantics[kind, item] = member
        _, item = e.coerce_value(kind, item, storage, source, semantic=expected)
        e.emit_line(f"store {storage} {item}, ptr {result}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{other}:")
    if on_mismatch is None:
        e.guard_exception(node, "false", "TypeError", "object value changed after narrowing")
    else:
        # Argument collection can defer a kind mismatch until all operands and
        # binding errors have been observed. The placeholder is never consumed
        # by the callee; this does not suppress nested layout/representation errors.
        on_mismatch()
        e.emit_line(f"store {storage} zeroinitializer, ptr {result}")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return storage, e.emit_value(f"load {storage}, ptr {result}")


def unbox_reference(e, value):
    return e.emit_value(
        f"call ptr @pyjs.object.reference.value.with.types(ptr {value}, "
        f"ptr @pyjs.object.references, i64 {len(REFERENCES)})")


def known_payload(e, value, semantic):
    """Decode an exact, already checked runtime kind (not an isinstance proof)."""
    name = runtime_name(semantic)
    if name == "NoneType":
        return ""
    if name in REFERENCES:
        return unbox_reference(e, value)
    if name not in {"int", "bool", "float"}:
        return value
    slot = e.emit_value(f"getelementptr %pyjs.object.scalar, ptr {value}, i32 0, i32 1")
    bits = e.emit_value(f"load i64, ptr {slot}")
    if name == "int":
        return bits
    operation = "trunc" if name == "bool" else "bitcast"
    return e.emit_value(f"{operation} i64 {bits} to {e.value_type(semantic)}")


def dispatch(e, value, result_kind, node, callback, *, description, decode=True, on_unsupported=None, candidates=None):
    """Visit an erased value's concrete layout only after validating its tag.

    The callback receives the semantic type, retained numeric representation,
    storage kind and unboxed payload. Application references are already their
    own payload. With decode=False a classifier receives the original box and
    can defer decoding to an outlined helper. Boxing layouts must be registered
    before outlining these consumers.
    """
    from .analysis import NATIVE_ENVIRONMENT

    result = e.emit_value(f"alloca {result_kind}") if result_kind != "void" else None
    done, present = e.new_label("object.dispatch.done"), e.new_label("object.dispatch.present")
    absent = e.new_label("object.dispatch.absent")

    def finish(semantic, represented, storage, payload):
        answer = callback(semantic, represented, storage, payload)
        if result is not None:
            e.emit_line(f"store {result_kind} {answer}, ptr {result}")
        e.emit_line(f"br label %{done}")

    e.emit_line(f"br i1 {e.emit_value(f'icmp eq ptr {value}, null')}, label %{absent}, label %{present}")
    e.emit_line(f"{absent}:")
    finish(NATIVE_ENVIRONMENT.builtins.search("NoneType"), None, "void", "")
    e.emit_line(f"{present}:")
    identity = e.emit_value(f"call ptr @pyjs.runtime.typeof.with.types(ptr {value}, "
                            f"ptr @pyjs.object.types, i64 {len(runtime_types(e))})")

    def case(matches, semantic, represented, storage):
        yes, no = e.new_label("object.dispatch.case"), e.new_label("object.dispatch.next")
        e.emit_line(f"br i1 {matches}, label %{yes}, label %{no}")
        e.emit_line(f"{yes}:")
        finish(semantic, represented, storage, known_payload(e, value, semantic) if decode else value)
        e.emit_line(f"{no}:")

    candidates = tuple(e.module.erased_candidates) if candidates is None else candidates
    classes = {cls for semantic, _ in candidates for cls in e.module.classes if is_subclass(cls, semantic)}
    for cls in sorted(classes, key=e.class_name):
        matches = e.emit_value(f"icmp eq ptr {identity}, @{e.vtable_name(cls)}")
        case(matches, cls, None, "ptr")
    for semantic, represented in candidates:
        name = runtime_name(semantic)
        if name not in {"bool", "int", "float", "NotImplementedType", *REFERENCES}:
            continue
        matches = e.emit_value(f"icmp eq ptr {identity}, @pyjs.object.type.{name}")
        if semantic.generic_types is not None:
            # Read a reference layout only after matching its whitelisted kind;
            # scalar boxes and application instances have different sizes.
            check, next_case = e.new_label("object.dispatch.layout"), e.new_label("object.dispatch.kind.next")
            e.emit_line(f"br i1 {matches}, label %{check}, label %{next_case}")
            e.emit_line(f"{check}:")
            slot = e.emit_value(f"getelementptr %pyjs.object.reference, ptr {value}, i32 0, i32 3")
            layout = e.emit_value(f"load i64, ptr {slot}")
            # Empty tuple is a concrete zero-layout, not an unspecialized
            # wildcard for all tuples registered after it.
            token = layout_token(e, semantic, represented) if semantic.generic_types else 0
            case(e.emit_value(f"icmp eq i64 {layout}, {token}"), semantic, represented, "ptr")
            e.emit_line(f"br label %{next_case}")
            e.emit_line(f"{next_case}:")
        elif name in REFERENCES:
            case(matches, semantic, represented, "ptr")
        else:
            case(matches, semantic, represented, e.value_type(semantic))
    if on_unsupported is None:
        e.guard_exception(node, "false", "TypeError", f"unsupported erased {description} layout")
    else:
        on_unsupported()
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load {result_kind}, ptr {result}") if result is not None else None
