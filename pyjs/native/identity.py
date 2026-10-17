"""Original reference identity across non-owning interface/convention views."""

from . import (
    callable_adapters,
    dom_ops,
    enum_ops,
    iterable_views,
    iterator_ops,
    nullable,
    object_values,
    tagged,
)
from .errors import LLVMUnsupported


def pointer(e, semantic, kind, value, node):
    if kind == "void":
        return "null"
    if kind == tagged.STORAGE:
        raise LLVMUnsupported("LLVM id does not support tagged multi-member unions; narrow the value first", node)
    if kind != "ptr" or enum_ops.scalar_name(nullable.member(semantic) or semantic):
        raise LLVMUnsupported("LLVM id supports only reference values, not unboxed numbers or scalar enums", node)
    if nullable.member(semantic):
        return nullable.dispatch(e, semantic, kind, value, "ptr", "null",
                                 lambda member, storage, payload: pointer(e, member, storage, payload, node))
    if dom_ops.is_element(e, semantic):
        return dom_ops.pointer(e, semantic, value)
    if nullable.is_object(semantic):
        if e.module.custom_element_types:
            return dom_ops.identity_pointer(e, semantic, kind, value, node)
        return object_values.unbox_reference(e, value)
    if iterator_ops.is_iterator(semantic):
        return e.emit_value(f"call ptr @pyjs.iterator.identity(ptr {value})")
    value = callable_adapters.identity(e, semantic, value)
    return iterable_views.identity(e, semantic, value)
