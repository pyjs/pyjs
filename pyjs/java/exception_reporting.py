"""JVM trace presentation without changing Python exception relationships."""

from .classfile import Bytecode, ClassFile, Method
from .exceptions import SUPPRESSION_GETTER, emit_context_runtime

DIRECT_CAUSE = "The above exception was the direct cause of the following exception:"
IMPLICIT_CONTEXT = "During handling of the above exception, another exception occurred:"


def invoke(code, class_file, owner, name, descriptor, opcode=0xB6):
    reference = class_file.method_reference(owner, name, descriptor)
    code.emit(opcode, reference.to_bytes(2, "big"))


def construct(code, class_file, owner):
    code.emit(0xBB, class_file.constants.class_(owner).to_bytes(2, "big"))
    code.emit(0x59)
    invoke(code, class_file, owner, "<init>", "()V", 0xB7)


def string(code, class_file, value):
    code.emit(0x13, class_file.constants.string(value).to_bytes(2, "big"))


def emit_print_overrides(class_file, prefix):
    reporter = f"{prefix}$exception$report"
    for output in (None, "java/io/PrintStream", "java/io/PrintWriter"):
        code = Bytecode()
        if output is None:
            field = class_file.field_reference("java/lang/System", "err", "Ljava/io/PrintStream;")
            code.emit(0xB2, field.to_bytes(2, "big"))
        else:
            code.local(0x19, 1)
        code.local(0x19, 0)
        invoke(code, class_file, reporter, "format", "(Ljava/lang/Throwable;)Ljava/lang/String;", 0xB8)
        invoke(code, class_file, output or "java/io/PrintStream", "print", "(Ljava/lang/String;)V")
        code.emit(0xB1)
        descriptor = "()V" if output is None else f"(L{output};)V"
        class_file.add_method(Method(0x0001, "printStackTrace", descriptor, code.render(), 2,
                                     1 if output is None else 2))


def emit_snapshot(class_files, name):
    # A detached Throwable lets Java render frames and native suppressed errors
    # without following the original cause again or mutating the user's error.
    snapshot = ClassFile(name, super_name="java/lang/Throwable")
    code = Bytecode()
    code.local(0x19, 0)
    code.local(0x19, 1)
    invoke(code, snapshot, "java/lang/Throwable", "toString", "()Ljava/lang/String;")
    invoke(code, snapshot, "java/lang/Throwable", "<init>", "(Ljava/lang/String;)V", 0xB7)
    code.local(0x19, 0)
    code.local(0x19, 1)
    invoke(code, snapshot, "java/lang/Throwable", "getStackTrace", "()[Ljava/lang/StackTraceElement;")
    invoke(code, snapshot, "java/lang/Throwable", "setStackTrace", "([Ljava/lang/StackTraceElement;)V")
    code.local(0x19, 1)
    invoke(code, snapshot, "java/lang/Throwable", "getSuppressed", "()[Ljava/lang/Throwable;")
    code.local(0x3A, 2)
    code.emit(0x03)
    code.local(0x36, 3)
    code.mark("suppressed")
    code.local(0x15, 3)
    code.local(0x19, 2)
    code.emit(0xBE)
    code.branch(0xA2, "done")
    code.local(0x19, 0)
    code.local(0x19, 2)
    code.local(0x15, 3)
    code.emit(0x32)
    invoke(code, snapshot, "java/lang/Throwable", "addSuppressed", "(Ljava/lang/Throwable;)V")
    code.emit(0x84, bytes((3, 1)))
    code.branch(0xA7, "suppressed")
    code.mark("done")
    code.emit(0xB1)
    snapshot.add_method(Method(0x0001, "<init>", "(Ljava/lang/Throwable;)V", code.render(), 3, 4))
    code = Bytecode()
    code.local(0x19, 0)
    invoke(code, snapshot, "java/lang/Throwable", "getMessage", "()Ljava/lang/String;")
    code.emit(0xB0)
    snapshot.add_method(Method(0x0001, "toString", "()Ljava/lang/String;", code.render(), 1, 1))
    class_files[name] = snapshot


def emit_report_runtime(class_files, prefix):
    name = f"{prefix}$exception$report"
    if name in class_files:
        return name
    helper = ClassFile(name)
    class_files[name] = helper
    state = emit_context_runtime(class_files, prefix)
    snapshot = f"{name}$snapshot"
    emit_snapshot(class_files, snapshot)

    code = Bytecode()
    for index, root in enumerate(("BaseException", "Exception")):
        owner = f"{prefix}$exception${root}"
        class_index = helper.constants.class_(owner).to_bytes(2, "big")
        code.local(0x19, 0)
        code.emit(0xC1, class_index)
        code.branch(0x99, f"next{index}")
        code.local(0x19, 0)
        code.emit(0xC0, class_index)
        invoke(code, helper, owner, SUPPRESSION_GETTER, "()Z")
        code.emit(0xAC)
        code.mark(f"next{index}")
    code.emit(0x03)
    code.emit(0xAC)
    helper.add_method(Method(0x000A, "suppressed", "(Ljava/lang/Throwable;)Z", code.render(), 1, 1))

    # Locals: current, seen, errors, separators, writer, output, next, index.
    code = Bytecode()
    for slot, owner in ((1, "java/util/IdentityHashMap"), (2, "java/util/ArrayList"),
                        (3, "java/util/ArrayList"), (4, "java/io/StringWriter")):
        construct(code, helper, owner)
        code.local(0x3A, slot)
    code.emit(0xBB, helper.constants.class_("java/io/PrintWriter").to_bytes(2, "big"))
    code.emit(0x59)
    code.local(0x19, 4)
    invoke(code, helper, "java/io/PrintWriter", "<init>", "(Ljava/io/Writer;)V", 0xB7)
    code.local(0x3A, 5)
    code.mark("collect")
    code.local(0x19, 0)
    code.branch(0xC6, "render")
    code.local(0x19, 1)
    code.local(0x19, 0)
    invoke(code, helper, "java/util/IdentityHashMap", "containsKey", "(Ljava/lang/Object;)Z")
    code.branch(0x9A, "render")
    code.local(0x19, 1)
    code.local(0x19, 0)
    code.local(0x19, 0)
    invoke(code, helper, "java/util/IdentityHashMap", "put", "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;")
    code.emit(0x57)
    code.local(0x19, 2)
    code.local(0x19, 0)
    invoke(code, helper, "java/util/ArrayList", "add", "(Ljava/lang/Object;)Z")
    code.emit(0x57)
    code.local(0x19, 0)
    invoke(code, helper, "java/lang/Throwable", "getCause", "()Ljava/lang/Throwable;")
    code.local(0x3A, 6)
    code.local(0x19, 6)
    code.branch(0xC6, "context")
    code.local(0x19, 3)
    string(code, helper, "\n" + DIRECT_CAUSE + "\n\n")
    code.branch(0xA7, "record")
    code.mark("context")
    code.local(0x19, 0)
    invoke(code, helper, name, "suppressed", "(Ljava/lang/Throwable;)Z", 0xB8)
    code.branch(0x9A, "context_done")
    code.local(0x19, 0)
    invoke(code, helper, state, "context", "(Ljava/lang/Throwable;)Ljava/lang/Throwable;", 0xB8)
    code.local(0x3A, 6)
    code.mark("context_done")
    code.local(0x19, 3)
    string(code, helper, "\n" + IMPLICIT_CONTEXT + "\n\n")
    code.mark("record")
    invoke(code, helper, "java/util/ArrayList", "add", "(Ljava/lang/Object;)Z")
    code.emit(0x57)
    code.local(0x19, 6)
    code.local(0x3A, 0)
    code.branch(0xA7, "collect")
    code.mark("render")
    code.local(0x19, 2)
    invoke(code, helper, "java/util/ArrayList", "size", "()I")
    code.emit(0x04)
    code.emit(0x64)
    code.local(0x36, 7)
    code.branch(0xA7, "error")
    code.mark("separator")
    code.local(0x19, 5)
    code.local(0x19, 3)
    code.local(0x15, 7)
    invoke(code, helper, "java/util/ArrayList", "get", "(I)Ljava/lang/Object;")
    code.emit(0xC0, helper.constants.class_("java/lang/String").to_bytes(2, "big"))
    invoke(code, helper, "java/io/PrintWriter", "print", "(Ljava/lang/String;)V")
    code.mark("error")
    code.local(0x15, 7)
    code.branch(0x9B, "done")
    code.emit(0xBB, helper.constants.class_(snapshot).to_bytes(2, "big"))
    code.emit(0x59)
    code.local(0x19, 2)
    code.local(0x15, 7)
    invoke(code, helper, "java/util/ArrayList", "get", "(I)Ljava/lang/Object;")
    code.emit(0xC0, helper.constants.class_("java/lang/Throwable").to_bytes(2, "big"))
    invoke(code, helper, snapshot, "<init>", "(Ljava/lang/Throwable;)V", 0xB7)
    code.local(0x19, 5)
    invoke(code, helper, "java/lang/Throwable", "printStackTrace", "(Ljava/io/PrintWriter;)V")
    code.emit(0x84, bytes((7, 255)))
    code.local(0x15, 7)
    code.branch(0x9C, "separator")
    code.mark("done")
    code.local(0x19, 4)
    invoke(code, helper, "java/io/StringWriter", "toString", "()Ljava/lang/String;")
    code.emit(0xB0)
    helper.add_method(Method(0x0009, "format", "(Ljava/lang/Throwable;)Ljava/lang/String;",
                             code.render(), 4, 8))
    return name
