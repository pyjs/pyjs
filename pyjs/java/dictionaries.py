"""Small runtime bridges for insertion-ordered JVM dictionaries."""

from .classfile import Bytecode, ExceptionHandler, Method


def emit_iterator_next(owner, throw_python):
    name = "$dictionaryNext"
    descriptor = "(Ljava/util/Iterator;)Ljava/lang/Object;"
    if not any(method.name == name for method in owner.methods):
        code = Bytecode()
        code.local(0x19, 0)
        reference = owner.interface_method_reference(
            "java/util/Iterator", "next", "()Ljava/lang/Object;",
        )
        code.emit(0xB9, reference.to_bytes(2, "big") + b"\x01\x00")
        code.emit(0xB0)
        end = len(code.code)
        code.emit(0x57)
        throw_python("RuntimeError", "dictionary keys changed during iteration", code, owner)
        owner.add_method(Method(
            0x0009, name, descriptor, code.render(), 8, 1,
            exception_handlers=(ExceptionHandler(
                0, end, end, "java/util/ConcurrentModificationException",
            ),),
        ))
    return name, descriptor
