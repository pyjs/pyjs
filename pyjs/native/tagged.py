"""Closed native unions: an explicit runtime kind and one word of payload.

Scalars keep their bits; references keep their existing pointer identity. The
collector already scans aligned words conservatively, so a payload slot can be
registered as a root without introducing another allocation or object header.
This is not the open-ended Python ``object`` representation.
"""

import ast
import inspect

from pyjs.analysis.analyzer import (
    analyzed_value_object,
    analyzed_value_type,
    callable_value_type,
)
from pyjs.analysis.objects import (
    Class,
    EvaluateOnce,
    Function,
    GenericClass,
    LiteralClass,
    StaticCast,
    UnionType,
)
from pyjs.analysis.type_relations import is_subclass
from pyjs.analysis.value_representation import analyzed_representation

from . import calls, collection_ops, dom_ops, dom_types, nullable
from .errors import LLVMUnsupported

STORAGE = "{ i64, i64 }"
INTEGER_BOUNDARY = "narrowed int may be bool; convert with int() before integer-only storage"
TAGS = {"NoneType": 0, "bool": 1, "int": 2, "float": 3, "str": 4,
        "bytes": 5, "list": 6, "dict": 7, "tuple": 8, "set": 9, "frozenset": 10,
        "NotImplementedType": 12, "range": 13, "slice": 14}
DOM_TAG = 11  # Opaque public Element; application class tags begin at 16.


class Value(ast.expr):
    """An already evaluated member supplied to ordinary expression lowering.

    This emitter-local node has no executable children. It lets a selected
    union arm reuse existing lowering without re-running the source expression
    or maintaining a second implementation of a builtin's semantics.
    """

    _fields = ()

    def __init__(self, source, semantic, kind, value):
        ast.copy_location(self, source)
        # Lowered allocations keep coordinates on their source expression.
        # Preserve that diagnostic link without adding executable children.
        self.source = source
        self.obj, self.kind, self.value = semantic, kind, value


def builtin_call(e, node):
    source = node.args[0]
    semantic = analyzed_value_type(source)
    if nullable.is_object(semantic):
        raise LLVMUnsupported("LLVM erased object builtin calls require narrowing the value", node)
    result_kind = e.expression_type(node)
    kind, value = e.expression(source)
    semantic = effective_type(semantic, kind)
    name = getattr(node.func.obj, "generic_name", None) or node.func.obj.name
    missing = {"len": "object of type 'NoneType' has no len()",
               "int": "int() argument must be a string, a bytes-like object or a real number, not 'NoneType'",
               "float": "float() argument must be a string or a real number, not 'NoneType'"}[name]

    def invoke(member, kind, value):
        if member.generic_name == "NoneType":
            e.guard_exception(node, "false", "TypeError", missing)
            return "zeroinitializer"
        selected = ast.Call(func=node.func, args=[], keywords=[])
        selected.__dict__.update(vars(node))
        # Plain ast.Call stores its result directly; the analyzed Call class
        # keeps it in value_obj (including portable numeric representation).
        selected.obj = analyzed_value_object(node)
        selected.args = [Value(source, member, kind, value)]
        actual, result = e.call(selected)
        return e.coerce_value(actual, result, result_kind, node)[1]

    if member := nullable.member(semantic):
        e.guard_exception(node, nullable.present(e, kind, value), "TypeError", missing)
        if kind != "ptr":
            value = e.emit_value(f"extractvalue {kind} {value}, 1")
        return result_kind, invoke(member, e.value_type(member), value)
    return result_kind, dispatch(e, semantic, value, result_kind, invoke)


def members(semantic):
    if not isinstance(semantic, UnionType) or nullable.member(semantic) or nullable.is_object(semantic):
        return ()
    # Distinct Literal refinements can collapse to the same runtime class.
    # Deduplicate that class, not its tag: list[int] and list[str] still have
    # different layouts and must be rejected below despite sharing a tag.
    result = tuple(dict.fromkeys(runtime_type(item) for item in semantic.types))
    opaque = [item for item in result if dom_types.is_opaque_type(item)]
    if len(opaque) > 1:
        # Opaque DOM declaration models expose different APIs but share one
        # pointer/tag. Dispatch their join through the common declaration base,
        # not whichever arm happened to win a duplicate tag. Keep the analyzer
        # types intact for API checks and mutable-container invariance; concrete
        # application wrappers must retain their separate tags and GC roots.
        common = dom_types.common_base(opaque)
        result = tuple(item for item in result if item not in opaque) + (common,)
    return result


def runtime_type(semantic):
    # Literal strings constrain analysis, but have the ordinary string layout
    # and operations at runtime. Never turn that refinement into a new tag.
    return semantic.super if isinstance(semantic, LiteralClass) else semantic


def tag(e, semantic):
    semantic = runtime_type(semantic)
    # Runtime type queries also pass unspecialized GenericClass declarations
    # (e.g. isinstance(value, list)), not only concrete collection storage types.
    # Application names must never alias the corresponding builtin tag.
    name = getattr(semantic, "generic_name", semantic.name) if semantic.container.scope.is_builtins else None
    if name in TAGS:
        return TAGS[name]
    if e.is_web_element_type(semantic) and semantic not in e.module.custom_element_types:
        # Public builtin DOM interfaces share the opaque native Element model;
        # application custom elements retain their own ordinary class tags.
        return DOM_TAG
    if semantic in e.module.classes:
        return 16 + sorted(e.module.classes, key=e.class_name).index(semantic)
    raise LLVMUnsupported(f"LLVM union member {semantic.name} has no concrete runtime tag")


def validate(e, semantic, node=None):
    seen = set()
    for member in members(semantic):
        current = tag(e, member)
        if current in seen:
            raise LLVMUnsupported("LLVM unions cannot distinguish different layouts of the same container class", node)
        seen.add(current)


def matches(e, actual, semantic):
    if collection_ops.builtin_name(semantic) == "object":
        return "true"
    candidates = (semantic.types if isinstance(semantic, UnionType) else (semantic,))
    tags = set()
    for member in candidates:
        tags.add(tag(e, member))
        if collection_ops.builtin_name(member) == "int":
            tags.add(TAGS["bool"])
        # The mapped Element base has no application layout of its own, but
        # custom-element tags still identify subclasses of that public base.
        if member in e.module.classes or e.is_web_element_type(member):
            relation = collection_ops.is_layout_subclass if member in e.module.classes else is_subclass
            tags.update(tag(e, child) for child in e.module.classes if relation(child, member))
    result = "false"
    for number in sorted(tags):
        equal = e.emit_value(f"icmp eq i64 {actual}, {number}")
        result = equal if result == "false" else e.emit_value(f"or i1 {result}, {equal}")
    return result


def parts(e, value):
    return (e.emit_value(f"extractvalue {STORAGE} {value}, 0"),
            e.emit_value(f"extractvalue {STORAGE} {value}, 1"))


def payload(e, semantic, bits):
    kind = e.value_type(semantic)
    if kind == "void":
        return kind, ""
    if kind == "i64":
        return kind, bits
    operation = {"i1": "trunc", "double": "bitcast", "ptr": "inttoptr"}[kind]
    return kind, e.emit_value(f"{operation} i64 {bits} to {kind}")


def pack(e, semantic, kind, value, node):
    member = nullable.member(semantic)
    if member:
        return nullable.dispatch(e, semantic, kind, value, STORAGE, "zeroinitializer",
                                 lambda concrete, storage, item: pack(e, concrete, storage, item, node))
    number = str(tag(e, semantic))
    if (semantic in e.module.classes and semantic not in e.module.vtable_roots
            and any(child is not semantic and collection_ops.is_layout_subclass(child, semantic)
                    for child in e.module.classes)):
        # A base-typed pointer may actually reference a subclass. Without a
        # runtime class header, tagging it as the base would silently make
        # subsequent isinstance checks false. Exact leaf classes remain safe.
        raise LLVMUnsupported("LLVM union widening of a base class requires runtime class identity", node)
    if kind == "ptr" and semantic in e.module.vtable_roots:
        table = e.emit_value(f"load ptr, ptr {value}")
        root = e.module.vtable_roots[semantic]
        # The trailing tag follows the parent identity and all method slots.
        slot = e.emit_value(calls.vtable_slot(e, table, root, len(e.module.vtable_slots[root])))
        number = e.emit_value(f"load i64, ptr {slot}")
    if kind == "void":
        bits = "0"
    elif kind == "i64":
        bits = value
    else:
        operation = {"ptr": "ptrtoint", "double": "bitcast", "i1": "zext"}[kind]
        bits = e.emit_value(f"{operation} {kind} {value} to i64")
    result = e.emit_value(f"insertvalue {STORAGE} zeroinitializer, i64 {number}, 0")
    return e.emit_value(f"insertvalue {STORAGE} {result}, i64 {bits}, 1")


def convert(e, kind, value, expected, node, semantic=None):
    if kind == STORAGE and expected == "ptr":
        alternatives = members(e.value_semantics.get((kind, value)))
        # Contextual collection typing may expose a single-container alias's
        # concrete target, optionally allowing None. Literal unions can also
        # collapse to that pointer layout; check the tag before unpacking.
        target = runtime_type(nullable.member(semantic) or semantic)
        if alternatives and all(member is target or nullable.member(semantic)
                                and member.generic_name == "NoneType" for member in alternatives):
            return narrow(e, value, semantic if nullable.member(semantic) else target, node)
        if (target in e.module.classes and alternatives
                and all(collection_ops.is_layout_subclass(member, target)
                        or nullable.member(semantic) and member.generic_name == "NoneType"
                        for member in alternatives)):
            # A closed union of application subclasses can share its nominal
            # base's pointer ABI. Do not extend this to covariant containers or
            # opaque DOM nodes: those need distinct layouts or wrapper unboxing.
            return narrow(e, value, semantic, node)
    if expected != STORAGE or kind == STORAGE:
        return None
    semantic = e.value_semantics.get((kind, value))
    if semantic is None:
        # Scalar storage is unambiguous even for compiler-created values.
        from .analysis import NATIVE_ENVIRONMENT
        name = {"void": "NoneType", "i1": "bool", "i64": "int", "double": "float"}.get(kind)
        semantic = NATIVE_ENVIRONMENT.builtins.search(name) if name else None
    if semantic is None:
        raise LLVMUnsupported("LLVM union construction requires the source value's concrete type", node)
    return expected, pack(e, semantic, kind, value, node)


def narrow(e, value, semantic, node):
    from . import dom_ops

    value = dom_ops.narrow_union(e, value, semantic, node)
    actual, bits = parts(e, value)
    valid = dom_ops.instancecheck(e, STORAGE, value, semantic)
    e.guard_exception(node, valid if valid is not None else matches(e, actual, semantic),
                      "TypeError", "union value changed after narrowing")
    if members(semantic):
        return STORAGE, value
    if collection_ops.builtin_name(nullable.member(semantic) or semantic) == "int":
        # isinstance(x, int) also accepts bool. Keep that runtime distinction
        # until an operation explicitly asks for numeric conversion.
        if analyzed_representation(node) is None:
            return STORAGE, value
        # A represented integer is a fixed numeric ABI, not an ordinary int
        # view that can still denote bool. Its width was checked by projection.
        e.guard_exception(node, e.emit_value(f"icmp ne i64 {actual}, {TAGS['bool']}"),
                          "TypeError", INTEGER_BOUNDARY)
    if member := nullable.member(semantic):
        kind, item = payload(e, member, bits)
        if kind == "ptr":
            return kind, item
        optional = nullable.pair(kind)
        present = e.emit_value(f"icmp ne i64 {actual}, 0")
        result = e.emit_value(f"insertvalue {optional} zeroinitializer, i1 {present}, 0")
        return optional, e.emit_value(f"insertvalue {optional} {result}, {kind} {item}, 1")
    return payload(e, semantic, bits)


def effective_type(semantic, kind):
    if kind == STORAGE and collection_ops.builtin_name(nullable.member(semantic) or semantic) == "int":
        from .analysis import NATIVE_ENVIRONMENT
        alternatives = semantic.types if isinstance(semantic, UnionType) else (semantic,)
        return UnionType(types=(*alternatives, NATIVE_ENVIRONMENT.builtins.search("bool")))
    return semantic


def untag_single_member(e, semantic, kind, value, node):
    """Expose an alias/refinement's concrete runtime class and sole layout."""
    if kind == STORAGE and len(alternatives := members(semantic)) == 1:
        semantic = alternatives[0]
        kind, value = narrow(e, value, semantic, node)
    return runtime_type(semantic), kind, value


def static_override_may_return_bool(target, receiver):
    """Inspect declarations without reaching otherwise unused subclass bodies.

    The imported Python class hierarchy already exists, even if analysis has
    not reached a subclass constructor. An unchanged inherited method or an
    explicitly integer-only override cannot introduce bool. Missing/unresolved
    annotations remain conservative until the emitter has the reached set.
    """
    owner = (receiver or target.cls).py_obj
    pending, seen = [owner], set()
    while pending:
        cls = pending.pop()
        if cls in seen:
            continue
        seen.add(cls)
        pending.extend(type.__subclasses__(cls))
        method = inspect.getattr_static(cls, target.name, None)
        if not isinstance(method, staticmethod) or method.__func__ is target.py_func:
            continue
        try:
            returned = inspect.get_annotations(method.__func__, eval_str=True).get("return")
        except Exception:
            # An unreached declaration can contain arbitrary lazy annotation
            # expressions. Failed evaluation must not crash unrelated code;
            # keep the possible Boolean tag until reached emission can decide.
            return True
        if returned is not int:
            return True
    return False


def narrowed_integer(node, slots=None, functions=(), *, scope=None, open_dispatch=False):
    """Does this integer view still need its Boolean runtime tag?

    Inference uses open_dispatch before all subclasses are reached. Emission
    uses the final function set to avoid unnecessary tagged integer storage.
    """
    from .type_queries import proven_integer
    if isinstance(node, EvaluateOnce):
        return narrowed_integer(node.body, slots, functions, scope=scope, open_dispatch=open_dispatch)
    if scope is not None and proven_integer(node, scope):
        # A copy may use integer storage; expression reads check the proof's
        # executable scope and runtime tag before materializing that payload.
        return False
    # A join can carry Class metadata for its result (for example x or 5).
    # That is a value expression, unlike a bare type[T] reference.
    if (not isinstance(node, (ast.BoolOp, ast.IfExp))
            and isinstance(analyzed_value_object(node), (Class, GenericClass))):
        return False  # Do not create a new type[T] dependency during emission.
    semantic = analyzed_value_type(node)
    if collection_ops.builtin_name(nullable.member(semantic) or semantic) != "int":
        return False
    if isinstance(node, (ast.BoolOp, ast.IfExp)):
        values = node.values if isinstance(node, ast.BoolOp) else (node.body, node.orelse)
        return any(narrowed_integer(value, slots, functions, scope=scope, open_dispatch=open_dispatch)
                   for value in values)
    if isinstance(node, StaticCast) and (
            nullable.is_object(analyzed_value_type(node.value))
            or members(analyzed_value_type(node.value))):
        return analyzed_representation(node) is None
    if isinstance(node, ast.Call):
        target = getattr(node.func, "obj", None)
        targets = getattr(node.func, "union_functions", ()) or (target,)
        receiver = calls.static_receiver(node, functions)
        if ((getattr(node.func, "union_functions", ()) or receiver is not None)
                and any(target.is_staticmethod for target in targets)):
            if open_dispatch and any(target in functions and static_override_may_return_bool(target, receiver)
                                     for target in targets):
                # Inference runs before the reached subclass set is final.
                # An instance-selected static override can return bool even
                # when its base declares int. Emission uses the closed set.
                return True
            # Static instance/union dispatch selects reached implementations,
            # not only the declarations recorded by shared analysis. Include
            # those bodies when deciding whether a result may carry bool.
            targets = (*targets, *(implementation for implementation in functions
                if implementation.cls is not None and any(
                    implementation.name == declared.name and declared.cls is not None
                    and collection_ops.is_layout_subclass(implementation.cls, receiver or declared.cls)
                    for declared in targets)))
        if any(target in functions and (members(target.return_type) or nullable.is_object(target.return_type)
                                       or collection_ops.builtin_name(nullable.member(target.return_type)
                                                                       or target.return_type) == "bool")
               for target in targets):
            # An overload refines the result but does not change its body's
            # union ABI; an int overload may still return a Boolean instance.
            # Builtin/inline lowering has no such body ABI: use only functions
            # selected for actual emission, not their declaration return types.
            return True
    original = getattr(analyzed_value_object(node), "narrowed_from", None)
    while original is not None:
        if members(original.type) or nullable.is_object(original.type):
            return True
        original = getattr(original, "narrowed_from", None)
    if slots is not None:
        from pyjs.analysis.ir import BlockArgument
        # Loop assignments can refine a load without a narrowed_from chain.
        # Lowered expression joins have the same storage contract as locals.
        if isinstance(node, (ast.Name, BlockArgument)):
            return slots.get(node.id if isinstance(node, ast.Name) else node.name) == STORAGE
    return False


def infer_local_storage(e, function, slots):
    """Propagate Boolean-preserving integer views through inferred local joins.

    A first-write layout is insufficient for forward copies and loop backedges.
    Only inferred integer slots can promote, once each; authored annotations and
    parameter ABIs stay fixed. This is local storage planning, not new IR types.
    """
    from pyjs.analysis.ir import Block, Jump

    if e.is_runtime_helper(function):
        return
    fixed = {parameter.arg for parameter in calls.parameters(function)}
    blocks = {block.name: block for block in function.ir.blocks if isinstance(block, Block)}
    writes = []
    for block in blocks.values():
        for statement in block.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if not isinstance(getattr(statement, "python_node", None), ast.Assign):
                    fixed.add(statement.target.id)
                elif statement.value is not None:
                    writes.append((statement.target.id, statement.value))
            elif isinstance(statement, ast.Assign):
                writes.extend((target.id, statement.value) for target in statement.targets
                              if isinstance(target, ast.Name))
            elif isinstance(statement, Jump):
                writes.extend((argument.name, value) for argument, value in zip(
                    blocks[statement.target].arguments, statement.arguments, strict=True))
    changed = True
    while changed:
        changed = False
        for name, value in writes:
            if (name not in fixed and slots.get(name) in {"i64", nullable.pair("i64")}
                    and narrowed_integer(value, slots, e.module.functions, scope=function.scope)):
                slots[name] = STORAGE
                changed = True


def numeric(e, node, kind, value):
    """Read a narrowed integer's payload only for an actual numeric operation."""
    semantic = e.value_semantics.get((kind, value))
    if semantic is None and hasattr(node, "obj"):
        semantic = analyzed_value_type(node)
    if kind == STORAGE and collection_ops.builtin_name(semantic) == "int":
        return "i64", parts(e, value)[1]
    return kind, value


def identity(e, left, right, node):
    from . import dom_ops

    def numeric_members(source):
        semantic = analyzed_value_type(source)
        candidates = semantic.types if isinstance(semantic, UnionType) else (semantic,)
        return {collection_ops.builtin_name(item) for item in candidates} & {"int", "float"}

    # Unboxed numbers have no Python object identity. Returning false would
    # even make `value is value` wrong; retain the concrete backend's explicit
    # boundary while allowing None/bool and reference identity through unions.
    if numeric_members(node.func.value) & numeric_members(node.args[0]):
        raise LLVMUnsupported("native numeric identity requires narrowing to reference values", node)
    a_kind, a = left
    b_kind, b = right
    a = dom_ops.identity_value(e, analyzed_value_type(node.func.value), a_kind, a, node)
    b = dom_ops.identity_value(e, analyzed_value_type(node.args[0]), b_kind, b, node)
    at, av = parts(e, a)
    bt, bv = parts(e, b)
    same_tag = e.emit_value(f"icmp eq i64 {at}, {bt}")
    same_value = e.emit_value(f"icmp eq i64 {av}, {bv}")
    reference = e.emit_value(f"icmp uge i64 {at}, 4")
    singleton = e.emit_value(f"icmp ule i64 {at}, 1")
    supported = e.emit_value(f"or i1 {reference}, {singleton}")
    same = e.emit_value(f"and i1 {same_tag}, {same_value}")
    return e.emit_value(f"and i1 {same}, {supported}")


def root_slot(e, kind, slot):
    if kind == "ptr":
        return slot
    if kind == STORAGE:
        return e.emit_value(f"getelementptr {STORAGE}, ptr {slot}, i32 0, i32 1")
    return None


def dispatch(e, semantic, value, result_kind, callback, *, runtime_classes=False, group=None):
    """Emit a closed switch; every case supplies its concrete semantic type.

    group may share a body for members with identical callback behavior. The
    payload storage kind must also match; callback receives a representative
    member, so callers must not group operations that depend on its exact type.
    """
    actual, bits = parts(e, value)
    result = e.emit_value(f"alloca {result_kind}") if result_kind != "void" else None
    done, invalid = e.new_label("union.done"), e.new_label("union.invalid")
    cases = []
    selected = {}
    for member in members(semantic):
        selected[tag(e, member)] = member
        if collection_ops.builtin_name(member) == "int":
            from .analysis import NATIVE_ENVIRONMENT
            selected[TAGS["bool"]] = NATIVE_ENVIRONMENT.builtins.search("bool")
        if member in e.module.classes:
            for child in e.module.classes:
                if collection_ops.is_layout_subclass(child, member):
                    previous = selected.get(tag(e, child))
                    if previous is None or collection_ops.is_layout_subclass(member, previous):
                        # Ordinary operations use the declared layout. Method
                        # lookup also needs the actual class: static methods
                        # have no virtual slot to repair a base-only selection.
                        selected[tag(e, child)] = child if runtime_classes else member
    bodies = {}
    for number, member in sorted(selected.items()):
        identity = (e.value_type(member), group(member)) if group is not None else number
        if identity not in bodies:
            bodies[identity] = member, e.new_label("union.member")
        cases.append((number, bodies[identity][1]))
    arms = " ".join(f"i64 {number}, label %{label}" for number, label in cases)
    e.emit_line(f"switch i64 {actual}, label %{invalid} [ {arms} ]")
    for member, label in bodies.values():
        e.emit_line(f"{label}:")
        kind, item = payload(e, member, bits)
        answer = callback(member, kind, item)
        if result is not None:
            e.emit_line(f"store {result_kind} {answer}, ptr {result}")
        e.emit_line(f"br label %{done}")
    e.emit_line(f"{invalid}:")
    e.guard_exception(e.allocation_node, "false", "TypeError", "unexpected native union tag")
    e.emit_line(f"br label %{done}")
    e.emit_line(f"{done}:")
    return e.emit_value(f"load {result_kind}, ptr {result}") if result is not None else None


def remember(e, node, kind, value):
    # Scalar kinds carry their own tag. References, narrowed tagged values and
    # optional pairs need source semantics. Functions retain their callable ABI;
    # class declarations are not instance values to instantiate here.
    if not (kind in {"ptr", STORAGE} or nullable.payload_kind(kind)) or not hasattr(node, "obj"):
        return
    if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.obj, (Class, GenericClass)):
        return
    e.value_semantics[kind, value] = callable_value_type(node)
    e.value_representations[kind, value] = analyzed_representation(node)


def method_call(e, node, semantic, receiver, *, positional=None):
    """Select the member before binding its own signature and defaults.

    Arguments appear in mutually exclusive cases, so their side effects execute
    once. The evaluated receiver already has the ordinary expression GC root;
    argument callbacks may remove it from its original owner safely. Reflected
    operators supply their already evaluated left operand; each arm still binds
    its own defaults without evaluating that operand again.
    """
    alternatives = members(semantic)
    if alternatives and all(collection_ops.builtin_name(member) in {"int", "bool"} for member in alternatives):
        # These inferred integer views preserve bool identity; the ordinary
        # integer operation needs an explicit numeric conversion, not an
        # application-class union method. Keep the diagnostic actionable.
        raise LLVMUnsupported(INTEGER_BOUNDARY, node)
    result_kind = e.expression_type(node)

    def invoke(member, kind, value):
        declaration = member.find_attrs(node.func.attr)
        target = (declaration if isinstance(declaration, Function) and declaration.is_staticmethod else
                  e.resolve_method(member, node.func.attr) if member in e.module.classes else None)
        if target is None and isinstance(declaration, Function) and e.is_opaque_web_element_type(declaration.cls):
            # Builtin DOM methods have no application function/virtual slot,
            # but each arm still carries its concrete wrapper and effects.
            target = declaration
            # Runtime-class union tags already prove an exact application
            # class; reselecting its descendants emits unreachable arms. The
            # opaque DOM tag is different: its payload may retain a wrapper.
            actual, result = dom_ops.method_call(e, target, member, value, node,
                base_implementation=member in e.module.custom_element_types)
        elif target is None or target.is_classmethod or target not in e.module.functions:
            raise LLVMUnsupported("LLVM union calls require application instance or static methods on every member", node)
        else:
            selected_node, operands = node, positional
            if target.name == "__hash__":
                from .hashing import guard_disabled_method
                # The runtime-class union tag has already selected this exact
                # member. Check shadowing before binding the ancestor's ABI,
                # but after evaluating the selected call's supplied operands.
                selected_node = guard_disabled_method(e, member, value, node,
                                                       dynamic=False, positional=positional)
                if selected_node is not node:
                    operands = None
            binding = calls.bind(e, target, selected_node, positional=operands, runtime_errors=True,
                                 project_argument=dom_ops.child_argument_projector(e, target, node))
            if binding is None:
                # The selected arm raised after evaluating its operands. Its
                # unreachable join value needs no callee or result adaptation.
                return "zeroinitializer" if result_kind != "void" else ""
            with binding as bound:
                # dispatch(runtime_classes=True) already selected the concrete
                # declaration, including the owner of its bound defaults.
                actual, result = calls.invoke(e, target, bound, node, receiver=value)
        return calls.join_result(e, target, actual, result, node)[1]

    return result_kind, dispatch(e, semantic, receiver, result_kind, invoke, runtime_classes=True)


def field_access(e, attribute, assigned=None, assigned_type=None):
    semantic = analyzed_value_type(attribute.value)
    expected = analyzed_value_type(attribute)
    result_kind = "void" if assigned is not None else e.expression_type(attribute)
    _, receiver = e.expression(attribute.value)

    def access(member, kind, value):
        from . import dom_ops, dom_state
        if descriptor := dom_state.field(e, member, attribute.attr):
            if assigned is not None:
                dom_state.write(e, member, value, descriptor, assigned, attribute)
                return None
            kind, value = dom_state.read(e, member, value, descriptor, attribute)
            e.value_semantics[kind, value] = member._self.find(attribute.attr).cls
            return e.coerce_value(kind, value, result_kind, attribute, semantic=expected)[1]
        storage, field, pointer = e.field_pointer(attribute, (member, value))
        declared = field.value_type
        if assigned is not None:
            dom_ops.bind_reference(e, member, value, attribute.attr, assigned, attribute)
            collection_ops.require_matching_layout(assigned_type, declared, attribute)
            kind, value = e.coerce_value(*assigned, e.value_type(declared), attribute, semantic=declared)
            kind, value = e.narrow_numeric(kind, value, storage, attribute)
            e.emit_line(f"store {kind} {value}, ptr {pointer}")
            return None
        value = e.emit_value(f"load {storage}, ptr {pointer}")
        dom_ops.check_proxy_field(e, member, attribute.attr, value, attribute)
        kind, value = e.widen_numeric(storage, value, field.numeric_format)
        e.value_semantics[kind, value] = declared
        e.value_representations[kind, value] = field.representation
        if kind == STORAGE and not members(expected) and not nullable.is_object(expected):
            return narrow(e, value, expected, attribute)[1]
        if (nullable.member(declared) and not nullable.member(expected)
                and not nullable.is_object(expected) and result_kind != STORAGE):
            nullable.check_narrowing(e, kind, value, expected, attribute, f"field {attribute.attr}")
        if nullable.is_object(declared):
            from . import object_values
            kind, value = object_values.narrow(e, value, expected, attribute)
        if result_kind == "void":
            return ""
        return e.coerce_value(kind, value, result_kind, attribute, semantic=expected)[1]

    return result_kind, dispatch(e, semantic, receiver, result_kind, access)
