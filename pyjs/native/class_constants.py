"""Read-only application class values through existing runtime-class dispatch."""

import ast
import inspect

from pyjs.analysis.analyzer import (
    analyzed_value_object,
    analyzed_value_type,
    get_type_members,
)
from pyjs.analysis.objects import Class, Instance
from pyjs.analysis.value_representation import (
    analyzed_representation,
    set_analyzed_representation,
)

from . import calls, collection_ops, persistent, tagged
from .errors import LLVMUnsupported


def declaration(value):
    return (isinstance(value, Instance) and isinstance(value.container, Class)
            and value.static_value is not None
            and not value.container.container.scope.is_builtins)


def read(e, attribute):
    if (not isinstance(attribute, ast.Attribute)
            or getattr(attribute, "property_getters", ())):
        return None
    owner = analyzed_value_object(attribute.value)
    if not declaration(attribute.obj):
        if isinstance(owner, Class):
            return None
        semantic = analyzed_value_type(attribute.value)
        # A union read has a merged declaration; ordinary fields (including
        # dataclass defaults) must keep their existing instance-storage path.
        if not tagged.members(semantic) or not any(
                isinstance(member, Class) and member._self.find_attrs(attribute.attr) is None
                and declaration(member.find_attrs(attribute.attr))
                for member in get_type_members(semantic)):
            return None
    expected = analyzed_value_type(attribute)
    result_kind = e.expression_type(attribute)

    def constant(field):
        if not declaration(field) or not isinstance(field.static_value, ast.Constant):
            raise LLVMUnsupported("LLVM class constants require immutable scalar values", attribute)
        value = persistent.literal(field.static_value, field.cls, attribute)
        set_analyzed_representation(value, field.representation)
        kind, result = e.expression(value)
        return e.coerce_value(kind, result, result_kind, attribute, semantic=expected)[1]

    def checked(candidate, field):
        # Shared discovery can omit an unsupported override and expose an
        # inherited declaration. Verify actual lookup even for symbolic and
        # lexical-super reads, not just runtime instance dispatch.
        if (not declaration(field)
                or inspect.getattr_static(candidate.py_obj, attribute.attr) is not field.py_obj):
            raise LLVMUnsupported("LLVM class constant overrides must remain scalar declarations", attribute)
        collection_ops.require_declaration_layout(field.cls, expected, attribute,
            actual_representation=field.representation,
            expected_representation=analyzed_representation(attribute))
        return field

    if isinstance(owner, Class):
        # A symbolic class name is not a runtime type object. In particular,
        # do not ask analyzed_value_type to specialize type[Class] at emission.
        if type(owner.py_obj).__getattribute__ is not type.__getattribute__:
            raise LLVMUnsupported("LLVM class constants require ordinary metaclass lookup", attribute)
        return result_kind, constant(checked(owner, attribute.obj))

    def select(candidate):
        python_type = candidate.py_obj
        if (python_type.__getattribute__ is not object.__getattribute__
                or hasattr(python_type, "__getattr__")):
            raise LLVMUnsupported("LLVM class constants require ordinary attribute lookup", attribute)
        if any(field.name == attribute.attr for field in e.module.layout_fields[candidate]):
            if tagged.members(semantic):
                raise LLVMUnsupported("LLVM union reads cannot mix class constants and instance fields", attribute)
            raise LLVMUnsupported("LLVM class constants cannot be shadowed by instance storage", attribute)
        return checked(candidate, candidate.find_attrs(attribute.attr))

    semantic = analyzed_value_type(attribute.value)
    kind, receiver = e.expression(attribute.value)
    if e.is_super_call(attribute.value):
        return result_kind, constant(checked(semantic, attribute.obj))

    def access(member, kind, value):
        if kind != "ptr" or member not in e.module.classes:
            raise LLVMUnsupported("LLVM class constants require an application receiver", attribute)
        return calls.runtime_protocol(e, member, value, result_kind, select, constant,
                                      attribute, compatible=collection_ops.is_layout_subclass)

    if kind == tagged.STORAGE:
        return result_kind, tagged.dispatch(e, semantic, receiver, result_kind, access)
    return result_kind, access(semantic, kind, receiver)
