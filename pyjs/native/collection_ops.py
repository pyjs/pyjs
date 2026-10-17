"""Lower eager collection algorithms using concrete storage and scalar loops."""

import ast

from pyjs.analysis.analyzer import (
    analyzed_iterable_protocol,
    analyzed_value_object,
    analyzed_value_type,
    callable_value_type,
    dynamic_slice_index,
    is_slice_index,
    iterable_is_provably_nonempty,
)
from pyjs.analysis.ir import CollectionNew, IteratorCreate
from pyjs.analysis.iterable_protocol import resolve_iterable_protocol
from pyjs.analysis.objects import (
    CallableClass,
    Class,
    Function,
    GenericClass,
    LiteralClass,
    UnionType,
    same_analyzer_type,
)
from pyjs.analysis.type_relations import (
    get_type_members,
    is_isinstance_match,
    is_numeric_promotion,
    is_return_type_compatible,
    is_subclass,
)
from pyjs.analysis.value_representation import (
    analyzed_numeric_format,
    analyzed_representation,
    merged_representation,
    representation_for_member,
    representations_conflict,
)
from pyjs.numeric import integer_literal
from pyjs.python import contains_equal_sequence_item
from pyjs.python import native as builtins

from . import calls, comparisons, enum_ops, gc_layouts, nullable, tagged
from . import itertools as streams
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported
from .functional import reduce

VIEWS = {"KeysView", "ValuesView", "ItemsView"}
CONTAINERS = {"list", "dict", "set", "frozenset", "tuple", *VIEWS}
COMPARISONS = {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}


def builtin_name(value_type):
    """A storage shortcut needs builtin identity, never just an application name."""
    if isinstance(value_type, (Class, GenericClass)) and value_type.container.scope.is_builtins:
        return getattr(value_type, "generic_name", value_type.name)
    return None


def sequence_name(value_type):
    # Read-only set algorithms share physical storage without exposing any
    # mutation methods on frozenset or changing the semantic result type.
    name = builtin_name(value_type)
    if name == "frozenset":
        return "set"
    if name == "tuple":
        members = tuple(value_type.generic_types.values())
        if members and all(same_analyzer_type(member, members[0]) for member in members):
            return "list"
    return name


def is_fixed_tuple(value_type):
    return builtin_name(value_type) == "tuple" and not value_type.tuple_variadic


def is_layout_subclass(actual, expected):
    """Nominal base storage, without the analyzer's generic covariance."""
    while isinstance(actual, Class):
        if same_analyzer_type(actual, expected):
            return True
        actual = actual.super
    return False


def require_matching_layout(actual, expected, node, *, adapt_value=True, allow_tuple_upcast=True):
    enum_ops.check_type_conversion(actual, expected, node)
    # Direct conversion and variance are separate: tuple items cannot be
    # adapted in place, but an immutable tuple may expose base-class pointers.
    # Declarations and enclosing mutable storage must disable that widening.
    from .dom_types import is_opaque_type
    from .iterable_views import check as check_iterable
    from .iterable_views import is_view
    from .iterator_ops import is_iterator

    if actual is expected:
        return
    if is_view(expected) and not isinstance(actual, UnionType):
        return check_iterable(actual, expected, node, adapt=adapt_value)
    if not adapt_value and not same_analyzer_type(actual, expected):
        # coerce_value adapts a direct DOM value, never fields already inside
        # an aliased record/container. Check both directions, also through
        # optional/tagged members, before their scalar conversion rules run.
        for left in get_type_members(actual):
            for right in get_type_members(expected):
                for source, target in ((left, right), (right, left)):
                    if (is_opaque_type(target) and not is_opaque_type(source)
                            and isinstance(source, Class) and is_subclass(source, target)):
                        raise LLVMUnsupported("LLVM stored DOM views require matching wrapper and opaque representations", node)
    if (isinstance(expected, Class) and expected.generic_types
            and not expected.container.scope.is_builtins):
        # Generic record fields are mutable storage, not covariant protocol
        # results. A different specialization needs a new object, not an
        # alias. Check the matching base of an ordinary subclass as well.
        base = actual
        while isinstance(base, Class):
            if base.py_cls is expected.py_cls:
                if not same_analyzer_type(base, expected):
                    raise LLVMUnsupported("LLVM generic object views require matching type arguments (invariant)", node)
                break
            base = base.super
    if is_iterator(actual) and is_iterator(expected):
        from .iterator_views import check
        return check(actual, expected, node, adapt=adapt_value)
    if tagged.members(expected):
        # A runtime tag identifies the container class, not its element
        # layout. Widening a list[bool] reference must not reinterpret it as
        # list[int] merely because the destination also accepts a string.
        sources = actual.types if isinstance(actual, UnionType) else (actual,)
        for source in sources:
            # A union of generic specializations retains each member's tag;
            # it does not reinterpret one specialization as every other arm.
            if any(is_layout_subclass(source, target) for target in expected.types):
                continue
            # Typing permits int -> float, but a tagged union preserves the
            # source's runtime kind. Do not pack an int tag into float | str
            # unless another arm (such as int) actually accepts that tag.
            if (builtin_name(source) in {"bool", "int"}
                    and any(is_numeric_promotion(source, target) for target in expected.types)
                    and not any(is_isinstance_match(source, target) for target in expected.types)):
                raise LLVMUnsupported("LLVM union values require an explicit numeric conversion", node)
            for target in expected.types:
                if (getattr(source, "generic_name", None) == getattr(target, "generic_name", None)
                        or isinstance(source, Class) and isinstance(target, Class) and is_subclass(source, target)):
                    require_matching_layout(source, target, node, adapt_value=adapt_value,
                                            allow_tuple_upcast=allow_tuple_upcast)
        return
    if isinstance(actual, UnionType) or isinstance(expected, UnionType):
        a, b = nullable.member(actual), nullable.member(expected)
        if a is not None and b is not None:
            # Nominal application upcasts retain pointer storage; cursor and
            # DOM views are adapted by coerce_value. Container payloads still
            # need the same concrete storage contracts, checked recursively.
            cursor_view = (is_iterator(b) and b.generic_name == "Iterator"
                           and isinstance(a.find_attrs("__next__"), Function))
            dom_view = is_opaque_type(b) and is_subclass(a, b)
            application_view = not b.container.scope.is_builtins and is_layout_subclass(a, b)
            from .callable_adapters import compatible
            adapted_view = adapt_value and (compatible(a, b) or is_view(b) or is_iterator(a) and is_iterator(b))
            if not same_analyzer_type(tagged.runtime_type(a), tagged.runtime_type(b)) and not (
                    application_view or cursor_view or dom_view or adapted_view):
                raise LLVMUnsupported("LLVM optional storage requires matching concrete payload types", node)
            return require_matching_layout(a, b, node, adapt_value=adapt_value,
                                           allow_tuple_upcast=allow_tuple_upcast)
        if b is not None:
            if getattr(actual, "generic_name", None) == "NoneType":
                return
            return require_matching_layout(actual, b, node, adapt_value=adapt_value,
                                           allow_tuple_upcast=allow_tuple_upcast)
        if a is not None:
            return require_matching_layout(a, expected, node, adapt_value=adapt_value,
                                           allow_tuple_upcast=allow_tuple_upcast)
    if isinstance(expected, CallableClass) or isinstance(actual, CallableClass):
        if (isinstance(actual, CallableClass) and isinstance(expected, CallableClass)
                and expected.parameter_types is None
                and same_analyzer_type(actual.return_type, expected.return_type)
                and actual.return_representation == expected.return_representation):
            # Opaque callback storage is safe; invocation still requires a
            # concrete signature and cannot reinterpret this code pointer.
            return
        # A Python-compatible callback can still need an ABI adapter (omitted
        # defaults, bool/int widening, or a covariant result). Never reinterpret
        # its code pointer using a different native signature.
        if not same_analyzer_type(actual, expected):
            from .callable_adapters import compatible
            if adapt_value and compatible(actual, expected):
                for source, target in zip(expected.parameter_types,
                                          actual.parameter_types[:len(expected.parameter_types)], strict=True):
                    require_matching_layout(source, target, node)
                return require_matching_layout(actual.return_type, expected.return_type, node)
            raise LLVMUnsupported("LLVM callable values require matching parameter and result types and representations", node)
        return
    # Tuple shape annotations share a sequence header, but their unboxed
    # members must still agree. A bool payload cannot be read as i64, nor
    # can a heterogeneous payload be traversed with a homogeneous stride.
    if builtin_name(actual) == builtin_name(expected) == "tuple":
        left = tuple(actual.generic_types.values())
        right = tuple(expected.generic_types.values())
        if actual.tuple_variadic or expected.tuple_variadic:
            pairs = ([(item_type(actual), other) for other in right] if actual.tuple_variadic
                     else [(other, item_type(expected)) for other in left])
        else:
            if len(left) != len(right) and not (
                sequence_name(actual) == sequence_name(expected) == "list"
                and same_analyzer_type(left[0], right[0])
            ):
                raise LLVMUnsupported("LLVM tuple views require matching fixed item layouts", node)
            pairs = zip(left, right, strict=False)
        for other, member in pairs:
            # Independently analyzed union fields can denote the same tagged
            # storage. Equality is structural; nominal name/stride alone is not.
            if same_analyzer_type(other, member):
                continue
            # Read-only tuples may expose nominal application base pointers.
            # Preserve direction for variadic shapes; never permit a downcast
            # or a mutable container's covariant item reinterpretation.
            application_upcast = (allow_tuple_upcast and isinstance(member, Class) and not member.container.scope.is_builtins
                                  and is_layout_subclass(other, member))
            if (not isinstance(other, Class) or not isinstance(member, Class)
                    or other.generic_name != member.generic_name and not application_upcast):
                raise LLVMUnsupported("LLVM tuple views require matching concrete item storage", node)
            require_matching_layout(other, member, node, adapt_value=False,
                                    allow_tuple_upcast=allow_tuple_upcast)
        return
    if isinstance(actual, Class) and isinstance(expected, Class) and actual.generic_name == expected.generic_name:
        for left, right in zip((actual.generic_types or {}).values(), (expected.generic_types or {}).values(), strict=False):
            # coerce_value can adapt a direct optional/union value, but viewing
            # an existing container never converts its stored members. Equal
            # union names therefore do not imply interchangeable item layouts.
            union_mismatch = (isinstance(left, UnionType) or isinstance(right, UnionType)) and not same_analyzer_type(left, right)
            if (actual.generic_name in CONTAINERS
                    and (union_mismatch or getattr(left, "generic_name", None) != getattr(right, "generic_name", None))):
                raise LLVMUnsupported("LLVM collection views require matching concrete item storage and element types (invariant)", node)
            # A read-only tuple view can widen its own items, but not items
            # nested in a mutable alias: that alias can publish base objects
            # where the original container still promises derived instances.
            # frozenset cannot publish replacements through the widened
            # handle. Preserve an enclosing invariant boundary, though:
            # list[frozenset[...]] still owns writable slots.
            require_matching_layout(left, right, node, adapt_value=False,
                                    allow_tuple_upcast=allow_tuple_upcast and builtin_name(actual) == "frozenset")


def require_declaration_layout(actual, expected, node, *, invariant=False,
                               actual_representation=None, expected_representation=None):
    """A shared field or virtual slot cannot insert a value conversion."""
    from .dom_types import is_opaque_type

    require_matching_layout(actual, expected, node, adapt_value=False,
                            allow_tuple_upcast=not invariant)
    if representations_conflict(((actual, actual_representation), (expected, expected_representation))):
        raise LLVMUnsupported("LLVM declarations require matching storage representations", node)

    def accepts(source, target):
        if same_analyzer_type(source, target):
            return True
        source_name, target_name = builtin_name(source), builtin_name(target)
        if target_name == "object":
            # Application instances already have an identity header; builtin
            # references need boxing, and opaque DOM pointers have no header.
            return source_name == "NoneType" or (isinstance(source, Class)
                and not source.container.scope.is_builtins and not is_opaque_type(source))
        if isinstance(source, LiteralClass) or isinstance(target, LiteralClass):
            return is_return_type_compatible(target, source)
        if source_name is not None and source_name == target_name:
            # The layout check above already handles nested item storage and
            # supported fixed/variadic tuple views, not just spelling equality.
            return True
        return is_layout_subclass(source, target)

    directions = ((actual, expected), (expected, actual)) if invariant else ((actual, expected),)
    for source, target in directions:
        if not all(any(accepts(member, destination) for destination in get_type_members(target))
                   for member in get_type_members(source)):
            message = ("LLVM inherited fields require invariant types" if invariant else
                       "LLVM overrides require compatible parameter and result types")
            raise LLVMUnsupported(message, node)


def prepare(emitter, node):
    value_type = None
    if isinstance(node, (ast.Call, CollectionNew)):
        from .mapping_keys import prepare
        prepare(emitter, node)
        value_type = analyzed_value_type(node)
        target = getattr(getattr(node, "func", None), "obj", None)
        if (builtin_name(value_type) not in CONTAINERS and isinstance(target, Function)
                and builtin_name(target.cls) in CONTAINERS):
            # A scalar-returning operation on a parameter still needs its
            # container runtime, even if no reached expression allocates one
            # (for example, a checked branch that only subscripts a list).
            value_type = target.cls
    name = getattr(value_type, "generic_name", None)
    if isinstance(value_type, Class) and value_type.container.scope.is_builtins and name in CONTAINERS:
        emitter.module.uses_collections = True
        if name in {"dict", "set", "frozenset", *VIEWS}:
            emitter.module.uses_mappings = True
            emitter.module.uses_strings = True
        if name == "tuple" and not value_type.tuple_variadic:
            emitter.tuple_type(value_type, node)
        if name == "ItemsView":
            emitter.tuple_type(item_type(value_type))
    if isinstance(node, IteratorCreate):
        source_type = analyzed_value_type(node.iterable)
        if source_type.generic_name == "str":
            emitter.module.uses_text_edit = True
    if isinstance(node, CollectionNew):
        if isinstance(node.source, (ast.List, ast.Set)):
            members = [(source, item_type(node.value_type)) for source in node.source.elts]
        elif isinstance(node.source, ast.Dict):
            members = [(source, node.value_type.generic_types[slot])
                       for sources, slot in ((node.source.keys, "K"), (node.source.values, "V"))
                       for source in sources if source is not None]
        elif isinstance(node.source, ast.Tuple):
            types = ([item_type(node.value_type)] * len(node.source.elts) if node.value_type.tuple_variadic
                     else node.value_type.generic_types.values())
            members = zip(node.source.elts, types, strict=True)
        else:
            members = ()
        for source, expected in members:
            location = source.source if isinstance(source, CollectionNew) else source
            require_matching_layout(emitter.runtime_value_type(source), expected, location)
    if isinstance(node, ast.Call):
        target = getattr(node.func, "obj", None)
        if (isinstance(target, Function) and getattr(target.cls, "generic_name", None) in {"set", "frozenset", "KeysView", "ItemsView"}
                and target.cls.container.scope.is_builtins
                and target.name in {"__eq__", "__ne__"} and node.args
                and not isinstance(getattr(node, "operator", None), (ast.Eq, ast.NotEq))
                and any(builtin_name(member) not in {"set", "frozenset", "KeysView", "ItemsView"}
                        for member in get_type_members(analyzed_value_type(node.args[0])))):
            # Syntax handles NotImplemented through reflected dispatch; an
            # explicit dunder call must return that sentinel, not False/True.
            raise LLVMUnsupported("LLVM explicit set comparison may return unsupported NotImplemented", node)
        if isinstance(target, Function) and target.py_func is builtins._len and node.args:
            names = {getattr(member, "generic_name", None)
                     for member in get_type_members(emitter.runtime_value_type(node.args[0]))}
            # A nullable parameter may have no constructor/literal anywhere in
            # the program. Its reachable len arm still needs the concrete ABI.
            emitter.module.uses_strings |= bool(names & {"str", "bytes"})
            emitter.module.uses_collections |= bool(names & (CONTAINERS | VIEWS))
        if (isinstance(target, Function) and target.cls is not None and target.cls.container.scope.is_builtins
                and target.cls.generic_name in {"list", "dict"}
                and not target.is_classmethod and isinstance(node.func, ast.Attribute)):
            owner = analyzed_value_type(node.func.value)
            owner_name = getattr(owner, "generic_name", None)
            index = None
            if owner_name == "list":
                index = 0 if target.name == "append" else 1 if target.name in {"insert", "__setitem__"} else None
                if target.name == "__setitem__" and (is_slice_index(node.args[0]) or dynamic_slice_index(node.args[0])):
                    # These operands may be a replacement iterable, not one
                    # stored item. The selected slice/item path checks layout.
                    index = None
            elif owner_name == "dict" and target.name in {"__setitem__", "setdefault", "get", "pop"}:
                index = 1
            if index is not None and len(node.args) > index:
                member = emitter.dictionary_types(owner)[1] if owner_name == "dict" else item_type(owner)
                require_matching_layout(analyzed_value_type(node.args[index]), member, node.args[index])
        if (isinstance(target, Function) and getattr(target.cls, "tuple_variadic", False)
                and target.name in {"__contains__", "count", "index"}):
            emitter.module.uses_sequence_search = True
        consumes = (isinstance(target, Class) and target.generic_name in {"list", "set", "frozenset", "tuple"}
                    or isinstance(target, Function) and target.py_func in {
                        builtins._sorted, builtins._sum, builtins._min, builtins._max, builtins._all, builtins._any, reduce,
                        streams.product, streams.combinations, streams.combinations_with_replacement, streams.permutations,
                    }
                    or isinstance(target, Function) and getattr(target.cls, "generic_name", None) in {"list", "set", "frozenset", "KeysView", "ItemsView"}
                    and target.name in {
                        "extend", "__iadd__", "update", "union", "intersection", "difference",
                        "symmetric_difference", "intersection_update", "difference_update",
                        "symmetric_difference_update", "issubset", "issuperset", "isdisjoint",
                    })
        if consumes and any(getattr(analyzed_value_type(arg), "generic_name", None) == "str"
                            for arg in [*node.args, *(value.value for value in node.keywords)]):
            emitter.module.uses_text_edit = True
        if (isinstance(target, Function) and target.py_func is builtins._sum
                and builtin_name(getattr(node, "native_sum_accumulator", value_type)) == "float"):
            emitter.module.uses_float_sum = analyzed_numeric_format(node) is None or emitter.module.uses_float_sum
        if isinstance(target, Function) and target.py_func in {builtins._min, builtins._max}:
            emitter.module.uses_strings |= any(builtin_name(member) in {"str", "bytes"}
                                               for member in get_type_members(value_type))
        if isinstance(target, Function) and target.py_func is builtins._sorted:
            key = sort_key(node)
            if key is not None:
                callback = callable_value_type(key)
                if not isinstance(callback, CallableClass) or callback.parameter_types is None or not callback.accepts_arity(1):
                    raise LLVMUnsupported("LLVM sort keys require a concrete one-argument callable", key)
        receiver_members = ()
        if (isinstance(target, Function) and target.name in {*COMPARISONS, "__dynamic_eq__", "__dynamic_ne__"}
                and isinstance(node.func, ast.Attribute)
                and not isinstance(analyzed_value_object(node.func.value), Class)):
            # Class-qualified static calls have no value receiver. Asking
            # for type[Class] here introduces a late, unanalyzed dependency.
            # Any concrete union arm can invoke collection comparison helpers,
            # not just the single payload of an optional collection.
            receiver_members = get_type_members(analyzed_value_type(node.func.value))
        if isinstance(target, Function) and (
            target.py_func in {builtins._sorted, contains_equal_sequence_item}
            or getattr(target.cls, "generic_name", None) in CONTAINERS | VIEWS
            and target.name in {*COMPARISONS, "sort", "count", "index", "__contains__", "isdisjoint"}
            or any(getattr(member, "generic_name", None) in CONTAINERS for member in receiver_members)
            and target.name in {*COMPARISONS, "__dynamic_eq__", "__dynamic_ne__"}
        ):
            emitter.module.uses_ordering = True
            emitter.module.uses_strings = True
            emitter.module.uses_collections = True


def item_type(value_type, node=None):
    if not isinstance(value_type, Class):
        raise LLVMUnsupported("LLVM iteration requires a concrete iterable type; narrow unions before use", node)
    if not value_type.container.scope.is_builtins:
        from .protocols import item_protocol
        if protocol := item_protocol(value_type):
            return protocol.item_type
        raise LLVMUnsupported(f"LLVM iteration needs a concrete homogeneous item type, got {value_type.name}", node)
    name = value_type.generic_name
    members = tuple((value_type.generic_types or {}).values())
    if name in {"list", "set", "frozenset", "dict", "KeysView", "ValuesView", "Iterable", "Iterator", "Generator"} and members:
        return members[0]
    if name == "ItemsView":
        return NATIVE_ENVIRONMENT.builtins.search("tuple")(*members)
    if name == "tuple" and members and all(same_analyzer_type(member, members[0]) for member in members):
        return members[0]
    if name in {"range", "bytes", "str"}:
        return NATIVE_ENVIRONMENT.builtins.search("str" if name == "str" else "int")
    raise LLVMUnsupported(f"LLVM iteration needs a concrete homogeneous item type, got {value_type.name}", node)


def field(emitter, value, structure, index):
    return emitter.emit_value(f"getelementptr %{structure}, ptr {value}, i32 0, i32 {index}")


def storage(emitter, value, index):
    return emitter.emit_value(f"load ptr, ptr {field(emitter, value, 'pyjs.dict', index)}")


def owner(emitter, managed=True, *, allocator="@pyjs.gc.alloc.adapter"):
    managed = managed and emitter.module.uses_gc
    allocator = allocator if managed else "null"
    context = emitter.load_local("__heap") if managed else "null"
    return f"ptr {emitter.load_local('__arena')}, ptr {allocator}, ptr {context}"


def new_list(emitter, value_type):
    kind = emitter.value_type(value_type)
    size = emitter.llvm_size(kind)
    allocation = owner(emitter, allocator=gc_layouts.item_allocator(kind))
    return emitter.allocated_value(f"call ptr @pyjs.list.new.owned({allocation}, i64 {size}, i64 0)")


def new_mapping(emitter, key_type, value_type):
    key_kind, value_kind = emitter.value_type(key_type), emitter.value_type(value_type)
    key_size, value_size = emitter.llvm_size(key_kind), emitter.llvm_size(value_kind)
    return emitter.allocated_value(
        f"call ptr @pyjs.dict.new.typed({mapping_owner(emitter, key_kind, value_kind)}, i64 {key_size}, i64 {value_size})")


def mapping_owner(emitter, key_kind, value_kind, managed=True):
    managed = managed and emitter.module.uses_gc
    key_allocator = gc_layouts.item_allocator(key_kind) if managed else "null"
    value_allocator = gc_layouts.item_allocator(value_kind) if managed else "null"
    context = emitter.load_local("__heap") if managed else "null"
    return f"ptr {emitter.load_local('__arena')}, ptr {key_allocator}, ptr {value_allocator}, ptr {context}"


def tuple_allocator(emitter, value_type):
    """Trace immutable row payloads, not their coallocated header metadata."""
    layout = emitter.tuple_type(value_type)
    fields = tuple(emitter.value_type(member) for member in value_type.generic_types.values())
    paths = tuple((1, *path) for path in gc_layouts.reference_paths(fields))
    return gc_layouts.allocator(emitter, f"{{ %pyjs.list, %{layout} }}", paths)


def new_tuple(emitter, value_type, values, *, managed=True):
    layout = emitter.tuple_type(value_type)
    size = emitter.llvm_size(f"%{layout}")
    allocator = "@pyjs.gc.alloc.adapter"
    if managed and emitter.module.uses_gc:
        # new_tuple coallocates a sequence header and its immutable payload.
        # Header pointers address this allocation, a function, and the heap;
        # only payload members can keep another managed object alive.
        allocator = tuple_allocator(emitter, value_type)
    value = emitter.allocated_value(
        f"call ptr @pyjs.tuple.new({owner(emitter, managed, allocator=allocator)}, i64 {size}, i64 {len(values)})")
    data = storage(emitter, value, 2)
    for index, (kind, item) in enumerate(values):
        emitter.emit_line(f"store {kind} {item}, ptr {field(emitter, data, layout, index)}")
    return value


def tuple_items(emitter, value_type, value):
    layout = emitter.tuple_type(value_type)
    value = storage(emitter, value, 2)
    return [(member, emitter.emit_value(
        f"load {emitter.value_type(member)}, ptr {field(emitter, value, layout, index)}"
    )) for index, member in enumerate(value_type.generic_types.values())]


def append(emitter, target, expected, actual, value, node):
    # This writes a fresh slot, so an application base view is safe here.
    # Validation still rejects widening members inside a shared mutable value.
    if (nullable.is_object(expected) or nullable.member(expected) or tagged.members(expected)
            or emitter.is_opaque_web_element_type(expected) or tagged.members(actual)
            or expected in emitter.module.classes and is_layout_subclass(actual, expected)
            or isinstance(actual, LiteralClass)):
        require_matching_layout(actual, expected, node)
        kind = emitter.value_type(actual)
        # Iterator-produced values have no expression node to record their
        # semantic type. Preserve it explicitly when widening a pointer.
        emitter.value_semantics[kind, value] = actual
        source = tagged.Value(node, actual, kind, value)
        _, value = emitter.coerce_value(kind, value, emitter.value_type(expected), source, semantic=expected)
        actual = expected
    if actual is not expected:
        if actual.generic_name != expected.generic_name:
            raise LLVMUnsupported("LLVM collection construction requires matching item types", node)
        require_matching_layout(actual, expected, node)
    kind = emitter.value_type(expected)
    size = emitter.llvm_size(kind)
    roots = calls.root_values(emitter, value) if nullable.is_object(expected) else None
    slot = emitter.allocated_value(
        f"call ptr @pyjs.list.append.slot(ptr {emitter.load_local('__arena')}, ptr {target}, i64 {size})"
    )
    emitter.emit_line(f"store {kind} {value}, ptr {slot}")
    calls.pop_roots(emitter, roots)


def read_item(emitter, name, member, source, index):
    if name == "str":
        # A byte cursor visits each UTF-8 character once; rescanning from the
        # beginning for each logical character index would be quadratic.
        width = emitter.emit_value(f"call i64 @pyjs.string.character.width(ptr {source}, i64 {index})")
        value = emitter.allocated_value(f"call ptr @pyjs.string.copy.span({owner(emitter)}, ptr {source}, i64 {index}, i64 {width})")
        return value, width
    if name == "ItemsView":
        parts = []
        for offset, component in enumerate(member.generic_types.values(), 2):
            kind = emitter.value_type(component)
            slot = emitter.emit_value(f"getelementptr {kind}, ptr {storage(emitter, source, offset)}, i64 {index}")
            parts.append((kind, emitter.emit_value(f"load {kind}, ptr {slot}")))
        return new_tuple(emitter, member, parts), "1"
    if name == "bytes":
        data = emitter.emit_value(f"load ptr, ptr {field(emitter, source, 'pyjs.string', 1)}")
    else:
        data = storage(emitter, source, 3 if name == "ValuesView" else 2)
    kind = "i8" if name == "bytes" else emitter.value_type(member)
    slot = emitter.emit_value(f"getelementptr {kind}, ptr {data}, i64 {index}")
    value = emitter.emit_value(f"load {kind}, ptr {slot}")
    if name == "bytes":
        value = emitter.emit_value(f"zext i8 {value} to i64")
    return value, "1"


def loop(emitter, value_type, value, visit, node, *, acquired=False):
    """Emit a concrete iteration; visit runs during compilation, not at runtime."""
    name = sequence_name(value_type)
    if name in {"Iterable", "Iterator", "Generator"} or value_type in emitter.module.classes:
        from .iterator_ops import consume
        from .protocols import consumer

        frame = None
        if not acquired:
            value_type, value, frame = consumer(emitter, value_type, value, node)
        consume(emitter, value_type, value, visit, node)
        calls.pop_roots(emitter, frame)
        return
    if name in VIEWS:
        value = emitter.emit_value(f"load ptr, ptr {value}")
    if name == "tuple":
        layout = emitter.tuple_type(value_type)
        for index, member in enumerate(value_type.generic_types.values()):
            slot = field(emitter, storage(emitter, value, 2), layout, index)
            item = emitter.emit_value(f"load {emitter.value_type(member)}, ptr {slot}")
            visit(member, item)
        return
    if name not in {"list", "dict", "set", "range", "bytes", "str", *VIEWS}:
        raise LLVMUnsupported(f"LLVM eager iteration over {value_type.name} is not implemented", node)
    member = item_type(value_type)
    loop_storage(emitter, name, member, value, visit, node)


def loop_storage(emitter, name, member, value, visit, node):
    """Iterate known storage, including internal snapshots without analyzer types."""
    index_slot = emitter.emit_value("alloca i64")
    start = "0"
    if name == "range":
        start, stop, step = emitter.range_values(value)
    elif name in {"dict", "set", *VIEWS}:
        expected_length = emitter.emit_value(f"load i64, ptr {value}")
    emitter.emit_line(f"store i64 {start}, ptr {index_slot}")
    check, body, done = (emitter.new_label(label) for label in ("consume.check", "consume.item", "consume.done"))
    emitter.emit_line(f"br label %{check}")
    emitter.emit_line(f"{check}:")
    index = emitter.emit_value(f"load i64, ptr {index_slot}")
    if name == "range":
        positive = emitter.emit_value(f"icmp sgt i64 {step}, 0")
        below = emitter.emit_value(f"icmp slt i64 {index}, {stop}")
        above = emitter.emit_value(f"icmp sgt i64 {index}, {stop}")
        available = emitter.emit_value(f"select i1 {positive}, i1 {below}, i1 {above}")
    else:
        length = emitter.emit_value(f"load i64, ptr {value}")
        if name in {"dict", "set", *VIEWS}:
            unchanged = emitter.emit_value(f"icmp eq i64 {length}, {expected_length}")
            container = "Set" if name == "set" else "dictionary"
            emitter.guard_exception(node, unchanged, "RuntimeError", f"{container} changed size during iteration")
        available = emitter.emit_value(f"icmp ult i64 {index}, {length}")
    emitter.emit_line(f"br i1 {available}, label %{body}, label %{done}")
    emitter.emit_line(f"{body}:")
    if name == "range":
        item = index
    else:
        item, width = read_item(emitter, name, member, value, index)
    visit(member, item)
    if name == "range":
        pair = emitter.emit_value(f"call {{ i64, i1 }} @llvm.sadd.with.overflow.i64(i64 {index}, i64 {step})")
        following = emitter.emit_value(f"extractvalue {{ i64, i1 }} {pair}, 0")
        overflow = emitter.emit_value(f"extractvalue {{ i64, i1 }} {pair}, 1")
        following = emitter.emit_value(f"select i1 {overflow}, i64 {stop}, i64 {following}")
    else:
        following = emitter.emit_value(f"add i64 {index}, {width}")
    emitter.emit_line(f"store i64 {following}, ptr {index_slot}")
    emitter.emit_line(f"br label %{check}")
    emitter.emit_line(f"{done}:")


def materialize(emitter, target_type, source_type, source, node, *, reiterate=False, item_representation=None):
    from . import iterable_views, iterator_ops, mapping_keys, protocols

    name = target_type.generic_name
    expected = item_type(target_type)
    sequence = name in {"list", "tuple"}
    source_protocol = (resolve_iterable_protocol(source_type, None, NATIVE_ENVIRONMENT.builtins)
                       if item_representation is not None else None)
    if (not sequence and builtin_name(source_type) in {"dict", "set", "frozenset"}
            and not mapping_keys.can_reuse(emitter, expected, item_type(source_type))
            and any(mapping_keys.uses_callbacks(member) for member in get_type_members(item_type(source_type)))):
        raise LLVMUnsupported("LLVM set construction cached callback keys require matching layouts", node)
    if (not sequence and builtin_name(source_type) in {"set", "frozenset"}
            and (same_analyzer_type(item_type(source_type), expected)
                 or mapping_keys.can_reuse(emitter, expected, item_type(source_type)))):
        # Set-to-set construction copies cached hashes, without running key
        # callbacks again. Lists/other iterables still hash each consumed item.
        return emitter.mapping_mutation("copy", target_type, expected, "i1", source, [], node)[1]
    target = (new_list(emitter, expected) if sequence else
              new_mapping(emitter, expected, NATIVE_ENVIRONMENT.builtins.search("bool")))
    frame = calls.root_values(emitter, target)
    if (not sequence and builtin_name(source_type) == "dict" and mapping_keys.uses_callbacks(expected)
            and mapping_keys.can_reuse(emitter, expected, item_type(source_type))):
        mapping_keys.update(emitter, target, source, expected, "1", node, keys_only=True, copy_empty=False)
        calls.pop_roots(emitter, frame)
        return target

    def insert(actual, value):
        if sequence:
            # Loop values have no expression carrying their item metadata.
            # Preserve nested represented references before boxing a fresh slot.
            if source_protocol is not None:
                emitter.value_representations[emitter.value_type(actual), value] = representation_for_member(
                    source_protocol.item_type, item_representation, actual)
            append(emitter, target, expected, actual, value, node)
            return
        calls.validate_storage(emitter, actual, expected, node)
        kind, value = convert_item(emitter, actual, expected, value, node, representation=item_representation)
        slot = emitter.dictionary_set_slot(target, expected, kind, value, "1", node)
        emitter.emit_line(f"store i1 true, ptr {slot}")

    if reiterate and (source_type in emitter.module.classes or iterator_ops.is_iterator(source_type)
                      or iterable_views.is_view(source_type)):
        # Sequence-fast consumers acquire an iterator, then construct a list
        # from that iterator. Its own __iter__ is observable (and may return a
        # different cursor); ordinary list construction acquires only once.
        _, cursor, source_frame = protocols.consumer(emitter, source_type, source, node)
        cursor = protocols.reiterate(emitter, cursor, node)
        cursor_frame = calls.root_values(emitter, cursor)
        iterator_ops.consume(emitter, source_type, cursor, insert, node)
        calls.pop_roots(emitter, cursor_frame)
        calls.pop_roots(emitter, source_frame)
    else:
        loop(emitter, source_type, source, insert, node)
    calls.pop_roots(emitter, frame)
    return target


def construct(emitter, node):
    result_type = analyzed_value_type(node)
    name = result_type.generic_name
    if (node.keywords and name != "dict") or len(node.args) > 1:
        raise LLVMUnsupported(f"LLVM {name}() accepts at most one positional iterable", node)
    source_type = analyzed_value_type(node.args[0]) if node.args else None
    source = emitter.expression(node.args[0])[1] if node.args else None
    if name in {"set", "frozenset"} and node.args and hasattr(node.args[0], "mapping_source_type"):
        source_type = node.args[0].mapping_source_type
        source = emitter.emit_value(f"load ptr, ptr {source}")
    if name == "tuple":
        if source_type is None:
            return "ptr", new_tuple(emitter, result_type, [])
        if builtin_name(source_type) == "tuple":
            require_matching_layout(source_type, result_type, node)
            return "ptr", source
        return "ptr", materialize(emitter, result_type, source_type, source, node)
    if name in {"list", "set", "frozenset"}:
        if name == "frozenset" and source_type is result_type:
            return "ptr", source
        if source_type is not None:
            protocol = analyzed_iterable_protocol(node.args[0])
            return "ptr", materialize(emitter, result_type, source_type, source, node,
                                      item_representation=protocol.item_representation)
        member = item_type(result_type)
        return "ptr", (new_list(emitter, member) if name == "list" else
                       new_mapping(emitter, member, NATIVE_ENVIRONMENT.builtins.search("bool")))
    key_type, value_type = emitter.dictionary_types(result_type)
    parameter = result_type.find("__init__").kwarg if node.keywords else None
    # Evaluate keyword operands before consuming/copying the positional source.
    # The ordinary binder owns ** duplicate checks, evaluation order and roots.
    with (calls.bind_keywords(emitter, parameter, node, representation=analyzed_representation(node)) if node.keywords
          else calls.BoundCall([], [])) as keywords:
        if source_type is None and node.keywords:
            return keywords.values[0]  # The binder already owns a fresh mapping.
        target = new_mapping(emitter, key_type, value_type)
        frame = calls.root_values(emitter, target)
        if source_type is not None:
            if builtin_name(source_type) == "dict":
                if source_type is not result_type:
                    from .mapping_keys import update_converted
                    update_converted(emitter, target, result_type, source, source_type, node)
                else:
                    emitter.mapping_mutation("update", result_type, key_type, emitter.value_type(value_type),
                                             target, [("ptr", source)], node)
            else:
                insert_pairs(emitter, target, result_type, source_type, source, node)
        if node.keywords:
            emitter.mapping_mutation("update", result_type, key_type, emitter.value_type(value_type),
                                     target, keywords.values, node, source_type=parameter.annotation.obj)
        calls.pop_roots(emitter, frame)
    return "ptr", target


def fromkeys(emitter, node):
    from . import mapping_keys, object_values

    if node.keywords or not 1 <= len(node.args) <= 2:
        raise LLVMUnsupported("LLVM dict.fromkeys takes keys and an optional value", node)
    semantic = analyzed_value_type(node)
    key_type, value_type = emitter.dictionary_types(semantic)
    kind = emitter.value_type(value_type)
    if not isinstance(analyzed_value_object(node.func.value), Class):
        # A classmethod accessed through an instance still evaluates its
        # receiver expression, although that instance is not passed as cls.
        emitter.expression(node.func.value)
    source_node = node.args[0]
    if hasattr(source_node, "mapping_source_type"):
        # Analysis supplies an implicit keys() view to satisfy Iterable[K].
        # Unlike an explicit view, a mapping source reuses its cached hashes.
        source_node = source_node.func.value
    source_type = analyzed_value_type(source_node)
    protocol = analyzed_iterable_protocol(source_node)
    source = emitter.expression(source_node)[1]
    source_frame = calls.root_values(emitter, source)
    default = node.args[1] if len(node.args) == 2 else ast.copy_location(ast.Constant(value=None), node)
    if len(node.args) == 1:
        default.obj = NATIVE_ENVIRONMENT.builtins.search("NoneType")._self
    # Retyping the fresh result cannot widen storage inside its shared default.
    require_matching_layout(analyzed_value_type(default), value_type, default)
    representation = analyzed_representation(node)
    with object_values.converted_values(emitter, [(default, value_type)],
            [representation.arguments[1] if representation else None]) as values:
        target = new_mapping(emitter, key_type, value_type)
        (default_slot, target_slot), frame = calls.value_slots(emitter, [kind, "ptr"])
        emitter.emit_line(f"store {kind} {values[0][1]}, ptr {default_slot}")
        emitter.emit_line(f"store ptr {target}, ptr {target_slot}")

        def insert(actual, key):
            # These are newly allocated key slots, not a mutable view of the
            # input. Keep the source's numeric domain even when the destination
            # erases its type; ordinary conversion must still validate boxing.
            calls.validate_storage(emitter, actual, key_type, node)
            source_representation = merged_representation(actual,
                ((protocol.item_type, protocol.item_representation),))
            key_kind, key = convert_item(emitter, actual, key_type, key, node,
                                         representation=source_representation)
            slot = emitter.dictionary_set_slot(target, key_type, key_kind, key,
                                               emitter.llvm_size(kind), node)
            emitter.emit_line(f"store {kind} {values[0][1]}, ptr {slot}")

        if builtin_name(source_type) in {"dict", "set", "frozenset"}:
            source_key = item_type(source_type)
            matching = same_analyzer_type(source_key, key_type)
            if not matching and any(mapping_keys.uses_callbacks(member) for member in get_type_members(source_key)):
                raise LLVMUnsupported("LLVM dict.fromkeys cached callback keys require matching layouts", node)
            if not matching:
                # Scalar keys have no observable hash callbacks. Other cached
                # keys stay on the hash-preserving path below, never rehashed.
                loop_storage(emitter, "dict" if builtin_name(source_type) == "dict" else "set",
                             source_key, source, insert, node)
            elif mapping_keys.uses_callbacks(key_type):
                # fromkeys inserts separately even into an empty dictionary:
                # mutable source keys may have become equal since insertion.
                mapping_keys.update(emitter, target, source, key_type, emitter.llvm_size(kind), node,
                                    keys_only=True, default_slot=default_slot, copy_empty=False)
            else:
                success = emitter.emit_value(
                    f"call i1 @pyjs.dict.copy.keys(ptr {emitter.load_local('__arena')}, "
                    f"ptr {target}, ptr {source}, i64 {emitter.llvm_size(emitter.value_type(key_type))}, "
                    f"i64 {emitter.llvm_size(kind)}, ptr {default_slot})")
                emitter.guard_exception(node, success, "MemoryError", "native mapping allocation failed")
        else:
            loop(emitter, source_type, source, insert, node)
        calls.pop_roots(emitter, frame)
    calls.pop_roots(emitter, source_frame)
    return "ptr", target


def insert_pairs(emitter, target, target_type, source_type, source, node):
    key_type, value_type = emitter.dictionary_types(target_type)
    kind = emitter.value_type(value_type)
    size = emitter.llvm_size(kind)

    def insert(actual, value):
        if builtin_name(actual) != "tuple" or len(actual.generic_types) != 2 or actual.tuple_variadic:
            raise LLVMUnsupported("LLVM dictionary construction/update requires typed key/value tuple pairs", node)
        key_kind = emitter.value_type(key_type)
        # A yielded pair may disappear from its source during a key callback.
        # Retain it while converting, and retain converted values independently:
        # boxing can allocate, and hashing/equality can mutate and collect.
        slots, frame = calls.value_slots(emitter, ["ptr", key_kind, kind])
        emitter.emit_line(f"store ptr {value}, ptr {slots[0]}")
        converted = []
        for (member, item), expected, slot in zip(
                tuple_items(emitter, actual, value), (key_type, value_type), slots[1:], strict=True):
            result_kind, item = convert_item(emitter, member, expected, item, node)
            emitter.emit_line(f"store {result_kind} {item}, ptr {slot}")
            converted.append(item)
        key, item = converted
        slot = emitter.dictionary_set_slot(target, key_type, key_kind, key, size, node)
        emitter.emit_line(f"store {kind} {item}, ptr {slot}")
        calls.pop_roots(emitter, frame)

    loop(emitter, source_type, source, insert, node)


def convert_item(emitter, actual, expected, value, node, *, representation=None):
    """Convert an iterator/storage value with no source expression node."""
    require_matching_layout(actual, expected, node)
    kind = emitter.value_type(actual)
    emitter.value_semantics[kind, value] = actual
    emitter.value_representations[kind, value] = representation
    return emitter.coerce_value(kind, value, emitter.value_type(expected), node, semantic=expected)


def scalar_kind(value_type, node):
    kind = {"bool": 1, "int": 2, "str": 3, "bytes": 3, "float": 4}.get(enum_ops.storage_name(value_type))
    if kind is None:
        raise LLVMUnsupported("LLVM collection ordering currently requires scalar items", node)
    return kind


def scalar_compare(emitter, name, value_type, left, right, node):
    kind = emitter.value_type(value_type)
    scalar = scalar_kind(value_type, node)
    if scalar in {1, 2}:
        predicate = "eq" if name == "equal" else "ult" if scalar == 1 else "slt"
        return emitter.emit_value(f"icmp {predicate} {kind} {left}, {right}")
    if scalar == 4:
        predicate = "oeq" if name == "equal" else "olt"
        return emitter.emit_value(f"fcmp {predicate} double {left}, {right}")
    return emitter.emit_value(f"call i1 @pyjs.string.{name}(ptr {left}, ptr {right})")


def sort(emitter, value_type, value, reverse, node):
    member = item_type(value_type)
    if enum_ops.storage_name(member) not in {"int", "bool", "float", "str", "bytes"}:
        from . import callback_ops

        callback_ops.sort_structural(emitter, value, member, reverse, node)
        return
    kind = scalar_kind(member, node)
    size = emitter.llvm_size(emitter.value_type(member))
    success = emitter.emit_value(f"call i1 @pyjs.list.sort(ptr {value}, i64 {size}, i8 {kind}, i1 {reverse})")
    emitter.guard_exception(node, success, "MemoryError", "native sorting scratch allocation failed")


def sort_key(node):
    return next((keyword.value for keyword in node.keywords if keyword.arg == "key"
                 and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)), None)


def sort_keyed(emitter, value_type, value, callback, key_node, reverse, node):
    from . import callback_ops

    signature = callable_value_type(key_node)
    key_type = signature.return_type
    member = item_type(value_type)
    require_matching_layout(member, signature.parameter_types[0], key_node)
    keys = new_list(emitter, key_type)
    frame = calls.root_values(emitter, value, keys)

    def consume(actual, item):
        _, key = callback_ops.invoke(emitter, callback, signature, [(actual, item)], key_node)
        append(emitter, keys, key_type, key_type, key, key_node)

    loop(emitter, value_type, value, consume, node)
    sort_prepared(emitter, value, member, keys, key_type, reverse, node)
    calls.pop_roots(emitter, frame)


def sort_prepared(emitter, value, member, keys, key_type, reverse, node):
    """Sort values by an already evaluated parallel key vector."""
    size = emitter.llvm_size(emitter.value_type(member))
    key_size = emitter.llvm_size(emitter.value_type(key_type))
    if enum_ops.storage_name(key_type) in {"int", "bool", "float", "str", "bytes"}:
        kind = scalar_kind(key_type, node)
        success = emitter.emit_value(f"call i1 @pyjs.list.sort.keyed(ptr {value}, ptr {keys}, i64 {size}, "
                                     f"i64 {key_size}, i8 {kind}, i1 {reverse})")
        emitter.guard_exception(node, success, "MemoryError", "native sorting scratch allocation failed")
    else:
        from . import callback_ops

        callback_ops.sort_structural(emitter, value, member, reverse, node, keys=keys, key_type=key_type)


def builtin(emitter, name, node):
    name = name.removeprefix("_")
    if not node.args:
        raise LLVMUnsupported(f"LLVM {name} requires a positional iterable", node)
    arguments = [emitter.expression(argument) for argument in node.args]
    keywords = {keyword.arg: emitter.expression(keyword.value) for keyword in node.keywords}
    source_type = analyzed_value_type(node.args[0])
    source = arguments[0][1]
    if name in {"min", "max"}:
        from . import callback_ops

        return callback_ops.extreme(emitter, name, node, arguments, keywords)
    if name == "sorted":
        if len(arguments) != 1 or set(keywords) - {"key", "reverse"}:
            raise LLVMUnsupported("LLVM sorted accepts values, key, and reverse", node)
        reverse = keywords.get("reverse", ("i1", "false"))
        if reverse[0] != "i1":
            raise LLVMUnsupported("LLVM sorted reverse must be bool", node)
        value = materialize(emitter, analyzed_value_type(node), source_type, source, node)
        key_node = sort_key(node)
        if key_node is None:
            sort(emitter, analyzed_value_type(node), value, reverse[1], node)
        else:
            sort_keyed(emitter, analyzed_value_type(node), value, keywords["key"][1], key_node, reverse[1], node)
        return "ptr", value
    if name == "sum":
        if len(arguments) > 2 or set(keywords) - {"start"} or len(arguments) == 2 and keywords:
            raise LLVMUnsupported("LLVM sum accepts values and one start", node)
        source_node = getattr(node.args[0], "source", node.args[0])
        if isinstance(source_node, (ast.List, ast.Tuple)) and not source_node.elts:
            # Arguments have already evaluated in source order. An empty literal
            # returns the exact start, without emitting an unreachable addition
            # for its context-inferred (possibly union) item type.
            return arguments[1] if len(arguments) == 2 else keywords.get("start", ("i64", "0"))
    from .protocols import consumer
    source_type, source, source_frame = consumer(emitter, source_type, source, node)
    result_type = getattr(node, "native_sum_accumulator", analyzed_value_type(node))
    result_kind = emitter.value_type(result_type)
    result = emitter.emit_value(f"alloca {result_kind}")
    done = emitter.new_label("reduce.done")
    if name in {"any", "all"}:
        if len(arguments) != 1 or keywords:
            raise LLVMUnsupported(f"LLVM {name} accepts one iterable", node)
        emitter.emit_line(f"store i1 {str(name == 'all').lower()}, ptr {result}")

        def consume(actual, value):
            from .iterator_callbacks import truth as item_truth
            truth = item_truth(emitter, actual, emitter.value_type(actual), value, node)
            emitter.emit_line(f"store i1 {truth}, ptr {result}")
            following = emitter.new_label("reduce.next")
            yes, no = (done, following) if name == "any" else (following, done)
            emitter.emit_line(f"br i1 {truth}, label %{yes}, label %{no}")
            emitter.emit_line(f"{following}:")
    elif name == "sum":
        def convert(kind, value):
            if kind == "i1":
                value = emitter.emit_value(f"zext i1 {value} to i64")
                kind = "i64"
            return emitter.coerce_numeric(kind, value, result_kind, node)[1]

        initial = arguments[1] if len(arguments) == 2 else keywords.get("start", ("i64", "0"))
        source_node = getattr(node.args[0], "source", node.args[0])
        start_node = node.args[1] if len(node.args) == 2 else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "start"), None)
        if (start_node is not None and enum_ops.scalar_name(analyzed_value_type(start_node))
                and not iterable_is_provably_nonempty(source_node, node.args[0])):
            raise LLVMUnsupported("LLVM sum with an enum start requires a statically nonempty iterable or explicit int() conversion", node)
        preserve_start = hasattr(node, "native_sum_accumulator")
        if not preserve_start and initial[0] != result_kind and not iterable_is_provably_nonempty(source_node, node.args[0]):
            # Python returns the original start object for an empty input.
            # Widening it would silently change its type and string formatting.
            raise LLVMUnsupported("LLVM sum over a potentially empty iterable requires a matching start type; use 0.0 for floats", node)
        if preserve_start:
            # Keep the scalar accumulator fast; only its final result needs a
            # tag distinguishing an untouched start from an addition result.
            original = initial
            used = emitter.emit_value("alloca i1")
            emitter.emit_line(f"store i1 false, ptr {used}")
        ordinary_float = result_kind == "double" and analyzed_numeric_format(node) is None
        # CPython's bool start stays on the generic addition path even after
        # producing floats; unlike an exact int/float start, it never compensates.
        compensated = ordinary_float and initial[0] != "i1"
        # Heterogeneous tuples are consumed in statically known order. Keep their
        # integer prefix exact until the first float, regardless of the final
        # inferred result type. Homogeneous float loops have no integer prefix.
        integer_prefix = None
        transition = None
        if ordinary_float and sequence_name(source_type) == "tuple" and initial[0] in {"i1", "i64"}:
            integer_prefix = initial[1] if initial[0] == "i64" else emitter.emit_value(f"zext i1 {initial[1]} to i64")
        elif compensated and initial[0] in {"i1", "i64"}:
            transition = emitter.emit_value("alloca i1")
            emitter.emit_line(f"store i1 true, ptr {transition}")
        initial = convert(*initial) if integer_prefix is None else "0.0"
        emitter.emit_line(f"store {result_kind} {initial}, ptr {result}")
        if compensated:
            state = emitter.emit_value("alloca [2 x double]")
            correction = emitter.emit_value(f"getelementptr double, ptr {state}, i64 1")
            emitter.emit_line(f"store double {initial}, ptr {state}")
            emitter.emit_line(f"store double 0.0, ptr {correction}")

        def start_float(prefix, value):
            # Python rounds the first mixed addition normally, then starts
            # compensation with zero correction. Compensating this transition
            # would retain precision that Python has already discarded.
            total = emitter.emit_value(f"fadd double {prefix}, {value}")
            emitter.emit_line(f"store double {total}, ptr {state if compensated else result}")

        def consume(actual, value):
            nonlocal integer_prefix
            if preserve_start:
                emitter.emit_line(f"store i1 true, ptr {used}")
            kind = emitter.value_type(actual)
            if integer_prefix is not None:
                if kind in {"i1", "i64"}:
                    if kind == "i1":
                        value = emitter.emit_value(f"zext i1 {value} to i64")
                    integer_prefix = emitter.emit_value(f"add i64 {integer_prefix}, {value}")
                    return
                prefix = convert("i64", integer_prefix)
                start_float(prefix, convert(kind, value))
                integer_prefix = None
                return
            value = convert(kind, value)
            if compensated:
                if transition is not None:
                    pending = emitter.emit_value(f"load i1, ptr {transition}")
                    first, add, ready = (emitter.new_label(label) for label in ("sum.first", "sum.add", "sum.ready"))
                    emitter.emit_line(f"br i1 {pending}, label %{first}, label %{add}")
                    emitter.emit_line(f"{first}:")
                    start_float(emitter.emit_value(f"load double, ptr {state}"), value)
                    emitter.emit_line(f"store i1 false, ptr {transition}")
                    emitter.emit_line(f"br label %{ready}")
                    emitter.emit_line(f"{add}:")
                emitter.emit_line(f"call void @pyjs.sum.add(ptr {state}, double {value})")
                if transition is not None:
                    emitter.emit_line(f"br label %{ready}")
                    emitter.emit_line(f"{ready}:")
                return
            previous = emitter.emit_value(f"load {result_kind}, ptr {result}")
            following = emitter.emit_value(f"{'fadd' if result_kind == 'double' else 'add'} {result_kind} {previous}, {value}")
            _, following = (emitter.normalize_float_result(following, node) if result_kind == "double"
                            else emitter.normalize_integer_result(following, node))
            emitter.emit_line(f"store {result_kind} {following}, ptr {result}")
    loop(emitter, source_type, source, consume, node, acquired=True)
    if name == "sum" and compensated:
        total = emitter.emit_value(f"call double @pyjs.sum.finish(ptr {state})")
        emitter.emit_line(f"store double {total}, ptr {result}")
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, source_frame)
    value = emitter.emit_value(f"load {result_kind}, ptr {result}")
    if name == "sum" and preserve_start:
        start_type = analyzed_value_type(start_node) if start_node is not None else NATIVE_ENVIRONMENT.builtins.search("int")
        empty = tagged.pack(emitter, start_type, *original, node)
        nonempty = tagged.pack(emitter, result_type, result_kind, value, node)
        present = emitter.emit_value(f"load i1, ptr {used}")
        return tagged.STORAGE, emitter.emit_value(
            f"select i1 {present}, {tagged.STORAGE} {nonempty}, {tagged.STORAGE} {empty}")
    return result_kind, value


def method(emitter, operation, value_type, receiver, arguments, node):
    name = builtin_name(value_type)
    if name == "frozenset":
        name = "set"
    if name == "tuple":
        if operation == "__add__":
            # Runtime-length concatenation copies payload bytes, not converted
            # values. Validate both sources against the inferred result layout.
            result_type = analyzed_value_type(node)
            require_matching_layout(value_type, result_type, node)
            require_matching_layout(analyzed_value_type(node.args[0]), result_type, node)
            kind = emitter.value_type(item_type(result_type, node))
            size = emitter.llvm_size(kind)
            return "ptr", emitter.allocated_value(
                f"call ptr @pyjs.tuple.concat({owner(emitter, allocator=gc_layouts.item_allocator(kind))}, ptr {receiver}, "
                f"ptr {arguments[0][1]}, i64 {size})")
        if operation == "__len__":
            return "i64", emitter.emit_value(f"load i64, ptr {receiver}")
        if operation == "__bool__":
            length = emitter.emit_value(f"load i64, ptr {receiver}")
            return "i1", emitter.emit_value(f"icmp ne i64 {length}, 0")
        if operation in {"__getitem__", "__slice__", "__mul__", "__rmul__"} and sequence_name(value_type) == "list":
            return emitter.sequence_call(operation, value_type, receiver, arguments, node)
        if operation in {"__slice__", "__mul__", "__rmul__"}:
            if not value_type.generic_types:
                # Arguments have already been evaluated, even though an empty
                # payload never needs copying or a concrete member type.
                if operation == "__slice__" and len(arguments) == 3:
                    from . import slices
                    step = slices.bound(emitter, arguments[2], node, 1)[0]
                    valid = emitter.emit_value(f"icmp ne i64 {step}, 0")
                    emitter.guard_exception(node, valid, "ValueError", "slice step cannot be zero")
                return "ptr", receiver
            result_type = analyzed_value_type(node)
            if result_type.tuple_variadic:
                raise LLVMUnsupported("LLVM heterogeneous tuple result requires a fixed shape", node)
            bounds = []
            for argument, (kind, _) in zip(node.args, arguments, strict=True):
                bound = integer_literal(getattr(argument, "python_node", argument), allow_bool=True)
                if bound is None and kind != "void":
                    raise LLVMUnsupported("LLVM heterogeneous tuple slicing/repetition requires literal bounds", node)
                bounds.append(bound)
            indexes = list(range(len(value_type.generic_types)))
            if operation == "__slice__":
                if len(bounds) == 3 and bounds[2] == 0:
                    emitter.guard_exception(node, "false", "ValueError", "slice step cannot be zero")
                    return "ptr", receiver
                selected = indexes[slice(*bounds)]
            else:
                selected = indexes * max(0, bounds[0])
            if selected == indexes:
                return "ptr", receiver
            values = tuple_items(emitter, value_type, receiver)
            return "ptr", new_tuple(emitter, result_type,
                                    [(emitter.value_type(values[index][0]), values[index][1]) for index in selected])
    if name in {"list", "set"} and operation in {"__eq__", "__ne__"}:
        other_name = builtin_name(analyzed_value_type(node.args[0]))
        if other_name == "frozenset":
            other_name = "set"
        # Set-like views and application equality overrides cannot use this
        # shortcut. These built-in container kinds are mutually unequal.
        if other_name in {"list", "set", "dict", "tuple"} - {name}:
            return "i1", str(operation == "__ne__").lower()
    if name in VIEWS and operation == "__bool__":
        return "i1", emitter.truth_value(node.func.value, "ptr", receiver)
    if (operation in COMPARISONS and (name in {"KeysView", "ItemsView"}
            or name == "set" and builtin_name(analyzed_value_type(node.args[0])) in {"KeysView", "ItemsView"})):
        from . import mapping_views
        return "i1", mapping_views.compare(emitter, operation, value_type, receiver,
                                           analyzed_value_type(node.args[0]), arguments[0][1], node)
    if name in {"KeysView", "ItemsView"} and operation in {"isdisjoint", "__contains__"}:
        from . import mapping_views
        compare = mapping_views.disjoint if operation == "isdisjoint" else mapping_views.contains
        return "i1", compare(emitter, value_type, receiver,
                             analyzed_value_type(node.args[0]), arguments[0][1], node)
    if name == "dict" and operation in {"keys", "values", "items"}:
        # A view owns its reference to the mapping, but has distinct identity.
        # Returning the mapping pointer itself would make separate keys() calls
        # identical and prevent future view-specific storage from composing.
        if emitter.module.uses_gc:
            size = emitter.llvm_size("%pyjs.mapping.view")
            view = emitter.allocated_value(f"call ptr @pyjs.gc.alloc(ptr {emitter.load_local('__heap')}, i64 {size})")
        else:
            view = emitter.arena_allocate("pyjs.mapping.view")
        emitter.emit_line(f"store ptr {receiver}, ptr {view}")
        return "ptr", view
    if name in {"dict", "list", "tuple"} and operation in {"__eq__", "__ne__"}:
        result = comparisons.equal_value(emitter, value_type, receiver, analyzed_value_type(node.args[0]), arguments[0][1], node)
        return "i1", (emitter.emit_value(f"xor i1 {result}, true") if operation == "__ne__" else result)
    if name in {"list", "tuple"} and operation in {"__lt__", "__le__", "__gt__", "__ge__"}:
        other_type, other = analyzed_value_type(node.args[0]), arguments[0][1]
        if getattr(node, "reverse", False):
            # Analysis may choose the reflected builtin method. Restore source
            # operand order for protocol errors; arguments were already evaluated.
            return "i1", comparisons.order_value(emitter, comparisons.REFLECTED[operation],
                                                 other_type, other, value_type, receiver, node)
        return "i1", comparisons.order_value(emitter, operation, value_type, receiver,
                                             other_type, other, node)
    if name in VIEWS | {"tuple"} and operation in {"__contains__", "count", "index"}:
        return comparisons.search(emitter, operation, value_type, receiver, arguments, node)
    if name == "set" and operation in {
        *COMPARISONS, "update", "union", "intersection", "difference", "symmetric_difference",
        "intersection_update", "difference_update", "symmetric_difference_update",
        "issubset", "issuperset", "isdisjoint", "__or__", "__and__", "__sub__", "__xor__",
        "__ior__", "__iand__", "__isub__", "__ixor__",
    }:
        return set_method(emitter, operation, value_type, receiver, arguments, node)
    if name == "dict" and operation in {"update", "__ior__"} and analyzed_value_type(node.args[0]) is not value_type:
        source_type = analyzed_value_type(node.args[0])
        if builtin_name(source_type) == "dict":
            from .mapping_keys import update_converted
            update_converted(emitter, receiver, value_type, arguments[0][1], source_type, node)
        else:
            insert_pairs(emitter, receiver, value_type, source_type, arguments[0][1], node)
        return ("ptr", receiver) if operation == "__ior__" else ("void", "")
    if name == "dict" and operation in {"__or__", "__ror__"}:
        return "ptr", mapping_union(emitter, operation, value_type, receiver, arguments, node)
    if name == "dict" and operation == "__ior__":
        key, member = emitter.dictionary_types(value_type)
        if analyzed_value_type(node.args[0]) is not value_type:
            raise LLVMUnsupported("LLVM mapping union requires identical key and value types", node)
        emitter.mapping_mutation("update", value_type, key, emitter.value_type(member), receiver, arguments, node)
        return "ptr", receiver
    if name == "list" and operation in {"extend", "__iadd__"} and analyzed_value_type(node.args[0]) is not value_type:
        expected = item_type(value_type)
        source_type = analyzed_value_type(node.args[0])
        if builtin_name(source_type) in {"list", "tuple"}:
            # Concrete sequences reserve the entire extension before publishing
            # any item. Iterators instead retain their consumed prefix on failure.
            count = emitter.emit_value(f"load i64, ptr {arguments[0][1]}")
            size = emitter.llvm_size(emitter.value_type(expected))
            reserved = emitter.emit_value(
                f"call i1 @pyjs.list.try.reserve.extension(ptr {emitter.load_local('__arena')}, "
                f"ptr {receiver}, i64 {count}, i64 {size})")
            emitter.guard_exception(node, reserved, "MemoryError", "native collection allocation failed")
        loop(emitter, source_type, arguments[0][1],
             lambda actual, value: append(emitter, receiver, expected, actual, value, node), node)
        return ("ptr", receiver) if operation == "__iadd__" else ("void", "")
    if name in {"dict", "set"} and operation == ("popitem" if name == "dict" else "pop"):
        if arguments or node.keywords:
            raise LLVMUnsupported("LLVM popitem/set.pop take no arguments", node)
        length = emitter.emit_value(f"load i64, ptr {receiver}")
        valid = emitter.emit_value(f"icmp ne i64 {length}, 0")
        message = "popitem(): dictionary is empty" if name == "dict" else "pop from an empty set"
        emitter.guard_exception(node, valid, "KeyError", repr(message))
        index = emitter.emit_value(f"sub i64 {length}, 1")
        key_type = item_type(value_type)
        key_kind = emitter.value_type(key_type)
        key_slot = emitter.emit_value(f"getelementptr {key_kind}, ptr {storage(emitter, receiver, 2)}, i64 {index}")
        key = emitter.emit_value(f"load {key_kind}, ptr {key_slot}")
        if name == "dict":
            member = emitter.dictionary_types(value_type)[1]
            kind = emitter.value_type(member)
            slot = emitter.emit_value(f"getelementptr {kind}, ptr {storage(emitter, receiver, 3)}, i64 {index}")
            item = emitter.emit_value(f"load {kind}, ptr {slot}")
            result = ("ptr", new_tuple(emitter, analyzed_value_type(node), [(key_kind, key), (kind, item)]))
            size = emitter.llvm_size(kind)
        else:
            result = key_kind, key
            size = "1"
        if name == "dict":
            emitter.emit_line(f"call void @pyjs.dict.popitem.order(ptr {receiver})")
        emitter.emit_line(f"call void @pyjs.dict.remove.index(ptr {receiver}, i64 {index}, i64 {emitter.llvm_size(key_kind)}, i64 {size})")
        return result
    if name in VIEWS and operation == "__len__":
        source = emitter.emit_value(f"load ptr, ptr {receiver}")
        return "i64", emitter.emit_value(f"load i64, ptr {source}")
    if name == "list" and operation == "sort":
        from . import callback_ops

        if arguments or any(keyword.arg not in {"reverse", "key"} for keyword in node.keywords):
            raise LLVMUnsupported("LLVM list.sort accepts key and reverse", node)
        keywords = {keyword.arg: emitter.expression(keyword.value) for keyword in node.keywords}
        reverse = keywords.get("reverse", ("i1", "false"))
        if reverse[0] != "i1":
            raise LLVMUnsupported("LLVM list.sort reverse must be bool", node)
        callback_ops.sort_in_place(emitter, value_type, receiver, keywords.get("key", ("ptr", "null"))[1],
                                   sort_key(node), reverse[1], node)
        return "void", ""
    return None


def mapping_union(emitter, operation, value_type, receiver, arguments, node):
    from . import mapping_keys

    other_type = analyzed_value_type(node.args[0])
    if builtin_name(other_type) != "dict":
        raise LLVMUnsupported("LLVM dictionary union requires a dict", node)
    key, expected = emitter.dictionary_types(value_type)
    other_key, actual = emitter.dictionary_types(other_type)
    if not same_analyzer_type(key, other_key):
        raise LLVMUnsupported("LLVM dictionary union requires matching key layouts", node)
    try:
        calls.validate_storage(emitter, actual, expected, node)
    except LLVMUnsupported as error:
        raise LLVMUnsupported("LLVM dictionary union requires compatible value layouts", node) from error
    sources = [(value_type, receiver, node.func.value), (other_type, arguments[0][1], node.args[0])]
    if operation == "__ror__":
        sources.reverse()
    first_type, first, _ = sources[0]
    # Copying the first operand never compares stored keys, even if equal keys
    # have changed since insertion. Converted copies preserve the same rule.
    result = (emitter.mapping_mutation("copy", value_type, key, emitter.value_type(expected), first, [], node)[1]
              if same_analyzer_type(first_type, value_type) else new_mapping(emitter, key, expected))
    frame = calls.root_values(emitter, result, receiver, arguments[0][1])
    for index, (source_type, source, source_node) in enumerate(sources):
        if same_analyzer_type(source_type, value_type):
            if index != 0:
                emitter.mapping_mutation("update", value_type, key, emitter.value_type(expected),
                                         result, [("ptr", source)], node, source_type=source_type)
        else:
            mapping_keys.update_converted(emitter, result, value_type, source, source_type, node,
                                          source_node=source_node)
    calls.pop_roots(emitter, frame)
    return result


def set_intersection(emitter, value_type, receiver, source_type, source, node, *, item_representation=None):
    from . import mapping_keys
    from .protocols import consumer

    expected = item_type(value_type)
    if (builtin_name(source_type) in {"set", "frozenset"}
            and not same_analyzer_type(item_type(source_type), expected)
            and not mapping_keys.can_reuse(emitter, expected, item_type(source_type))):
        # Both concrete-set paths must choose keys from the smaller operand,
        # including signed zero. Stage compatible fresh slots, then reuse the
        # ordinary selection path without reinterpreting either input array.
        converted = materialize(emitter, value_type, source_type, source, node,
                                item_representation=item_representation)
        converted_frame = calls.root_values(emitter, converted)
        result = set_intersection(emitter, value_type, receiver, value_type, converted, node)
        calls.pop_roots(emitter, converted_frame)
        return result
    result = new_mapping(emitter, expected, NATIVE_ENVIRONMENT.builtins.search("bool"))
    frame = calls.root_values(emitter, result, receiver, source)
    custom = mapping_keys.uses_callbacks(expected)
    if (custom and builtin_name(source_type) in {"set", "frozenset"}
            and emitter.value_type(item_type(source_type)) == emitter.value_type(expected)):
        if not mapping_keys.can_reuse(emitter, expected, item_type(source_type)):
            raise LLVMUnsupported("LLVM set membership requires matching item types", node)
        mapping_keys.set_operation(emitter, "intersection", expected, receiver, source, node, result=result)
        calls.pop_roots(emitter, frame)
        return result
    if builtin_name(source_type) in {"set", "frozenset"} and item_type(source_type) is expected:
        # Primitive equality can hide distinct payloads, notably signed zero.
        # Match concrete-set traversal just as the callback-aware path does.
        own_length = emitter.emit_value(f"load i64, ptr {receiver}")
        other_length = emitter.emit_value(f"load i64, ptr {source}")
        source_smaller = emitter.emit_value(f"icmp ule i64 {other_length}, {own_length}")
        searched = emitter.emit_value(f"select i1 {source_smaller}, ptr {receiver}, ptr {source}")
        source = emitter.emit_value(f"select i1 {source_smaller}, ptr {source}, ptr {receiver}")
        receiver = searched
    done = emitter.new_label("intersection.done")

    def consume(actual, value):
        calls.validate_storage(emitter, actual, expected, node)
        if not same_analyzer_type(actual, expected):
            _, value = convert_item(emitter, actual, expected, value, node, representation=item_representation)
            actual = expected
        emitter.value_semantics[(emitter.value_type(actual), value)] = actual
        if custom:
            index, _, hashed = mapping_keys.find(emitter, receiver, expected, emitter.value_type(actual), value, node)
            present = emitter.emit_value(f"icmp sge i64 {index}, 0")
        else:
            slot, _ = emitter.dictionary_lookup(receiver, value_type, emitter.value_type(actual), value, node,
                                                source_type=actual)
            present = emitter.emit_value(f"icmp ne ptr {slot}, null")
        insert, following = emitter.new_label("intersection.insert"), emitter.new_label("intersection.next")
        emitter.emit_line(f"br i1 {present}, label %{insert}, label %{following}")
        emitter.emit_line(f"{insert}:")
        slot = (mapping_keys.lookup(emitter, result, expected, emitter.value_type(actual), value, "1", node,
                                    insert=True, known_hash=hashed) if custom else
                emitter.dictionary_set_slot(result, expected, emitter.value_type(actual), value, "1", node))
        emitter.emit_line(f"store i1 true, ptr {slot}")
        count = emitter.emit_value(f"load i64, ptr {result}")
        length = emitter.emit_value(f"load i64, ptr {receiver}")
        complete = emitter.emit_value(f"icmp uge i64 {count}, {length}")
        # CPython stops after the last matching insertion, not before reading
        # an empty receiver's operand. Duplicate inputs must not count twice.
        emitter.emit_line(f"br i1 {complete}, label %{done}, label %{following}")
        emitter.emit_line(f"{following}:")

    # The last matching item jumps directly to done, bypassing loop cleanup.
    source_type, source, source_frame = consumer(emitter, source_type, source, node)
    loop(emitter, source_type, source, consume, node, acquired=True)
    emitter.emit_line(f"br label %{done}")
    emitter.emit_line(f"{done}:")
    calls.pop_roots(emitter, source_frame)
    calls.pop_roots(emitter, frame)
    return result


def set_discard_operand(emitter, value_type, receiver, source_type, source, node):
    from . import mapping_keys

    expected = item_type(value_type)
    if builtin_name(source_type) in {"set", "frozenset"}:
        if not mapping_keys.can_reuse(emitter, expected, item_type(source_type)):
            raise LLVMUnsupported("LLVM set difference requires matching item types", node)
        mapping_keys.set_operation(emitter, "discard", expected, receiver, source, node)
        return

    def consume(actual, value):
        if not is_return_type_compatible(expected, actual):
            raise LLVMUnsupported("LLVM set difference requires matching item types", node)
        kind = emitter.value_type(actual)
        emitter.value_semantics[(kind, value)] = actual
        emitter.mapping_mutation("discard", value_type, expected, "i1", receiver, [(kind, value)], node)

    # General iterables (including dictionaries) rehash every consumed key,
    # even after the receiver becomes empty. Earlier removals stay published.
    loop(emitter, source_type, source, consume, node)


def set_difference(emitter, value_type, receiver, arguments, node, inplace):
    from . import mapping_keys

    expected = item_type(value_type)
    (result_slot,), result_frame = calls.value_slots(emitter, ["ptr"])
    frame = calls.root_values(emitter, receiver, *(value for _, value in arguments))
    result = receiver
    if not inplace and not arguments:
        result = emitter.mapping_mutation("copy", value_type, expected, "i1", receiver, [], node)[1]
    emitter.emit_line(f"store ptr {result}, ptr {result_slot}")
    for index, (source_node, (_, source)) in enumerate(zip(node.args, arguments, strict=True)):
        source_type = analyzed_value_type(source_node)
        if hasattr(source_node, "mapping_source_type"):
            source_type = source_node.mapping_source_type
            source = emitter.emit_value(f"load ptr, ptr {source}")
        if not inplace and index == 0:
            if builtin_name(source_type) in {"set", "frozenset", "dict"}:
                if not mapping_keys.can_reuse(emitter, expected, item_type(source_type)):
                    raise LLVMUnsupported("LLVM set difference requires matching item types", node)
                result = new_mapping(emitter, expected, NATIVE_ENVIRONMENT.builtins.search("bool"))
                emitter.emit_line(f"store ptr {result}, ptr {result_slot}")
                own_length = emitter.emit_value(f"load i64, ptr {receiver}")
                other_length = emitter.emit_value(f"load i64, ptr {source}")
                quarter = emitter.emit_value(f"lshr i64 {own_length}, 2")
                smaller = emitter.emit_value(f"icmp ugt i64 {quarter}, {other_length}")
                copy, select, done = (emitter.new_label(label) for label in ("difference.copy", "difference.select", "difference.done"))
                emitter.emit_line(f"br i1 {smaller}, label %{copy}, label %{select}")
                emitter.emit_line(f"{copy}:")
                size = emitter.llvm_size(emitter.value_type(expected))
                copied = emitter.emit_value(f"call i1 @pyjs.dict.replace(ptr {emitter.load_local('__arena')}, "
                                             f"ptr {result}, ptr {receiver}, i64 {size}, i64 1)")
                emitter.guard_exception(node, copied, "MemoryError", "native set allocation failed")
                set_discard_operand(emitter, value_type, result, source_type, source, node)
                emitter.emit_line(f"br label %{done}")
                emitter.emit_line(f"{select}:")
                # The opposite traversal direction changes callback receivers.
                # Dict inputs reuse hashes here, but not in the copy path above.
                mapping_keys.set_operation(emitter, "select", expected, receiver, source, node,
                                           result=result, matches=False)
                emitter.emit_line(f"br label %{done}")
                emitter.emit_line(f"{done}:")
                continue
            result = emitter.mapping_mutation("copy", value_type, expected, "i1", receiver, [], node)[1]
            emitter.emit_line(f"store ptr {result}, ptr {result_slot}")
        set_discard_operand(emitter, value_type, result, source_type, source, node)
    calls.pop_roots(emitter, frame)
    calls.pop_roots(emitter, result_frame)
    return result


def set_symmetric_difference(emitter, value_type, receiver, arguments, node, inplace):
    from . import mapping_keys

    expected = item_type(value_type)
    source_node = node.args[0]
    source_type = analyzed_value_type(source_node)
    source = arguments[0][1]
    if hasattr(source_node, "mapping_source_type"):
        source_type = source_node.mapping_source_type
        source = emitter.emit_value(f"load ptr, ptr {source}")
    frame = calls.root_values(emitter, receiver, source)
    (temporary_slot,), temporary_frame = calls.value_slots(emitter, ["ptr"])
    concrete = builtin_name(source_type) in {"set", "frozenset", "dict"}
    if concrete and not mapping_keys.can_reuse(emitter, expected, item_type(source_type)):
        raise LLVMUnsupported("LLVM set symmetric difference requires matching item types", node)
    if not inplace or not concrete:
        if concrete:
            temporary = new_mapping(emitter, expected, NATIVE_ENVIRONMENT.builtins.search("bool"))
            emitter.emit_line(f"store ptr {temporary}, ptr {temporary_slot}")
            mapping_keys.update(emitter, temporary, source, expected, "1", node, keys_only=True,
                                copy_empty=source_type.generic_name != "dict")
        else:
            # Deduplicate completely before mutating or copying the receiver.
            protocol = analyzed_iterable_protocol(source_node)
            temporary = materialize(emitter, value_type, source_type, source, node,
                                    item_representation=protocol.item_representation)
            emitter.emit_line(f"store ptr {temporary}, ptr {temporary_slot}")
        source = temporary
    # A readonly XOR starts with the argument and toggles receiver keys into
    # it. Copying the receiver instead reverses observable equality callbacks.
    target, incoming = (receiver, source) if inplace else (source, receiver)
    mapping_keys.set_operation(emitter, "toggle", expected, target, incoming, node)
    calls.pop_roots(emitter, temporary_frame)
    calls.pop_roots(emitter, frame)
    return target


def set_method(emitter, operation, value_type, receiver, arguments, node):
    from . import mapping_keys

    expected = item_type(value_type)
    size = emitter.llvm_size(emitter.value_type(expected))
    custom = mapping_keys.uses_callbacks(expected)
    kind = 0 if custom else emitter.dictionary_key_kind(expected)
    types = [analyzed_value_type(argument) for argument in node.args]
    set_operand = len(types) == 1 and builtin_name(types[0]) in {"set", "frozenset"}
    if (operation in {"isdisjoint", "issuperset", "issubset"} and len(arguments) == 1
            and types[0] is not value_type and not set_operand):
        if operation == "issubset":
            protocol = analyzed_iterable_protocol(node.args[0])
            intersection = set_intersection(emitter, value_type, receiver, types[0], arguments[0][1], node,
                                            item_representation=protocol.item_representation)
            count = emitter.emit_value(f"load i64, ptr {intersection}")
            length = emitter.emit_value(f"load i64, ptr {receiver}")
            return "i1", emitter.emit_value(f"icmp eq i64 {count}, {length}")
        result = emitter.emit_value("alloca i1")
        emitter.emit_line(f"store i1 true, ptr {result}")
        done = emitter.new_label("disjoint.done")

        def consume(actual, value):
            calls.validate_storage(emitter, actual, expected, node)
            slot, _ = emitter.dictionary_lookup(receiver, value_type, emitter.value_type(actual), value, node,
                                                source_type=actual)
            predicate = "eq" if operation == "isdisjoint" else "ne"
            matches = emitter.emit_value(f"icmp {predicate} ptr {slot}, null")
            emitter.emit_line(f"store i1 {matches}, ptr {result}")
            following = emitter.new_label("disjoint.next")
            emitter.emit_line(f"br i1 {matches}, label %{following}, label %{done}")
            emitter.emit_line(f"{following}:")

        from .protocols import consumer
        source_type, source, frame = consumer(emitter, types[0], arguments[0][1], node)
        loop(emitter, source_type, source, consume, node, acquired=True)
        emitter.emit_line(f"br label %{done}")
        emitter.emit_line(f"{done}:")
        calls.pop_roots(emitter, frame)
        return "i1", emitter.emit_value(f"load i1, ptr {result}")
    if operation.startswith("__") and operation not in COMPARISONS:
        for other_type in types:
            if builtin_name(other_type) not in {"set", "frozenset"}:
                raise LLVMUnsupported("LLVM set operators require set or frozenset operands", node)
            calls.validate_storage(emitter, item_type(other_type), expected, node)
    if operation in {*COMPARISONS, "issubset", "issuperset", "isdisjoint"}:
        if len(arguments) != 1:
            raise LLVMUnsupported("LLVM set comparison requires one operand", node)
        return "i1", comparisons.set_compare(emitter, operation, value_type, receiver,
                                              types[0], arguments[0][1], node)
    names = {
        "__or__": "union", "__ior__": "union", "__and__": "intersection", "__iand__": "intersection",
        "__sub__": "difference", "__isub__": "difference", "__xor__": "symmetric_difference", "__ixor__": "symmetric_difference",
    }
    action = "union" if operation == "update" else names.get(operation, operation.removesuffix("_update"))
    inplace = operation.endswith("update") or operation in {"__ior__", "__iand__", "__isub__", "__ixor__"}
    if custom and action in {"difference", "symmetric_difference"}:
        apply = set_difference if action == "difference" else set_symmetric_difference
        result = apply(emitter, value_type, receiver, arguments, node, inplace)
        return ("void", "") if operation.endswith("update") else ("ptr", result)
    if action == "symmetric_difference" and types[0] is not value_type:
        # Python consumes/deduplicates the operand before copying the receiver;
        # a callback in that operand may mutate the receiver during this step.
        protocol = analyzed_iterable_protocol(node.args[0])
        other = materialize(emitter, value_type, types[0], arguments[0][1], node,
                            item_representation=protocol.item_representation)
        types, arguments = [value_type], [("ptr", other)]
    # intersection_update publishes only after all operands succeed. update
    # and difference_update instead expose each mutation before advancing.
    result = receiver if inplace or action == "intersection" and arguments else emitter.mapping_mutation(
        "copy", value_type, expected, "i1", receiver, [], node)[1]
    (result_slot,), frame = calls.value_slots(emitter, ["ptr"])
    emitter.emit_line(f"store ptr {result}, ptr {result_slot}")
    for source_node, other_type, (_, other) in zip(node.args, types, arguments, strict=True):
        if action == "union" and not inplace and builtin_name(other_type) in {"set", "frozenset"}:
            # union skips operands aliasing the original receiver, even if an
            # earlier iterable mutated it. Select the result itself to reuse
            # both mapping runtimes' no-callback self-update fast path.
            same = emitter.emit_value(f"icmp eq ptr {receiver}, {other}")
            other = emitter.emit_value(f"select i1 {same}, ptr {result}, ptr {other}")
        if custom and action == "union" and hasattr(source_node, "mapping_source_type"):
            other_type = source_node.mapping_source_type
            other = emitter.emit_value(f"load ptr, ptr {other}")
        if (custom and action == "union" and builtin_name(other_type) in {"set", "frozenset", "dict"}
                and mapping_keys.can_reuse(emitter, expected, item_type(other_type))):
            mapping_keys.update(emitter, result, other, expected, "1", node, keys_only=True,
                                copy_empty=other_type.generic_name != "dict")
            continue
        if action == "intersection":
            protocol = analyzed_iterable_protocol(source_node)
            result = set_intersection(emitter, value_type, result, other_type, other, node,
                                      item_representation=protocol.item_representation)
            emitter.emit_line(f"store ptr {result}, ptr {result_slot}")
            continue
        if other_type is not value_type:
            if action in {"union", "difference"}:
                def consume(actual, value, result=result, source_node=source_node):
                    calls.validate_storage(emitter, actual, expected, node)
                    protocol = analyzed_iterable_protocol(source_node)
                    kind, value = convert_item(emitter, actual, expected, value, node,
                                              representation=protocol.item_representation)
                    if action == "union":
                        slot = emitter.dictionary_set_slot(result, expected, kind, value, "1", node)
                        emitter.emit_line(f"store i1 true, ptr {slot}")
                    else:
                        emitter.mapping_mutation("discard", value_type, expected, "i1", result, [(kind, value)], node)

                loop(emitter, other_type, other, consume, node)
                continue
        if action == "difference":
            emitter.emit_line(f"call void @pyjs.set.intersect(ptr {result}, ptr {other}, i64 {size}, i8 {kind}, i1 true)")
        else:
            symbol = "pyjs.dict.update" if action == "union" else "pyjs.set.symmetric.difference"
            sizes = f"i64 {size}, i64 1" if action == "union" else f"i64 {size}"
            success = emitter.emit_value(f"call i1 @{symbol}(ptr {emitter.load_local('__arena')}, ptr {result}, ptr {other}, {sizes}, i8 {kind})")
            emitter.guard_exception(node, success, "MemoryError", "native set allocation failed")
    if inplace and action == "intersection":
        success = emitter.emit_value(f"call i1 @pyjs.dict.replace(ptr {emitter.load_local('__arena')}, "
                                     f"ptr {receiver}, ptr {result}, i64 {size}, i64 1)")
        emitter.guard_exception(node, success, "MemoryError", "native set allocation failed")
        result = receiver
    calls.pop_roots(emitter, frame)
    return ("void", "") if operation.endswith("update") else ("ptr", result)


def iterator_next(emitter, node, iterator, name, member):
    if name == "tuple" and not emitter.iterators[node.iterator][2].generic_types:
        emitter.emit_line(f"br label %{emitter.name(node.exhausted, 'block')}")
        return
    source = emitter.emit_value(f"load ptr, ptr {iterator}")
    index_slot = field(emitter, iterator, "pyjs.sequence.iterator", 1)
    index = emitter.emit_value(f"load i64, ptr {index_slot}")
    length = emitter.emit_value(f"load i64, ptr {source}")
    if name in VIEWS:
        expected = emitter.load_local(node.iterator + ".length")
        unchanged = emitter.emit_value(f"icmp eq i64 {length}, {expected}")
        emitter.guard_exception(node, unchanged, "RuntimeError", "dictionary changed size during iteration")
    available = emitter.emit_value(f"icmp ult i64 {index}, {length}")
    body = emitter.new_label("view.item")
    emitter.emit_line(f"br i1 {available}, label %{body}, label %{emitter.name(node.exhausted, 'block')}")
    emitter.emit_line(f"{body}:")
    value, width = read_item(emitter, name, member, source, index)
    emitter.assign_iterator_target(node.target, member, value)
    following = emitter.emit_value(f"add i64 {index}, {width}")
    emitter.emit_line(f"store i64 {following}, ptr {index_slot}")
    emitter.emit_line(f"br label %{emitter.name(node.body, 'block')}")
