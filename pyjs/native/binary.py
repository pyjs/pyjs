"""Runtime application binary dispatch without a second call ABI."""

import ast
import types

from pyjs.analysis.analyzer import (
    InferenceVisitor,
    analyzed_value_object,
    analyzed_value_type,
    get_type_members,
    is_return_type_compatible,
)
from pyjs.analysis.objects import Class, Function, UnionType
from pyjs.analysis.representation import apply_representation
from pyjs.analysis.type_relations import (
    inherited_sequence_slot,
    is_builtin_class,
    is_strict_runtime_subclass,
)
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.decorators import is_empty_inline, is_inline_for

from . import calls, collection_ops, enum_ops, nullable, object_values, tagged
from .errors import LLVMUnsupported


def operands(node):
    receiver, argument = node.func.value, node.args[0]
    return (argument, receiver) if getattr(node, "reverse", False) else (receiver, argument)


def is_application(value):
    return (isinstance(value, Class) and not value.container.scope.is_builtins
            and not enum_ops.scalar_name(value))


def is_sequence(value):
    return inherited_sequence_slot(value, "__mul__") is not None


def dynamic_count(value):
    return nullable.is_object(value) or isinstance(value, UnionType)


def repeat_uses_index(node):
    if getattr(node, "native_repeat_inplace", False):
        count = analyzed_value_type(node.args[0])
        if is_application(count):
            return descriptor(count, "__rmul__") is MISSING
    return True


def require_supported_result(semantic, node):
    # Comparisons negotiate the sentinel, arithmetic does not yet. Keep this
    # check on operator paths, not ordinary explicit calls to authored dunders.
    if any(is_builtin_class(member, "NotImplementedType") for member in get_type_members(semantic)):
        raise LLVMUnsupported("LLVM arithmetic operators do not yet support NotImplemented results", node)


def check_result(e, target, result, node):
    if (not isinstance(getattr(node, "operator", None), ast.operator)
            and not getattr(node, "inplace_method", None)
            and not getattr(node, "native_arithmetic_builtin", False)):
        return
    require_supported_result(target.inferred_return_type, node)
    require_supported_result(target.return_type, node)
    if nullable.is_object(target.return_type):
        # An object result can obtain the singleton from a parameter or field,
        # beyond static return inference. Preserve ordinary boxed results but
        # diagnose unsupported decline instead of silently treating it as data.
        e.module.uses_not_implemented = True
        valid = e.emit_value(f"icmp ne ptr {result[1]}, @pyjs.not_implemented")
        e.guard_exception(node, valid, "TypeError",
                          "LLVM arithmetic operators do not yet support NotImplemented results")


def retain(node, names):
    if (names is None or not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
            or node.func.attr not in names and not getattr(node, "native_repeat_inplace", False)
            or len(node.args) != 1 or node.keywords
            or is_empty_inline(node.func.obj.py_func, "native")):
        return
    semantics = tuple(analyzed_value_type(value) for value in operands(node))
    mixed_repeat = (names == ("__mul__", "__rmul__")
                    and any(is_sequence(value) for value in semantics)
                    and any(is_application(value) or dynamic_count(value) for value in semantics))
    if all(is_application(value) for value in semantics) or mixed_repeat:
        node.binary_methods = names
        node.runtime_protocols = (*getattr(node, "runtime_protocols", ()),
                                  *((value, (name,)) for value, name in zip(semantics, names, strict=True)))
        if mixed_repeat and is_sequence(node.func.obj.cls) and repeat_uses_index(node):
            # A selected application numeric method cannot fall through without
            # NotImplemented support. Do not reach its unused __index__ body.
            node.runtime_protocols += tuple((value, ("__index__",)) for value in semantics if is_application(value))


MISSING = object()


def descriptor(semantic, name):
    if method := inherited_sequence_slot(semantic, name):
        # Use the analyzed slot, not a CPython wrapper_descriptor. Literal and
        # nominal enum operands still reach application methods unchanged.
        return method.py_func
    for base in semantic.py_obj.__mro__:
        if name in vars(base):
            return vars(base)[name]
    return MISSING


def emit_repetition(e, node, sources, semantics):
    """Select a count's runtime type, then reuse ordinary binary/sequence calls.

    Capture and root both operands before selecting a slot: reflection or
    __index__ can mutate the source container and collect its former owner.
    This is not an early conversion to int; numeric reflection must run first.
    """
    position = next(index for index, semantic in enumerate(semantics) if dynamic_count(semantic))
    result_kind = e.expression_type(node)
    kinds = [e.expression_type(source) for source in sources]
    slots, frame = calls.value_slots(e, kinds)
    with calls.BoundCall([], [], e, frame):
        values = []
        for source, semantic, slot in zip(sources, semantics, slots, strict=True):
            kind, value = e.expression(source)
            e.emit_line(f"store {kind} {value}, ptr {slot}")
            captured = tagged.Value(source, semantic, kind, value)
            captured.obj = analyzed_value_object(source)
            apply_representation(captured, analyzed_representation(source))
            values.append(captured)

        def invoke(semantic, represented, kind, value):
            count = tagged.Value(sources[position], semantic, kind, value)
            count.obj = semantic._self
            apply_representation(count, represented)
            selected = values.copy()
            selected[position] = count
            receiver, argument = reversed(selected) if getattr(node, "reverse", False) else selected
            invocation = ast.Call(func=node.func, args=[], keywords=[])
            vars(invocation).update(vars(node))
            invocation.obj = analyzed_value_object(node)
            invocation.func = ast.Attribute(value=receiver, attr=node.func.attr, ctx=ast.Load())
            invocation.func.obj = node.func.obj
            invocation.args = [argument]
            if not is_application(semantic):
                del invocation.binary_methods
            return e.expression(invocation)[1]

        count = values[position]
        semantic = semantics[position]
        if nullable.is_object(semantic):
            from .analysis import NATIVE_ENVIRONMENT
            # Counts need only scalar kinds and application headers, never
            # boxed container layouts. Do not depend on boxing sites already
            # emitted: the caller that erases this count may be emitted later.
            candidates = tuple((NATIVE_ENVIRONMENT.builtins.search(name), None)
                               for name in ("int", "bool", "float"))
            # A class with no relevant slot cannot repeat a sequence. Let it
            # take the shared invalid-count path instead of expanding a full
            # binary call at every site for every unrelated application class.
            candidates += tuple((cls, None) for cls in e.module.classes
                                if any(descriptor(cls, name) is not MISSING
                                       for name in ("__index__", "__mul__", "__rmul__")))
            result = object_values.dispatch(e, count.value, result_kind, node, invoke,
                description="sequence repetition count", candidates=candidates,
                on_unsupported=lambda: e.guard_exception(
                    node, "false", "TypeError", "object cannot be interpreted as an integer"))
        elif nullable.member(semantic):
            e.guard_exception(node, nullable.present(e, count.kind, count.value), "TypeError",
                              "None cannot be interpreted as an integer")
            member = nullable.member(semantic)
            payload = count.value if count.kind == "ptr" else e.emit_value(
                f"extractvalue {count.kind} {count.value}, 1")
            result = invoke(member, None, e.value_type(member), payload)
        else:
            result = tagged.dispatch(e, semantic, count.value, result_kind,
                lambda member, kind, payload: invoke(member, None, kind, payload))
        return result_kind, result


def emit(e, node):
    sources = operands(node)
    semantics = tuple(analyzed_value_type(value) for value in sources)
    if any(is_sequence(value) for value in semantics) and any(dynamic_count(value) for value in semantics):
        return emit_repetition(e, node, sources, semantics)
    if not all(value in e.module.classes or is_sequence(value) for value in semantics):
        raise LLVMUnsupported("LLVM runtime binary dispatch requires application operands", node)
    names = node.binary_methods
    result_type, result_kind = analyzed_value_type(node), e.expression_type(node)
    kinds = [e.expression_type(value) for value in sources]
    slots, frame = calls.value_slots(e, kinds)
    with calls.BoundCall([], [], e, frame):
        values = []
        for source, semantic, slot in zip(sources, semantics, slots, strict=True):
            kind, value = e.expression(source)
            e.emit_line(f"store {kind} {value}, ptr {slot}")
            evaluated = tagged.Value(source, semantic, kind, value)
            evaluated.obj = semantic._self
            apply_representation(evaluated, analyzed_representation(source))
            values.append(evaluated)

        def select(left, right):
            forward, reflected = descriptor(left, names[0]), descriptor(right, names[1])
            if is_sequence(left):
                # Numeric reflection precedes sq_repeat/sq_inplace_repeat.
                # Explicit dunders never enter this bilateral dispatch.
                if reflected is not MISSING:
                    return right, True, reflected
                operation = "__imul__" if getattr(node, "native_repeat_inplace", False) else names[0]
                return left, False, descriptor(left, operation)
            if is_sequence(right) and forward is not MISSING:
                return left, False, forward

            def accepts(owner, name, raw, other):
                method = owner.find_attrs(name)
                # Typed models use a narrow signature to describe an operation
                # that CPython delegates via NotImplemented (timedelta + date,
                # for example). Preserve shared analysis's signature fallback;
                # do not invoke that body with an incompatible object layout.
                return (not isinstance(raw, types.FunctionType) or not isinstance(method, Function)
                        or len(method.params) != 1
                        or is_return_type_compatible(method.params[0].annotation.obj, other))
            # A strict subtype gets priority only if it provides a different
            # reflected implementation. Inheriting the same function is not
            # an override; operands with identical classes never reflect first.
            if (is_strict_runtime_subclass(right, left)
                    and reflected is not MISSING and reflected is not descriptor(left, names[1])
                    and accepts(right, names[1], reflected, left)):
                return right, True, reflected
            if forward is not MISSING and accepts(left, names[0], forward, right):
                return left, False, forward
            if left is not right and reflected is not MISSING and accepts(right, names[1], reflected, left):
                return right, True, reflected
            return left, False, MISSING

        def prepare(selection, left, right):
            # Validate every class pair before grouping. Sharing an emitted arm
            # must not let a representative class hide an incompatible layout.
            owner, reverse, raw = selection
            if isinstance(method := owner.find_attrs(names[int(reverse)]), Function):
                require_supported_result(method.return_type, node)
            if not isinstance(raw, types.FunctionType):
                if raw is not MISSING and raw is not None:
                    raise LLVMUnsupported("LLVM binary operators require ordinary application methods", node)
                symbol = InferenceVisitor.BIN_OP_SYMBOLS[type(node.operator)]
                message = ("'NoneType' object is not callable" if raw is None else
                           f"unsupported operand type(s) for {symbol}: '{left.py_obj.__name__}' and '{right.py_obj.__name__}'")
                return message, False
            if raw is node.func.obj.py_func and reverse == getattr(node, "reverse", False):
                return raw, reverse
            operation = ("__imul__" if is_sequence(owner) and getattr(node, "native_repeat_inplace", False)
                         else names[int(reverse)])
            method = owner.find_attrs(operation) if is_sequence(owner) else e.resolve_method(owner, operation)
            if method is None or method.py_func is not raw or (not is_sequence(owner) and method not in e.module.functions):
                if is_inline_for(raw, "native"):
                    raise LLVMUnsupported("LLVM runtime binary inline overrides are not supported", node)
                declared = owner.find_attrs(names[int(reverse)])
                if not isinstance(declared, Function) or declared.py_func is not raw:
                    raise LLVMUnsupported("LLVM runtime binary aliases require an analyzed protocol declaration", node)
                raise LLVMUnsupported("LLVM binary operators require a reached ordinary application method", node)
            if len(method.params) != 1 or method.vararg is not None or method.kwarg is not None:
                raise LLVMUnsupported("LLVM binary methods require one fixed operand parameter", node)
            other = left if reverse else right
            if not is_return_type_compatible(method.params[0].annotation.obj, other):
                raise LLVMUnsupported(
                    f"LLVM runtime binary operand must preserve its analyzed type for {owner.name}.{method.name}", node)
            if not is_return_type_compatible(result_type, method.return_type):
                raise LLVMUnsupported("LLVM runtime binary result must preserve its analyzed type", node)
            if method.return_representation != analyzed_representation(node):
                raise LLVMUnsupported("LLVM runtime binary result must preserve its numeric representation", node)
            collection_ops.require_matching_layout(method.return_type, result_type, node)
            return method, reverse

        def invoke(choice):
            method, reverse = choice
            if isinstance(method, str):
                e.guard_exception(node, "false", "TypeError", method)
                return "zeroinitializer"
            receiver, argument = (values[1], values[0]) if reverse else values
            if method is node.func.obj.py_func or isinstance(method, Function) and is_sequence(method.cls):
                # Reuse original/sequence lowering with evaluated operands;
                # removing only our marker avoids dispatch recursion. Builtin
                # repetition keeps the checked-index and allocation path.
                invocation = ast.Call(func=node.func, args=node.args, keywords=node.keywords)
                invocation.__dict__.update(vars(node))
                del invocation.binary_methods
                target = node.func.obj if method is node.func.obj.py_func else method
                invocation.func = ast.Attribute(value=receiver, attr=target.name, ctx=ast.Load())
                invocation.func.obj = target
                invocation.args = [argument]
                invocation.reverse = False
                return e.coerce_value(*e.expression(invocation), result_kind, node, semantic=result_type)[1]
            invocation = ast.copy_location(ast.Call(func=node.func, args=[argument], keywords=[]), node)
            with calls.bind(e, method, invocation) as bound:
                actual, result = calls.invoke(e, method, bound, node, receiver=receiver.value)
            e.value_semantics[actual, result] = method.return_type
            e.value_representations[actual, result] = method.return_representation
            return e.coerce_value(actual, result, result_kind, node, semantic=result_type)[1]

        def compatible(candidate, base):
            # An annotation can retain a layout without making its methods
            # callable. Use the same runtime population as protocol retention.
            return ((candidate is base or candidate in e.module.entry_function.compilation_objects)
                    and collection_ops.is_layout_subclass(candidate, base))

        candidates = ([semantics[1]] if is_sequence(semantics[1]) else
                      [candidate for candidate in sorted(e.module.classes, key=e.class_name)
                       if compatible(candidate, semantics[1])])
        right_indices = {candidate: index for index, candidate in enumerate(candidates)}

        def row(left):
            return tuple(prepare(select(left, right), left, right) for right in right_indices)

        def left_case(choices):
            if is_sequence(semantics[1]):
                return invoke(choices[0])
            return calls.runtime_protocol(
                e, semantics[1], values[1].value, result_kind,
                lambda right: choices[right_indices[right]], invoke, node,
                compatible=compatible)

        # Equal decision rows share the left arm; equal implementations share
        # the right arm. An inherited-only hierarchy becomes one direct call,
        # not N*N copies at each operator site. Missing-method messages retain
        # their class names in the key, and strict-subtype priority is selected
        # before grouping, not approximated from a representative class.
        if is_sequence(semantics[0]):
            result = left_case(row(semantics[0]))
        else:
            result = calls.runtime_protocol(e, semantics[0], values[0].value, result_kind,
                                            row, left_case, node, compatible=compatible)
        return result_kind, result
