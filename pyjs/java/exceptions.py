"""Managed Python exception classes for JVM control-flow lowering."""

from pyjs.decorators import is_declaration
from pyjs.python import native as native_builtins

from .classfile import Bytecode, ClassFile, Method


def exception_type(value_type):
    value = getattr(value_type, "py_obj", None)
    if isinstance(value, type) and (
        issubclass(value, native_builtins._BaseException)
        or issubclass(value, BaseException) and is_declaration(value, "jvm")
    ):
        return value
    return None


def emit_exception_class(class_files, prefix, value):
    name = f"{prefix}$exception${value.__name__.removeprefix('_')}"
    if name in class_files:
        return name
    if value is native_builtins._BaseException:
        parent = "java/lang/Throwable"
    elif value is native_builtins._Exception:
        # Java callers can catch ordinary Python errors as Exception. Python's
        # broader BaseException handler matches Throwable in the dispatcher.
        parent = "java/lang/RuntimeException"
    else:
        parent = emit_exception_class(class_files, prefix, value.__bases__[0])
    class_file = ClassFile(name, super_name=parent, access=0x0021)
    code = Bytecode()
    code.local(0x19, 0)
    code.local(0x19, 1)
    constructor = class_file.method_reference(parent, "<init>", "(Ljava/lang/String;)V")
    code.emit(0xB7, constructor.to_bytes(2, "big"))
    code.emit(0xB1)
    class_file.add_method(Method(
        0x0001, "<init>", "(Ljava/lang/String;)V", code.render(), 2, 2,
    ))
    class_files[name] = class_file
    return name
