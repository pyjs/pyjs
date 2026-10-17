"""Checked comparison of boxed values using their registered concrete layouts."""

from pyjs.analysis.type_relations import same_analyzer_type

from . import (
    calls,
    collection_ops,
    comparisons,
    mapping_keys,
    nullable,
    object_values,
    tagged,
)
from .analysis import NATIVE_ENVIRONMENT
from .errors import LLVMUnsupported


def invoke(e, left, right, node, operation, identity, layouts=None):
    key = layouts, operation, identity
    if key not in e.module.erased_comparisons:
        e.module.erased_comparisons[key] = f"pyjs.object.compare.{len(e.module.erased_comparisons)}", node
    symbol, _ = e.module.erased_comparisons[key]
    arguments = [*e.context_arguments(), ("ptr", left), ("ptr", right)]
    actual = ", ".join(f"{kind} {value}" for kind, value in arguments)
    result = e.emit_value(f"call i1 @{symbol}({actual})")
    e.check_active_exception(node)
    return result


def call(e, left_type, left, right_type, right, node, *, operation, identity):
    object_type = NATIVE_ENVIRONMENT.builtins.search("object")
    none_type = NATIVE_ENVIRONMENT.builtins.search("NoneType")
    operands = [(semantic, "void" if semantic is none_type else e.value_type(semantic), value)
                for semantic, value in ((left_type, left), (right_type, right))]
    # The second boxing operation can allocate or fail. Retain both originals
    # and each completed box until the comparison and its callbacks finish.
    original = [(kind, value) for _, kind, value in operands if kind in {"ptr", tagged.STORAGE}]
    original_slots, frame = calls.value_slots(e, [kind for kind, _ in original])
    for slot, (kind, value) in zip(original_slots, original, strict=True):
        e.emit_line(f"store {kind} {value}, ptr {slot}")
    roots, boxes_frame = calls.value_slots(e, ["ptr", "ptr"])
    boxed = []
    for index, (semantic, kind, value) in enumerate(operands):
        _, box = object_values.convert(e, kind, value, object_type, node, actual=semantic,
                                      representation=e.value_representations.get((kind, value)))
        e.emit_line(f"store ptr {box}, ptr {roots[index]}")
        boxed.append(box)
    result = invoke(e, *boxed, node, operation, identity)
    calls.pop_roots(e, boxes_frame)
    calls.pop_roots(e, frame)
    return result


def dispatch(e, left, right, node, operation, identity, left_layout=None):
    def with_left(left_type, left_representation, left_kind, left_value):
        layouts = ((left_type, left_representation), None)
        return invoke(e, left, right, node, operation, identity, layouts)

    def with_right(right_type, right_representation, right_kind, right_value):
        left_type = left_layout[0]
        if any(object_values.runtime_name(item) == "dom" for item in (left_type, right_type)):
            # Erased DOM transport preserves identity, not rich comparison
            # dispatch through an opaque node's lost application wrapper.
            # Reject only the selected pair, not unrelated boxed comparisons.
            e.guard_exception(node, "false", "TypeError", "erased DOM equality requires typed operands")
            return "false"
        left_name, right_name = (collection_ops.builtin_name(value) for value in (left_type, right_type))
        numeric = {"bool", "int", "float"}
        if (left_name is not None and right_name is not None and left_name != right_name
                and not {left_name, right_name} <= numeric
                and not {left_name, right_name} <= {"set", "frozenset"}):
            # Different builtin families cannot be equal. Avoid a comparator
            # body (and unsupported child-layout checks) for impossible pairs.
            return str(operation == "__ne__").lower()
        if left_type in e.module.classes or right_type in e.module.classes:
            authored = any(comparisons.disabled_method(semantic, name)
                           or getattr(semantic.find_attrs(name), "cls", None) in e.module.classes
                           for semantic in (left_type, right_type) if semantic in e.module.classes
                           for name in {"__eq__", operation})
            if not authored:
                predicate = "ne" if operation == "__ne__" else "eq"
                return e.emit_value(f"icmp {predicate} ptr {left}, {right}")
        return invoke(e, left, right, node, operation, identity,
                      (left_layout, (right_type, right_representation)))

    # Both dispatch levels and concrete pairs are outlined. Nesting right's
    # decoder inside every left branch makes -O0 reserve O(types squared)
    # scratch per recursive frame, even though only one branch executes.
    if left_layout is None:
        return object_values.dispatch(e, left, "i1", node, with_left, description="comparison", decode=False)
    return object_values.dispatch(e, right, "i1", node, with_right, description="comparison", decode=False)


def unsupported_layout(e, layouts, operation, node):
    """Check a pair without emitting IR, so unused layouts cannot poison it."""
    left_type, right_type = (item[0] for item in layouts)
    if any(represented is not None for _, represented in layouts):
        # Concrete numeric operators consume representation metadata. The
        # recursive object edge cannot erase it and silently compare widths
        # as ordinary numbers; keep this boundary until leaf transport carries
        # that contract through every nested comparison.
        return "LLVM erased equality requires ordinary item representations"
    for semantic in (left_type, right_type):
        if semantic in e.module.classes:
            for name in {"__eq__", operation}:
                method = semantic.find_attrs(name)
                if getattr(method, "cls", None) not in e.module.classes:
                    continue
                if method not in e.module.functions:
                    return "LLVM erased equality requires a lowered body"
                if len(method.params) != 1 or not nullable.is_object(method.params[0].annotation.obj):
                    return "LLVM erased equality callbacks require an object parameter"
                if not comparisons.supported_result(method.return_type):
                    return "LLVM erased equality callbacks require a builtin bool result or NotImplemented"
    left_name, right_name = (collection_ops.builtin_name(value) for value in (left_type, right_type))
    if left_name == right_name == "dict":
        if not mapping_keys.comparable(e, e.dictionary_types(left_type)[0], e.dictionary_types(right_type)[0]):
            return "LLVM mapping comparisons require matching key types"
    if {left_name, right_name} <= {"set", "frozenset"}:
        a, b = collection_ops.item_type(left_type), collection_ops.item_type(right_type)
        try:
            if not (same_analyzer_type(a, b) or mapping_keys.can_reuse(e, b, a) or mapping_keys.can_reuse(e, a, b)):
                return "LLVM set comparisons require matching item types"
        except LLVMUnsupported as error:
            return str(error)
    if left_name == right_name == "tuple" and (left_type.tuple_variadic or right_type.tuple_variadic):
        try:
            collection_ops.require_matching_layout(left_type, right_type, node)
        except LLVMUnsupported as error:
            return str(error)
    return None


def concrete(e, left, right, node, layouts, operation):
    left_type, right_type = (item[0] for item in layouts)
    if problem := unsupported_layout(e, layouts, operation, node):
        # Erased dispatch sees every registered layout, including values only
        # formatted elsewhere. Fail only if this unsupported pair is selected;
        # never catch an emitter failure after it has produced partial IR.
        e.guard_exception(node, "false", "TypeError", problem)
        return "false"
    if left_type in e.module.classes or right_type in e.module.classes:
        # Pass the original boxes, not scalar bits masquerading as pointers.
        object_type = NATIVE_ENVIRONMENT.builtins.search("object")
        return comparisons.object_compare(
            e, left_type if left_type in e.module.classes else object_type, left,
            right_type if right_type in e.module.classes else object_type, right,
            node, operation=operation, identity=False)

    result = comparisons._equal_value(e, left_type, object_values.known_payload(e, left, left_type),
                                      right_type, object_values.known_payload(e, right, right_type), node)
    return e.emit_value(f"xor i1 {result}, true") if operation == "__ne__" else result


def register_members(e):
    """Freeze the transitive layout set before any dispatch table is emitted."""
    from pyjs.analysis.objects import UnionType

    seen = set()
    def visit(semantic, represented):
        key = semantic, represented
        if key in seen or nullable.is_object(semantic):
            return
        seen.add(key)
        if represented is not None:
            # Registered represented layouts receive a checked TypeError in
            # concrete(); do not invent ordinary child layouts for them.
            return
        if isinstance(semantic, UnionType):
            for member in semantic.types:
                visit(member, None)
            return
        e.module.erased_candidates[semantic, represented] = None
        for member in (semantic.generic_types or {}).values():
            visit(member, None)
    for semantic, represented in tuple(e.module.erased_candidates):
        visit(semantic, represented)


def definition(parent, key):
    from .llvm import FunctionEmitter

    layouts, operation, identity = key
    symbol, node = parent.module.erased_comparisons[key]
    e = FunctionEmitter(parent.module)
    e.erased_comparison = True
    e.stack_allocations = []
    e.allocation_node = node
    e.return_type = e.return_storage_type = "i1"
    parameters = [name for name, enabled in (("__arena", e.module.uses_arena),
                  ("__heap", e.module.uses_gc), ("__exception", e.module.uses_exceptions)) if enabled]
    for name in parameters:
        e.slots[name], e.slot_types[name] = f"%slot.{name}", "ptr"
        e.emit_line(f"%slot.{name} = alloca ptr")
        e.emit_line(f"store ptr %{name}, ptr %slot.{name}")
    if e.module.uses_gc:
        e.gc_frame = calls.root_values(e, "%left", "%right")
    if layouts is None or layouts[1] is None:
        value = dispatch(e, "%left", "%right", node, operation, identity, layouts[0] if layouts else None)
    else:
        result = e.emit_value("alloca i1")
        e.emit_line(f"store i1 true, ptr {result}")
        compare, done = e.new_label("erased.compare"), e.new_label("erased.done")
        same = e.emit_value("icmp eq ptr %left, %right") if identity else "false"
        e.emit_line(f"br i1 {same}, label %{done}, label %{compare}")
        e.emit_line(f"{compare}:")
        with calls.recursion_scope(e, node, "maximum recursion depth exceeded in comparison"):
            value = concrete(e, "%left", "%right", node, layouts, operation)
        e.emit_line(f"store i1 {value}, ptr {result}")
        e.emit_line(f"br label %{done}")
        e.emit_line(f"{done}:")
        value = e.emit_value(f"load i1, ptr {result}")
    calls.pop_roots(e, e.gc_frame)
    e.emit_line(f"ret i1 {value}")
    if e.module.uses_exceptions:
        e.emit_line("pyjs.exception.return:")
        e.restore_gc_frame()
        calls.pop_roots(e, e.gc_frame)
        e.emit_line("ret i1 false")
    signature = ", ".join([*(f"ptr %{name}" for name in parameters), "ptr %left", "ptr %right"])
    # Re-inlining the dispatch levels can combine all inactive branches'
    # stack slots, defeating the bounded-frame design even under -O2.
    return [f"define private i1 @{symbol}({signature}) noinline {{", "entry:",
            *(f"  {line}" for line in (*e.stack_allocations, *e.lines)), "}"]


def definitions(parent, emitted):
    output = []
    while pending := [key for key in parent.module.erased_comparisons if key not in emitted]:
        for key in pending:
            emitted.add(key)
            output.extend(definition(parent, key))
    return output
