"""Application descriptors and super access through checked native calls."""

import ast
import types

from pyjs.analysis.analyzer import analyzed_value_type, is_return_type_compatible
from pyjs.analysis.objects import Class, Function
from pyjs.analysis.type_relations import is_subclass
from pyjs.python import native as native_builtins

from . import calls, collection_ops, dom_ops, nullable, tagged
from .errors import LLVMUnsupported


def dispatch_name(function):
    # A getter and setter share a Python spelling, but not a callable ABI or
    # virtual slot. Keep both identities distinct through layout and emission.
    return function.name + (".setter" if function.is_property_setter else "")


def reject_super_write(e, attribute):
    if not e.is_super_call(attribute.value):
        return False
    # super() forwards reads, not writes: assignment targets the proxy, never
    # a base descriptor or instance field. Call only after evaluating the RHS.
    e.guard_exception(attribute, "false", "AttributeError",
                      f"'super' object has no attribute '{attribute.attr}' and no __dict__ for setting new attributes")
    return True


def check_super_field_read(e, attribute):
    if not e.is_super_call(attribute.value):
        return
    semantic = analyzed_value_type(attribute.value)
    for base in semantic.py_obj.__mro__:
        if attribute.attr in vars(base):
            descriptor = vars(base)[attribute.attr]
            if isinstance(descriptor, types.MemberDescriptorType):
                # A real slot descriptor reads instance storage through super;
                # ordinary instance-dictionary fields are not visible to it.
                return
            raise LLVMUnsupported("LLVM super field reads require a slot or a supported property descriptor", attribute)
    e.guard_exception(attribute, "false", "AttributeError",
                      f"'super' object has no attribute '{attribute.attr}'")


def access(e, attribute, assigned=None, *, check_layout=True):
    setter = assigned is not None
    accessors = getattr(attribute, "property_setters" if setter else "property_getters", ())
    semantic = analyzed_value_type(attribute.value)
    expected = None if setter else analyzed_value_type(attribute)
    result_kind = "void" if setter else e.expression_type(attribute)
    static = e.is_super_call(attribute.value)
    kind, receiver = e.expression(attribute.value)
    if setter and reject_super_write(e, attribute):
        return "void", None

    def invoke(member, kind, value, *, concrete=None):
        target = None
        for accessor in accessors:
            if is_subclass(member, accessor.cls) and (target is None or is_subclass(accessor.cls, target.cls)):
                target = accessor
        if target is not None:
            target = e.resolve_method(member, dispatch_name(target)) or target
        if concrete is not None:
            target = concrete
        elif (not static and target is not None and target.name == "textContent"
              and e.is_opaque_web_element_type(target.cls)
              and member in e.module.custom_element_types):
            # An inherited DOM default has no application virtual slot. Keep
            # the wrapper until selecting the actual class's accessor; only
            # the builtin branch may unwrap it and bypass override checks.
            def select(candidate):
                getter = candidate.find_attrs(target.name)
                accessor = getattr(getter, "property_setter", None) if setter else getter
                if not isinstance(accessor, Function) or not (accessor.is_property_setter if setter else accessor.is_property):
                    raise LLVMUnsupported("LLVM DOM textContent override must preserve the accessed property", attribute)
                if setter:
                    actual = e.value_semantics.get(assigned) or analyzed_value_type(attribute)
                    compatible = len(accessor.params) == 1 and is_return_type_compatible(accessor.params[0].annotation.obj, actual)
                else:
                    compatible = is_return_type_compatible(target.return_type, accessor.return_type)
                if not compatible:
                    raise LLVMUnsupported("LLVM DOM textContent override has an incompatible accessor type", attribute)
                return accessor

            def access_selected(accessor):
                result = invoke(member, kind, value, concrete=accessor)
                return "true" if setter else result

            result = calls.runtime_protocol(e, member, value, "i1" if setter else result_kind,
                                            select, access_selected, attribute,
                                            compatible=collection_ops.is_layout_subclass)
            return None if setter else result
        if setter:
            dom_ops.bind_reference(e, member, value, attribute.attr, assigned, attribute)
        if (kind == "ptr" and target is not None
                and getattr(target.cls, "py_obj", None) is native_builtins._WebTokenList):
            if setter or target.name != "length":
                raise LLVMUnsupported("LLVM classList only exposes the read-only length property", attribute)
            actual = "i64"
            result = dom_ops.token_query(e, value)
        elif (kind == "ptr" and target is not None
                and e.is_opaque_web_element_type(target.cls)):
            storage = e.current_function.cls if static else member
            actual = "ptr"
            result = dom_ops.property_access(e, target, storage, value, attribute, assigned,
                                            base_implementation=static or concrete is not None)
        else:
            if kind != "ptr" or target not in e.module.functions:
                raise LLVMUnsupported("LLVM properties require a reached application accessor on every member", attribute)
            if setter:
                # Shared analysis validates the one-value setter signature and all
                # member representations. The RHS is already evaluated and rooted.
                source = tagged.Value(attribute,
                    e.value_semantics.get(assigned) or analyzed_value_type(attribute), *assigned)
                source.representation = e.value_representations.get(assigned)
                arguments = [source]
                positional = [assigned]
            else:
                arguments, positional = [], []
            invocation = ast.copy_location(ast.Call(func=attribute, args=arguments, keywords=[]), attribute)
            actual, result = calls.bind_method(e, target, value, invocation, semantic=member,
                positional=positional, dynamic=not static and concrete is None)
        if setter:
            # Python assignment ignores fset's return value.
            return None
        e.value_semantics[actual, result] = target.return_type
        e.value_representations[actual, result] = target.return_representation
        if nullable.is_object(target.return_type):
            from . import object_values
            actual, result = object_values.narrow(e, result, expected, attribute,
                                                  check_layout=check_layout)
        # An object result widens every union arm; it is not a concrete member
        # to project out. Let the ordinary conversion box the active payload.
        if actual == tagged.STORAGE and not tagged.members(expected) and not nullable.is_object(expected):
            actual, result = tagged.narrow(e, result, expected, attribute)
        return e.coerce_value(actual, result, result_kind, attribute,
                              semantic=expected)[1]

    if kind == tagged.STORAGE:
        return result_kind, tagged.dispatch(e, semantic, receiver, result_kind, invoke)
    if not isinstance(semantic, Class):
        raise LLVMUnsupported("LLVM property access requires a concrete or tagged receiver", attribute)
    return result_kind, invoke(semantic, kind, receiver)
