"""Managed Python exception classes for JVM control-flow lowering."""

from pyjs.analysis.objects import Class, UnionType
from pyjs.decorators import is_declaration
from pyjs.python import native as native_builtins

from .classfile import Bytecode, ClassFile, ExceptionHandler, Field, Method

MESSAGE_GETTER = "$pyjs$exception$base_text"
MESSAGE_SETTER = "$pyjs$exception$set_message"
FORMATTER = "$pyjs$exception$text"
EXPLICIT_FORMATTER = "$pyjs$exception$explicit_text"
CAUSE_SETTER = "$pyjs$exception$set_cause"
SUPPRESSION_GETTER = "$pyjs$exception$suppress_context"


def exception_type(value_type):
    value = getattr(value_type, "py_obj", None)
    if isinstance(value, type) and (
        issubclass(value, native_builtins._BaseException)
        or issubclass(value, BaseException)
    ):
        return value
    return None


def builtin_exception(value):
    if value.__module__ == "builtins":
        return getattr(native_builtins, f"_{value.__name__}", None)
    return value if value.__module__ == native_builtins.__name__ else None


def managed_exception(value_type):
    value = exception_type(value_type)
    return value is not None and not any(is_declaration(base, "jvm") for base in value.__mro__)


def nullable_exception(value_type):
    """Whether every non-None union member is an exception."""
    if not isinstance(value_type, UnionType):
        return False
    members = value_type.types
    exceptions = [member for member in members if exception_type(member) is not None]
    return bool(exceptions) and len(exceptions) < len(members) and all(
        exception_type(member) is not None
        or isinstance(member, Class) and member.generic_name in {"None", "NoneType"}
        for member in members
    )


def contained_exception_types(value_type):
    """Find exception members in a value, including typed container contents."""
    pending = [value_type]
    seen = set()
    while pending:
        value_type = pending.pop()
        if value_type in seen:
            continue
        seen.add(value_type)
        if isinstance(value_type, UnionType):
            pending.extend(value_type.types)
        elif exception_type(value_type) is not None:
            yield value_type
        elif isinstance(value_type, Class):
            pending.extend((value_type.generic_types or {}).values())


def emit_type_error(code, class_file, class_files, prefix, message):
    name = emit_exception_class(class_files, prefix, native_builtins._TypeError)
    code.emit(0xBB, class_file.constants.class_(name).to_bytes(2, "big"))
    code.emit(0x59)
    code.emit(0x13, class_file.constants.string(message).to_bytes(2, "big"))
    constructor = class_file.method_reference(name, "<init>", "(Ljava/lang/String;)V")
    code.emit(0xB7, constructor.to_bytes(2, "big"))
    code.emit(0xBF)


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
    return emit_exception_subclass(class_files, name, parent, prefix)


def strict_formatter_bridge(class_file, class_files, prefix, *, final=True):
    """Check implicit Python text without changing explicit or Java calls."""
    code = Bytecode()
    code.local(0x19, 0)
    reference = class_file.method_reference(class_file.name, EXPLICIT_FORMATTER, "()Ljava/lang/String;")
    code.emit(0xB6, reference.to_bytes(2, "big"))
    code.emit(0x59)
    code.branch(0xC7, "valid")
    code.emit(0x57)
    emit_type_error(
        code, class_file, class_files, prefix,
        "Exception __str__ must accept no arguments and return str",
    )
    code.mark("valid")
    code.emit(0xB0)
    return Method(
        0x0011 if final else 0x0001, FORMATTER, "()Ljava/lang/String;", code.render(), 3, 1,
    )


def emit_exception_subclass(class_files, name, parent, prefix):
    if name in class_files:
        return name
    class_file = ClassFile(name, super_name=parent, access=0x0021)
    class_files[name] = class_file
    code = Bytecode()
    code.local(0x19, 0)
    code.local(0x19, 1)
    constructor = class_file.method_reference(parent, "<init>", "(Ljava/lang/String;)V")
    code.emit(0xB7, constructor.to_bytes(2, "big"))
    if parent in {"java/lang/Throwable", "java/lang/RuntimeException"}:
        # A Python initializer may replace the original message. A null raw
        # message marks an unsupported original payload, not absent text:
        # field-only construction and a later scalar replacement stay valid.
        field = class_file.field_reference(name, "$pyjs$message", "Ljava/lang/String;")
        class_file.add_field(Field(0x0002, "$pyjs$message", "Ljava/lang/String;"))
        code.local(0x19, 0)
        code.local(0x19, 1)
        code.emit(0xB5, field.to_bytes(2, "big"))
        getter = Bytecode()
        getter.local(0x19, 0)
        getter.emit(0xB4, field.to_bytes(2, "big"))
        getter.emit(0x59)
        getter.branch(0xC7, "supported")
        getter.emit(0x57)
        emit_type_error(
            getter, class_file, class_files, prefix,
            "JVM default exception text requires scalar positional arguments",
        )
        getter.mark("supported")
        getter.emit(0xB0)
        class_file.add_method(Method(
            0x0011, MESSAGE_GETTER, "()Ljava/lang/String;", getter.render(), 3, 1,
        ))
        getter = Bytecode()
        getter.local(0x19, 0)
        reference = class_file.method_reference(name, MESSAGE_GETTER, "()Ljava/lang/String;")
        getter.emit(0xB6, reference.to_bytes(2, "big"))
        getter.emit(0xB0)
        class_file.add_method(Method(
            0x0001, EXPLICIT_FORMATTER, "()Ljava/lang/String;", getter.render(), 1, 1,
        ))
        class_file.add_method(strict_formatter_bridge(class_file, class_files, prefix))
        # Java loggers and uncaught handlers must not lose the original error
        # when Python formatting fails. Python calls use FORMATTER directly.
        getter = Bytecode()
        getter.local(0x19, 0)
        reference = class_file.method_reference(name, FORMATTER, "()Ljava/lang/String;")
        getter.emit(0xB6, reference.to_bytes(2, "big"))
        end = len(getter.code)
        getter.emit(0xB0)
        handler = len(getter.code)
        getter.emit(0x57)
        getter.emit(0x13, class_file.constants.string("<exception str() failed>").to_bytes(2, "big"))
        getter.emit(0xB0)
        class_file.add_method(Method(
            0x0011, "getMessage", "()Ljava/lang/String;", getter.render(), 1, 1,
            exception_handlers=(ExceptionHandler(0, end, handler, "java/lang/Throwable"),),
        ))
        setter = Bytecode()
        setter.local(0x19, 0)
        setter.local(0x19, 1)
        setter.emit(0xB5, field.to_bytes(2, "big"))
        setter.emit(0xB1)
        class_file.add_method(Method(
            0x0011, MESSAGE_SETTER, "(Ljava/lang/String;)V", setter.render(), 2, 2,
        ))
        emit_cause_state(class_file)
    code.emit(0xB1)
    class_file.add_method(Method(
        0x0001, "<init>", "(Ljava/lang/String;)V", code.render(), 2, 2,
    ))
    return name


def emit_cause_state(class_file):
    # Throwable.initCause is one-shot and rejects self-cycles. Python permits
    # both replacing a cause and self-cycles, including clearing it with None.
    cause_name = "$pyjs$cause"
    suppress_name = "$pyjs$suppress_context"
    class_file.add_field(Field(0x0002, cause_name, "Ljava/lang/Throwable;"))
    class_file.add_field(Field(0x0002, suppress_name, "Z"))
    cause = class_file.field_reference(class_file.name, cause_name, "Ljava/lang/Throwable;")
    suppress = class_file.field_reference(class_file.name, suppress_name, "Z")
    for method, field, descriptor, opcode in (
        ("getCause", cause, "Ljava/lang/Throwable;", 0xB0),
        (SUPPRESSION_GETTER, suppress, "Z", 0xAC),
    ):
        getter = Bytecode()
        getter.local(0x19, 0)
        getter.emit(0xB4, field.to_bytes(2, "big"))
        getter.emit(opcode)
        class_file.add_method(Method(
            0x0011, method, f"(){descriptor}", getter.render(), 1, 1,
        ))
    setter = Bytecode()
    setter.local(0x19, 0)
    setter.local(0x19, 1)
    setter.emit(0xB5, cause.to_bytes(2, "big"))
    setter.local(0x19, 0)
    setter.emit(0x04)
    setter.emit(0xB5, suppress.to_bytes(2, "big"))
    setter.emit(0xB1)
    class_file.add_method(Method(
        0x0011, CAUSE_SETTER, "(Ljava/lang/Throwable;)V", setter.render(), 2, 2,
    ))
