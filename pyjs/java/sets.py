"""Reference-valued sets backed by Java's standard hash table."""
from .diagnostics import JVMUnsupported

DESCRIPTOR = "Ljava/util/Set;"


def item_type(emitter, value_type, node=None):
    item = value_type.generic_types["V"]
    emitter.validate_java_object_semantics(item, node, dictionary_key=True)
    descriptor = emitter.value_type(item)
    if not descriptor.startswith("L") or descriptor in {
            "Ljava/lang/Long;", "Ljava/lang/Double;", "Ljava/lang/Boolean;"}:
        raise JVMUnsupported("JVM sets currently require reference items with Java-compatible equality", node)
    return descriptor


def invoke(emitter, name, descriptor, slots=1):
    reference = emitter.class_file.interface_method_reference("java/util/Set", name, descriptor)
    emitter.code.emit(0xB9, reference.to_bytes(2, "big") + bytes((slots, 0)))


def construct(emitter, value_type, elements=()):
    item = item_type(emitter, value_type)
    owner = "java/util/LinkedHashSet"
    emitter.code.emit(0xBB, emitter.class_file.constants.class_(owner).to_bytes(2, "big"))
    emitter.code.emit(0x59)
    constructor = emitter.class_file.method_reference(owner, "<init>", "()V")
    emitter.code.emit(0xB7, constructor.to_bytes(2, "big"))
    for element in elements:
        emitter.code.emit(0x59)
        actual = emitter.expression(element, expected=item)
        emitter.convert_native_argument(actual, item, element)
        emitter.dictionary_key_guard(item)
        invoke(emitter, "add", "(Ljava/lang/Object;)Z", 2)
        emitter.code.emit(0x57)
    return DESCRIPTOR


def call(emitter, node, target, value_type, leading=None):
    item = item_type(emitter, value_type, node)
    if node.keywords:
        raise JVMUnsupported("JVM set methods require positional arguments", node)
    if target.name in {"__len__", "__bool__", "clear", "copy"} and not node.args:
        if target.name == "copy":
            saved = emitter.allocate_temporary(DESCRIPTOR, "set.copy.source")
            emitter.store(saved, DESCRIPTOR)
            owner = "java/util/LinkedHashSet"
            emitter.code.emit(0xBB, emitter.class_file.constants.class_(owner).to_bytes(2, "big"))
            emitter.code.emit(0x59)
            emitter.load(saved)
            constructor = emitter.class_file.method_reference(owner, "<init>", "(Ljava/util/Collection;)V")
            emitter.code.emit(0xB7, constructor.to_bytes(2, "big"))
            return DESCRIPTOR
        if target.name == "clear":
            invoke(emitter, "clear", "()V")
            return "V"
        invoke(emitter, "size", "()I")
        if target.name == "__len__":
            emitter.code.emit(0x85)
            return "J"
        emitter.comparison(0x9A)
        return "Z"
    if target.name in {"add", "discard", "__contains__"} and len(node.args) == 1:
        actual = emitter.load(leading) if leading is not None else emitter.expression(node.args[0], expected=item)
        actual = emitter.refine_reference(node.args[0], actual, item)
        if not emitter.compatible(actual, item):
            raise JVMUnsupported("JVM set item has an incompatible type", node)
        emitter.convert_native_argument(actual, item, node.args[0])
        emitter.dictionary_key_guard(item)
        method = {"add": "add", "discard": "remove", "__contains__": "contains"}[target.name]
        invoke(emitter, method, "(Ljava/lang/Object;)Z", 2)
        if target.name == "__contains__":
            return "Z"
        emitter.code.emit(0x57)
        return "V"
    raise JVMUnsupported(f"JVM set operation {target.name} is not implemented", node)
