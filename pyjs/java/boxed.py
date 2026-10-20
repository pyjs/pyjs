"""Primitive payloads stored through Python object views."""

from .classfile import Bytecode, Method


def box(code, class_file, descriptor):
    if descriptor in {"B", "C", "S", "I"}:
        code.emit(0x85)
        descriptor = "J"
    elif descriptor == "F":
        code.emit(0x8D)
        descriptor = "D"
    owner = {"J": "java/lang/Long", "Z": "java/lang/Boolean",
             "D": "java/lang/Double"}.get(descriptor)
    if owner is not None:
        reference = class_file.method_reference(owner, "valueOf", f"({descriptor})L{owner};")
        code.emit(0xB8, reference.to_bytes(2, "big"))
        return f"L{owner};"
    return descriptor


def emit_key_guard(owner, throw_python):
    name = "$pyjs$object$dictionary_key"
    descriptor = "(Ljava/lang/Object;)Ljava/lang/Object;"
    if not any(method.name == name for method in owner.methods):
        code = Bytecode()
        # HashMap cannot use Python's cross-kind numeric equality or structural
        # array hashing. Preserve identity keys without claiming those domains.
        for index, kind in enumerate((
            "java/lang/Number", "java/lang/Boolean", "[Ljava/lang/Object;",
        )):
            code.local(0x19, 0)
            code.emit(0xC1, owner.constants.class_(kind).to_bytes(2, "big"))
            code.branch(0x99, f"next{index}")
            throw_python(
                "TypeError", "JVM erased numeric and reference-array dictionary keys are not implemented",
                code, owner,
            )
            code.mark(f"next{index}")
        code.local(0x19, 0)
        code.emit(0xB0)
        owner.add_method(Method(0x0009, name, descriptor, code.render(), 3, 1))
    return name, descriptor


def emit_equality(owner, throw_python):
    name = "$pyjs$object$equals"
    descriptor = "(Ljava/lang/Object;Ljava/lang/Object;)Z"
    if any(method.name == name for method in owner.methods):
        return name, descriptor
    code = Bytecode()
    for slot in (0, 1):
        code.local(0x19, slot)
        array = owner.constants.class_("[Ljava/lang/Object;")
        code.emit(0xC1, array.to_bytes(2, "big"))
        code.branch(0x99, f"scalar{slot}")
        throw_python("TypeError", "JVM reference-array equality is not implemented", code, owner)
        code.mark(f"scalar{slot}")
        code.local(0x19, slot)
        boolean = owner.constants.class_("java/lang/Boolean")
        code.emit(0xC1, boolean.to_bytes(2, "big"))
        code.branch(0x99, f"next{slot}")
        code.local(0x19, slot)
        code.emit(0xC0, boolean.to_bytes(2, "big"))
        reference = owner.method_reference("java/lang/Boolean", "booleanValue", "()Z")
        code.emit(0xB6, reference.to_bytes(2, "big"))
        code.emit(0x85)
        box(code, owner, "J")
        code.local(0x3A, slot)
        code.mark(f"next{slot}")

    def instance(slot, kind):
        code.local(0x19, slot)
        code.emit(0xC1, owner.constants.class_(f"java/lang/{kind}").to_bytes(2, "big"))

    def unbox(slot, kind, method, result):
        code.local(0x19, slot)
        code.emit(0xC0, owner.constants.class_(f"java/lang/{kind}").to_bytes(2, "big"))
        reference = owner.method_reference(f"java/lang/{kind}", method, f"(){result}")
        code.emit(0xB6, reference.to_bytes(2, "big"))

    instance(0, "Double")
    code.branch(0x99, "integer_left")
    instance(1, "Double")
    code.branch(0x99, "floating_left")
    unbox(0, "Double", "doubleValue", "D")
    unbox(1, "Double", "doubleValue", "D")
    code.emit(0x97)
    code.branch(0x9A, "different")
    code.emit(0x04)
    code.emit(0xAC)
    code.mark("floating_left")
    instance(1, "Long")
    code.branch(0x99, "objects")
    unbox(1, "Long", "longValue", "J")
    unbox(0, "Double", "doubleValue", "D")
    code.branch(0xA7, "mixed")
    code.mark("integer_left")
    instance(0, "Long")
    code.branch(0x99, "objects")
    instance(1, "Double")
    code.branch(0x99, "objects")
    unbox(0, "Long", "longValue", "J")
    unbox(1, "Double", "doubleValue", "D")
    code.mark("mixed")
    mixed = "$pyjs$object$integer_float_equals"
    reference = owner.method_reference(owner.name, mixed, "(JD)Z")
    code.emit(0xB8, reference.to_bytes(2, "big"))
    code.emit(0xAC)
    code.mark("different")
    code.emit(0x03)
    code.emit(0xAC)
    code.mark("objects")
    code.local(0x19, 0)
    code.local(0x19, 1)
    reference = owner.method_reference("java/util/Objects", "equals", descriptor)
    code.emit(0xB8, reference.to_bytes(2, "big"))
    code.emit(0xAC)
    owner.add_method(Method(0x0009, name, descriptor, code.render(), 4, 2))

    code = Bytecode()
    # Converting both operands to double loses integer bits above 2**53.
    # Check range before d2l (which saturates), then require both exact views.
    for boundary, comparison, branch in ((-2**63, 0x98, 0x9B), (2**63, 0x97, 0x9C)):
        code.local(0x18, 2)
        code.emit(0x14, owner.constants.double(float(boundary)).to_bytes(2, "big"))
        code.emit(comparison)
        code.branch(branch, "different")
    code.local(0x18, 2)
    code.emit(0x8F)
    code.local(0x16, 0)
    code.emit(0x94)
    code.branch(0x9A, "different")
    code.local(0x16, 0)
    code.emit(0x8A)
    code.local(0x18, 2)
    code.emit(0x97)
    code.branch(0x9A, "different")
    code.emit(0x04)
    code.emit(0xAC)
    code.mark("different")
    code.emit(0x03)
    code.emit(0xAC)
    owner.add_method(Method(0x0009, mixed, "(JD)Z", code.render(), 4, 4))
    return name, descriptor
