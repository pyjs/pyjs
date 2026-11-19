"""Value equality over the live prefix of specialized scalar lists."""

from pyjs.analysis.analyzer import analyzed_value_type
from pyjs.analysis.objects import Class

from .classfile import Bytecode, Method
from .diagnostics import JVMUnsupported


def call(emitter, node, target, value_type):
    if node.keywords or len(node.args) != 1:
        raise JVMUnsupported("JVM list equality requires one positional list", node)
    other = analyzed_value_type(node.args[0])
    item_type = emitter.list_item_type(value_type)
    if (item_type not in {"J", "Z", "Ljava/lang/String;"}
            or not isinstance(other, Class) or other.generic_name != "list"
            or emitter.list_item_type(other) != item_type):
        raise JVMUnsupported(
            "JVM list equality requires matching integer, boolean or string item storage", node)
    owner = emitter.list_class(value_type)
    descriptor = f"(L{owner.name};)Z"
    if not any(method.name == "same_items" for method in owner.methods):
        owner.add_method(equality_method(emitter, owner, item_type, descriptor))
    emitter.expression(node.args[0], expected=f"L{owner.name};")
    reference = emitter.class_file.method_reference(owner.name, "same_items", descriptor)
    emitter.code.emit(0xB6, reference.to_bytes(2, "big"))
    if target.name == "__ne__":
        emitter.code.emit(0x04)
        emitter.code.emit(0x82)
    return "Z"


def equality_method(emitter, owner, item_type, descriptor):
    code = Bytecode()
    length = owner.field_reference(owner.name, "length", "I")
    data = owner.field_reference(owner.name, "data", f"[{item_type}")
    for slot in (0, 1):
        code.local(0x19, slot)
        code.emit(0xB4, length.to_bytes(2, "big"))
    code.branch(0xA0, "different")
    code.emit(0x03)
    code.local(0x36, 2)
    code.mark("loop")
    code.local(0x15, 2)
    code.local(0x19, 0)
    code.emit(0xB4, length.to_bytes(2, "big"))
    code.branch(0xA2, "equal")
    for slot in (0, 1):
        code.local(0x19, slot)
        code.emit(0xB4, data.to_bytes(2, "big"))
        code.local(0x15, 2)
        code.emit(emitter.array_load_opcode(item_type))
    if item_type == "Ljava/lang/String;":
        equals = owner.method_reference(
            "java/util/Objects", "equals", "(Ljava/lang/Object;Ljava/lang/Object;)Z")
        code.emit(0xB8, equals.to_bytes(2, "big"))
        code.branch(0x99, "different")
    elif item_type == "J":
        code.emit(0x94)
        code.branch(0x9A, "different")
    else:
        code.branch(0xA0, "different")
    code.emit(0x84, bytes((2, 1)))
    code.branch(0xA7, "loop")
    code.mark("different")
    code.emit(0x03)
    code.emit(0xAC)
    code.mark("equal")
    code.emit(0x04)
    code.emit(0xAC)
    return Method(0x0001, "same_items", descriptor, code.render(), 4, 3)
