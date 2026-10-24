"""Demand-driven JVM helpers for Python string semantics."""

from functools import partial

from .classfile import Bytecode, ClassFile, ExceptionHandler, Method


def emit_string_helpers(class_file: ClassFile, required: set[str], throw_python) -> None:
    required = required | ({"length"} if "getitem" in required else set())
    if "repr" in required:
        required = required | {"printable"}
    if required & {"contains", "startswith", "endswith", "replace"}:
        required = required | {"boundary"}
    for name, factory in (
        ("length", string_length_method),
        ("getitem", partial(string_getitem_method, throw_python=throw_python)),
        ("repeat", partial(string_repeat_method, throw_python=throw_python)),
        ("strip", string_strip_method),
        ("int", partial(string_int_method, throw_python=throw_python)),
        ("printable", string_printable_method),
        ("repr", string_repr_method),
        ("boundary", string_boundary_method),
        ("contains", string_contains_method),
        ("startswith", partial(string_affix_method, suffix=False)),
        ("endswith", partial(string_affix_method, suffix=True)),
        ("replace", string_replace_method),
        ("ord", partial(string_ord_method, throw_python=throw_python)),
        ("chr", partial(string_chr_method, throw_python=throw_python)),
        ("hex", string_hex_method),
        ("slice", string_slice_method),
        ("compare", string_compare_method),
    ):
        if name in required:
            class_file.add_method(factory(class_file))


def string_compare_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    def call(owner, name, descriptor, opcode=0xB6):
        code.emit(opcode, class_file.method_reference(owner, name, descriptor).to_bytes(2, "big"))
    for slot in (2, 3):
        code.emit(0x03)
        code.local(0x36, slot)
    code.mark("compare.next")
    for receiver, offset in ((0, 2), (1, 3)):
        code.local(0x15, offset)
        code.local(0x19, receiver)
        call("java/lang/String", "length", "()I")
        code.branch(0xA2, "compare.end")
        code.local(0x19, receiver)
        code.local(0x15, offset)
        call("java/lang/String", "codePointAt", "(I)I")
        code.local(0x36, offset + 2)
    code.local(0x15, 4)
    code.local(0x15, 5)
    code.branch(0xA0, "compare.different")
    for offset in (2, 3):
        code.local(0x15, offset)
        code.local(0x15, offset + 2)
        call("java/lang/Character", "charCount", "(I)I", 0xB8)
        code.emit(0x60)
        code.local(0x36, offset)
    code.branch(0xA7, "compare.next")
    code.mark("compare.different")
    code.local(0x15, 4)
    code.local(0x15, 5)
    code.emit(0x64)
    code.emit(0xAC)
    code.mark("compare.end")
    for receiver, offset in ((0, 2), (1, 3)):
        code.local(0x19, receiver)
        call("java/lang/String", "length", "()I")
        code.local(0x15, offset)
        code.emit(0x64)
    code.emit(0x64)
    code.emit(0xAC)
    return Method(
        0x0009, "pyjs_string_compare", "(Ljava/lang/String;Ljava/lang/String;)I",
        code.render(), 3, 6,
    )


def string_slice_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    def call(name, descriptor):
        code.emit(0xB6, class_file.method_reference("java/lang/String", name, descriptor).to_bytes(2, "big"))
    code.local(0x19, 0)
    code.emit(0x03)
    code.local(0x19, 0)
    call("length", "()I")
    call("codePointCount", "(II)I")
    code.emit(0x85)
    code.local(0x37, 5)
    for slot in (1, 3):
        code.local(0x16, slot)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9C, f"slice.{slot}.upper")
        code.local(0x16, slot)
        code.local(0x16, 5)
        code.emit(0x61)
        code.local(0x37, slot)
        code.local(0x16, slot)
        code.emit(0x09)
        code.emit(0x94)
        code.branch(0x9C, f"slice.{slot}.upper")
        code.emit(0x09)
        code.local(0x37, slot)
        code.mark(f"slice.{slot}.upper")
        code.local(0x16, slot)
        code.local(0x16, 5)
        code.emit(0x94)
        code.branch(0x9E, f"slice.{slot}.done")
        code.local(0x16, 5)
        code.local(0x37, slot)
        code.mark(f"slice.{slot}.done")
    code.local(0x16, 1)
    code.local(0x16, 3)
    code.emit(0x94)
    code.branch(0x9E, "slice.substring")
    code.local(0x16, 1)
    code.local(0x37, 3)
    code.mark("slice.substring")
    code.local(0x19, 0)
    for slot in (1, 3):
        code.local(0x19, 0)
        code.emit(0x03)
        code.local(0x16, slot)
        code.emit(0x88)
        call("offsetByCodePoints", "(II)I")
    call("substring", "(II)Ljava/lang/String;")
    code.emit(0xB0)
    return Method(
        0x0009, "pyjs_string_slice", "(Ljava/lang/String;JJ)Ljava/lang/String;",
        code.render(), 6, 7,
    )


def string_ord_method(class_file: ClassFile, *, throw_python) -> Method:
    code = Bytecode()
    def call(owner, name, descriptor):
        code.emit(0xB6, class_file.method_reference(owner, name, descriptor).to_bytes(2, "big"))
    code.local(0x19, 0)
    code.emit(0x03)
    code.local(0x19, 0)
    call("java/lang/String", "length", "()I")
    call("java/lang/String", "codePointCount", "(II)I")
    code.emit(0x04)
    code.branch(0x9F, "ord.valid")
    throw_python("TypeError", "ord() expected a character", code, class_file)
    code.mark("ord.valid")
    code.local(0x19, 0)
    code.emit(0x03)
    call("java/lang/String", "codePointAt", "(I)I")
    code.emit(0x85)
    code.emit(0xAD)
    return Method(0x0009, "pyjs_string_ord", "(Ljava/lang/String;)J", code.render(), 4, 1)


def string_chr_method(class_file: ClassFile, *, throw_python) -> Method:
    code = Bytecode()
    def bound(value, opcode, label):
        code.local(0x16, 0)
        code.emit(0x14, class_file.constants.long(value).to_bytes(2, "big"))
        code.emit(0x94)
        code.branch(opcode, label)
    bound(0, 0x9B, "chr.range")
    bound(1114111, 0x9D, "chr.range")
    code.emit(0xBB, class_file.constants.class_("java/lang/String").to_bytes(2, "big"))
    code.emit(0x59)
    code.local(0x16, 0)
    code.emit(0x88)
    reference = class_file.method_reference("java/lang/Character", "toChars", "(I)[C")
    code.emit(0xB8, reference.to_bytes(2, "big"))
    reference = class_file.method_reference("java/lang/String", "<init>", "([C)V")
    code.emit(0xB7, reference.to_bytes(2, "big"))
    code.emit(0xB0)
    code.mark("chr.range")
    throw_python("ValueError", "chr() arg not in range(0x110000)", code, class_file)
    return Method(
        0x0009, "pyjs_string_chr", "(J)Ljava/lang/String;", code.render(), 4, 2,
    )


def string_hex_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    def call(owner, name, descriptor, opcode=0xB6):
        code.emit(opcode, class_file.method_reference(owner, name, descriptor).to_bytes(2, "big"))
    def text(value):
        code.emit(0x13, class_file.constants.string(value).to_bytes(2, "big"))
    code.local(0x16, 0)
    code.emit(0x10, bytes([16]))
    call("java/lang/Long", "toString", "(JI)Ljava/lang/String;", 0xB8)
    code.local(0x3A, 2)
    code.local(0x16, 0)
    code.emit(0x09)
    code.emit(0x94)
    code.branch(0x9C, "hex.positive")
    text("-0x")
    code.local(0x19, 2)
    code.emit(0x04)
    call("java/lang/String", "substring", "(I)Ljava/lang/String;")
    code.branch(0xA7, "hex.concat")
    code.mark("hex.positive")
    text("0x")
    code.local(0x19, 2)
    code.mark("hex.concat")
    call("java/lang/String", "concat", "(Ljava/lang/String;)Ljava/lang/String;")
    code.emit(0xB0)
    return Method(0x0009, "pyjs_string_hex", "(J)Ljava/lang/String;", code.render(), 4, 3)


def string_replace_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    def call(owner, name, descriptor, opcode=0xB6):
        code.emit(opcode, class_file.method_reference(owner, name, descriptor).to_bytes(2, "big"))
    def append():
        call("java/lang/StringBuilder", "append", "(Ljava/lang/String;)Ljava/lang/StringBuilder;")
        code.emit(0x57)
    # UTF-16 cursors advance only at code-point boundaries. In particular an
    # empty pattern inserts around characters, not inside surrogate pairs.
    builder = class_file.constants.class_("java/lang/StringBuilder")
    code.emit(0xBB, builder.to_bytes(2, "big"))
    code.emit(0x59)
    call("java/lang/StringBuilder", "<init>", "()V", 0xB7)
    code.local(0x3A, 5)
    for slot in (6, 7):
        code.emit(0x03)
        code.local(0x36, slot)
    for source, slot in ((0, 8), (1, 9)):
        code.local(0x19, source)
        call("java/lang/String", "length", "()I")
        code.local(0x36, slot)
    code.local(0x16, 3)
    code.emit(0x09)
    code.emit(0x94)
    code.branch(0x9C, "replace.loop")
    code.emit(0x14, class_file.constants.long(9223372036854775807).to_bytes(2, "big"))
    code.local(0x37, 3)
    code.mark("replace.loop")
    code.local(0x16, 3)
    code.emit(0x09)
    code.emit(0x94)
    code.branch(0x99, "replace.done")
    code.local(0x19, 0)
    code.local(0x19, 1)
    code.local(0x15, 6)
    call("java/lang/String", "startsWith", "(Ljava/lang/String;I)Z")
    code.branch(0x99, "replace.advance")
    code.local(0x19, 0)
    code.local(0x15, 6)
    code.local(0x15, 9)
    code.emit(0x60)
    call(class_file.name, "pyjs_string_boundary", "(Ljava/lang/String;I)Z", 0xB8)
    code.branch(0x99, "replace.advance")
    code.local(0x19, 5)
    code.local(0x19, 0)
    code.local(0x15, 7)
    code.local(0x15, 6)
    call("java/lang/String", "substring", "(II)Ljava/lang/String;")
    append()
    code.local(0x19, 5)
    code.local(0x19, 2)
    append()
    code.local(0x15, 6)
    code.local(0x15, 9)
    code.emit(0x60)
    code.local(0x36, 7)
    code.local(0x16, 3)
    code.emit(0x0A)
    code.emit(0x65)
    code.local(0x37, 3)
    code.local(0x15, 9)
    code.branch(0x99, "replace.advance")
    code.local(0x15, 7)
    code.local(0x36, 6)
    code.branch(0xA7, "replace.loop")
    code.mark("replace.advance")
    code.local(0x15, 6)
    code.local(0x15, 8)
    code.branch(0x9F, "replace.done")
    code.local(0x19, 0)
    code.local(0x15, 6)
    code.emit(0x04)
    call("java/lang/String", "offsetByCodePoints", "(II)I")
    code.local(0x36, 6)
    code.branch(0xA7, "replace.loop")
    code.mark("replace.done")
    code.local(0x19, 5)
    code.local(0x19, 0)
    code.local(0x15, 7)
    call("java/lang/String", "substring", "(I)Ljava/lang/String;")
    append()
    code.local(0x19, 5)
    call("java/lang/StringBuilder", "toString", "()Ljava/lang/String;")
    code.emit(0xB0)
    return Method(
        0x0009, "pyjs_string_replace",
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;J)Ljava/lang/String;",
        code.render(), 6, 10,
    )


def string_printable_method(class_file: ClassFile) -> Method:
    # Share the pinned Unicode data with LLVM, not the host JDK's version.
    from pyjs.native.unicode_data import PRINTABLE_RANGES

    code = Bytecode()

    def emit_ranges(start, stop):
        if start == stop:
            code.branch(0xA7, "printable.false")
            return
        middle = (start + stop) // 2
        lower, upper = PRINTABLE_RANGES[middle]
        code.local(0x15, 0)
        code.emit(0x13, class_file.constants.integer(lower).to_bytes(2, "big"))
        code.branch(0xA1, f"printable.left.{middle}")
        code.local(0x15, 0)
        code.emit(0x13, class_file.constants.integer(upper).to_bytes(2, "big"))
        code.branch(0xA4, "printable.true")
        emit_ranges(middle + 1, stop)
        code.mark(f"printable.left.{middle}")
        emit_ranges(start, middle)

    # A balanced decision tree avoids allocating a runtime range table.
    emit_ranges(0, len(PRINTABLE_RANGES))
    code.mark("printable.false")
    code.emit(0x03)
    code.emit(0xAC)
    code.mark("printable.true")
    code.emit(0x04)
    code.emit(0xAC)
    return Method(0x0009, "pyjs_string_printable", "(I)Z", code.render(), 2, 1)


def string_repr_method(class_file: ClassFile) -> Method:
    code = Bytecode()

    def call(owner, name, descriptor, opcode=0xB6):
        reference = class_file.method_reference(owner, name, descriptor)
        code.emit(opcode, reference.to_bytes(2, "big"))

    def integer(value):
        code.emit(0x13, class_file.constants.integer(value).to_bytes(2, "big"))

    def append(text):
        code.local(0x19, 1)
        code.emit(0x13, class_file.constants.string(text).to_bytes(2, "big"))
        call("java/lang/StringBuilder", "append", "(Ljava/lang/String;)Ljava/lang/StringBuilder;")
        code.emit(0x57)

    code.local(0x19, 0)
    code.branch(0xC7, "repr.string")
    code.emit(0x13, class_file.constants.string("None").to_bytes(2, "big"))
    code.emit(0xB0)
    code.mark("repr.string")
    # Locals: source, builder, delimiter, UTF-16 index, code point, hex,
    # padding. Iterate code points so astral characters stay intact.
    builder = class_file.constants.class_("java/lang/StringBuilder")
    code.emit(0xBB, builder.to_bytes(2, "big"))
    code.emit(0x59)
    call("java/lang/StringBuilder", "<init>", "()V", 0xB7)
    code.local(0x3A, 1)
    integer(ord("'"))
    code.local(0x36, 2)
    code.local(0x19, 0)
    integer(ord("'"))
    call("java/lang/String", "indexOf", "(I)I")
    code.branch(0x9B, "repr.open")
    code.local(0x19, 0)
    integer(ord('"'))
    call("java/lang/String", "indexOf", "(I)I")
    code.branch(0x9C, "repr.open")
    integer(ord('"'))
    code.local(0x36, 2)
    code.mark("repr.open")
    code.local(0x19, 1)
    code.local(0x15, 2)
    call("java/lang/StringBuilder", "appendCodePoint", "(I)Ljava/lang/StringBuilder;")
    code.emit(0x57)
    integer(0)
    code.local(0x36, 3)
    code.mark("repr.loop")
    code.local(0x15, 3)
    code.local(0x19, 0)
    call("java/lang/String", "length", "()I")
    code.branch(0xA2, "repr.done")
    code.local(0x19, 0)
    code.local(0x15, 3)
    call("java/lang/String", "codePointAt", "(I)I")
    code.local(0x36, 4)
    code.local(0x15, 4)
    code.local(0x15, 2)
    code.branch(0x9F, "repr.slash")
    code.local(0x15, 4)
    integer(ord("\\"))
    code.branch(0x9F, "repr.slash")
    for point, text in ((9, "\\t"), (10, "\\n"), (13, "\\r")):
        code.local(0x15, 4)
        integer(point)
        code.branch(0xA0, f"repr.not.{point}")
        append(text)
        code.branch(0xA7, "repr.next")
        code.mark(f"repr.not.{point}")
    code.local(0x15, 4)
    call(class_file.name, "pyjs_string_printable", "(I)Z", 0xB8)
    code.branch(0x99, "repr.hex")
    code.branch(0xA7, "repr.print")
    code.mark("repr.slash")
    append("\\")
    code.mark("repr.print")
    code.local(0x19, 1)
    code.local(0x15, 4)
    call("java/lang/StringBuilder", "appendCodePoint", "(I)Ljava/lang/StringBuilder;")
    code.emit(0x57)
    code.branch(0xA7, "repr.next")
    code.mark("repr.hex")
    code.local(0x15, 4)
    call("java/lang/Integer", "toHexString", "(I)Ljava/lang/String;", 0xB8)
    code.local(0x3A, 5)
    for limit, prefix, width in ((256, "\\x", 2), (65536, "\\u", 4)):
        code.local(0x15, 4)
        integer(limit)
        code.branch(0xA2, f"repr.wider.{width}")
        append(prefix)
        integer(width)
        code.branch(0xA7, "repr.pad.start")
        code.mark(f"repr.wider.{width}")
    append("\\U")
    integer(8)
    code.mark("repr.pad.start")
    code.local(0x19, 5)
    call("java/lang/String", "length", "()I")
    code.emit(0x64)
    code.local(0x36, 6)
    code.mark("repr.pad")
    code.local(0x15, 6)
    code.branch(0x9E, "repr.hex.append")
    append("0")
    code.emit(0x84, bytes((6, 255)))
    code.branch(0xA7, "repr.pad")
    code.mark("repr.hex.append")
    code.local(0x19, 1)
    code.local(0x19, 5)
    call("java/lang/StringBuilder", "append", "(Ljava/lang/String;)Ljava/lang/StringBuilder;")
    code.emit(0x57)
    code.mark("repr.next")
    code.local(0x15, 3)
    code.local(0x15, 4)
    call("java/lang/Character", "charCount", "(I)I", 0xB8)
    code.emit(0x60)
    code.local(0x36, 3)
    code.branch(0xA7, "repr.loop")
    code.mark("repr.done")
    code.local(0x19, 1)
    code.local(0x15, 2)
    call("java/lang/StringBuilder", "appendCodePoint", "(I)Ljava/lang/StringBuilder;")
    call("java/lang/StringBuilder", "toString", "()Ljava/lang/String;")
    code.emit(0xB0)
    return Method(0x0009, "pyjs_string_repr", "(Ljava/lang/String;)Ljava/lang/String;", code.render(), 3, 7)


def string_length_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    code.local(0x19, 0)
    code.emit(0x03)
    code.local(0x19, 0)
    length = class_file.method_reference(
        "java/lang/String",
        "length",
        "()I",
    )
    code.emit(0xB6, length.to_bytes(2, "big"))
    count = class_file.method_reference(
        "java/lang/String",
        "codePointCount",
        "(II)I",
    )
    code.emit(0xB6, count.to_bytes(2, "big"))
    code.emit(0x85)
    code.emit(0xAD)
    return Method(
        0x0009,
        "pyjs_string_length",
        "(Ljava/lang/String;)J",
        code.render(),
        3,
        1,
    )


def string_getitem_method(class_file: ClassFile, *, throw_python) -> Method:
    code = Bytecode()
    positive = "string.index.positive"
    valid = "string.index.valid"
    invalid = "string.index.invalid"
    code.local(0x19, 0)
    length = class_file.method_reference(
        class_file.name,
        "pyjs_string_length",
        "(Ljava/lang/String;)J",
    )
    code.emit(0xB8, length.to_bytes(2, "big"))
    code.emit(0x88)
    code.local(0x36, 3)
    code.local(0x16, 1)
    code.emit(0x09)
    code.emit(0x94)
    code.branch(0x9C, positive)
    code.local(0x16, 1)
    code.local(0x15, 3)
    code.emit(0x85)
    code.emit(0x61)
    code.local(0x37, 1)
    code.mark(positive)
    code.local(0x16, 1)
    code.emit(0x09)
    code.emit(0x94)
    code.branch(0x9B, invalid)
    code.local(0x16, 1)
    code.local(0x15, 3)
    code.emit(0x85)
    code.emit(0x94)
    code.branch(0x9B, valid)
    code.mark(invalid)
    throw_python("IndexError", "string index out of range", code, class_file)
    code.mark(valid)
    code.local(0x19, 0)
    code.emit(0x03)
    code.local(0x16, 1)
    code.emit(0x88)
    offset = class_file.method_reference(
        "java/lang/String",
        "offsetByCodePoints",
        "(II)I",
    )
    code.emit(0xB6, offset.to_bytes(2, "big"))
    code.local(0x36, 4)
    code.local(0x19, 0)
    code.local(0x15, 4)
    code.local(0x19, 0)
    code.local(0x15, 4)
    code.emit(0x04)
    code.emit(0xB6, offset.to_bytes(2, "big"))
    substring = class_file.method_reference(
        "java/lang/String",
        "substring",
        "(II)Ljava/lang/String;",
    )
    code.emit(0xB6, substring.to_bytes(2, "big"))
    code.emit(0xB0)
    return Method(
        0x0009,
        "pyjs_string_getitem",
        "(Ljava/lang/String;J)Ljava/lang/String;",
        code.render(),
        6,
        5,
    )


def string_strip_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    # Python's whitespace differs from Java's. All members are in the BMP,
    # so scanning UTF-16 units cannot split a retained surrogate pair.
    whitespace = class_file.constants.string(
        "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680"
        "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
        "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
    )
    length = class_file.method_reference("java/lang/String", "length", "()I")
    character = class_file.method_reference("java/lang/String", "charAt", "(I)C")
    contains = class_file.method_reference("java/lang/String", "indexOf", "(I)I")
    substring = class_file.method_reference(
        "java/lang/String", "substring", "(II)Ljava/lang/String;",
    )
    code.emit(0x03)
    code.local(0x36, 2)
    code.local(0x19, 0)
    code.emit(0xB6, length.to_bytes(2, "big"))
    code.local(0x36, 3)
    for left, index in ((True, 2), (False, 3)):
        check = "strip.left" if left else "strip.right"
        done = check + ".done"
        if left:
            code.local(0x15, 1)
            code.branch(0x99, done)
        code.mark(check)
        code.local(0x15, 3)
        code.local(0x15, 2)
        code.branch(0xA4, done)
        code.emit(0x13, whitespace.to_bytes(2, "big"))
        code.local(0x19, 0)
        code.local(0x15, index)
        if not left:
            code.emit(0x04)
            code.emit(0x64)
        code.emit(0xB6, character.to_bytes(2, "big"))
        code.emit(0xB6, contains.to_bytes(2, "big"))
        code.branch(0x9B, done)
        code.emit(0x84, bytes((index, 1 if left else 255)))
        code.branch(0xA7, check)
        code.mark(done)
    code.local(0x19, 0)
    code.local(0x15, 2)
    code.local(0x15, 3)
    code.emit(0xB6, substring.to_bytes(2, "big"))
    code.emit(0xB0)
    return Method(
        0x0009, "pyjs_string_strip", "(Ljava/lang/String;Z)Ljava/lang/String;",
        code.render(), 4, 4,
    )


def string_int_method(class_file: ClassFile, *, throw_python) -> Method:
    code = Bytecode()
    code.local(0x19, 0)
    whitespace = r"[\t\n\x0b\f\r \x85\p{Z}]"
    # Possessive repetition avoids regex-stack growth for long digit strings.
    grammar = class_file.constants.string(
        whitespace + r"*[+-]?\p{Nd}(?:_?\p{Nd})*+" + whitespace + "*",
    )
    code.emit(0x13, grammar.to_bytes(2, "big"))
    matches = class_file.method_reference(
        "java/lang/String", "matches", "(Ljava/lang/String;)Z",
    )
    code.emit(0xB6, matches.to_bytes(2, "big"))
    code.branch(0x9A, "int.valid")
    throw_python("ValueError", "invalid literal for int() with base 10", code, class_file)
    code.mark("int.valid")
    code.local(0x19, 0)
    separators = class_file.constants.string(whitespace + "|_")
    empty = class_file.constants.string("")
    code.emit(0x13, separators.to_bytes(2, "big"))
    code.emit(0x13, empty.to_bytes(2, "big"))
    replace = class_file.method_reference(
        "java/lang/String", "replaceAll",
        "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
    )
    code.emit(0xB6, replace.to_bytes(2, "big"))
    code.local(0x3A, 0)
    builder = class_file.constants.class_("java/lang/StringBuilder")
    code.emit(0xBB, builder.to_bytes(2, "big"))
    code.emit(0x59)
    init = class_file.method_reference("java/lang/StringBuilder", "<init>", "()V")
    code.emit(0xB7, init.to_bytes(2, "big"))
    code.local(0x3A, 1)
    code.emit(0x03)
    code.local(0x36, 2)
    code.mark("int.digit")
    code.local(0x15, 2)
    code.local(0x19, 0)
    length = class_file.method_reference("java/lang/String", "length", "()I")
    code.emit(0xB6, length.to_bytes(2, "big"))
    code.branch(0xA2, "int.parse")
    code.local(0x19, 0)
    code.local(0x15, 2)
    point = class_file.method_reference("java/lang/String", "codePointAt", "(I)I")
    code.emit(0xB6, point.to_bytes(2, "big"))
    code.local(0x36, 3)
    code.local(0x15, 3)
    code.emit(0x10, bytes((10,)))
    digit = class_file.method_reference("java/lang/Character", "digit", "(II)I")
    code.emit(0xB8, digit.to_bytes(2, "big"))
    code.local(0x36, 4)
    code.local(0x19, 1)
    code.local(0x15, 4)
    code.branch(0x9B, "int.sign")
    code.local(0x15, 4)
    code.emit(0x10, bytes((48,)))
    code.emit(0x60)
    code.branch(0xA7, "int.append")
    code.mark("int.sign")
    code.local(0x15, 3)
    code.mark("int.append")
    append = class_file.method_reference(
        "java/lang/StringBuilder", "appendCodePoint", "(I)Ljava/lang/StringBuilder;",
    )
    code.emit(0xB6, append.to_bytes(2, "big"))
    code.emit(0x57)
    code.local(0x15, 2)
    code.local(0x15, 3)
    count = class_file.method_reference("java/lang/Character", "charCount", "(I)I")
    code.emit(0xB8, count.to_bytes(2, "big"))
    code.emit(0x60)
    code.local(0x36, 2)
    code.branch(0xA7, "int.digit")
    code.mark("int.parse")
    code.local(0x19, 1)
    string = class_file.method_reference(
        "java/lang/StringBuilder", "toString", "()Ljava/lang/String;",
    )
    code.emit(0xB6, string.to_bytes(2, "big"))
    parse = class_file.method_reference(
        "java/lang/Long", "parseLong", "(Ljava/lang/String;)J",
    )
    start = len(code.code)
    code.emit(0xB8, parse.to_bytes(2, "big"))
    end = len(code.code)
    code.emit(0xAD)
    handler = len(code.code)
    code.emit(0x57)
    throw_python("OverflowError", "integer literal exceeds signed 64-bit range", code, class_file)
    return Method(
        0x0009, "pyjs_string_int", "(Ljava/lang/String;)J",
        code.render(), 3, 5,
        exception_handlers=(ExceptionHandler(start, end, handler, "java/lang/NumberFormatException"),),
    )


def string_boundary_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    length = class_file.method_reference("java/lang/String", "length", "()I")
    character = class_file.method_reference("java/lang/String", "charAt", "(I)C")
    code.local(0x15, 1)
    code.branch(0x99, "boundary.valid")
    code.local(0x15, 1)
    code.local(0x19, 0)
    code.emit(0xB6, length.to_bytes(2, "big"))
    code.branch(0x9F, "boundary.valid")
    code.local(0x19, 0)
    code.local(0x15, 1)
    code.emit(0x04)
    code.emit(0x64)
    code.emit(0xB6, character.to_bytes(2, "big"))
    high = class_file.method_reference("java/lang/Character", "isHighSurrogate", "(C)Z")
    code.emit(0xB8, high.to_bytes(2, "big"))
    code.branch(0x99, "boundary.valid")
    code.local(0x19, 0)
    code.local(0x15, 1)
    code.emit(0xB6, character.to_bytes(2, "big"))
    low = class_file.method_reference("java/lang/Character", "isLowSurrogate", "(C)Z")
    code.emit(0xB8, low.to_bytes(2, "big"))
    code.branch(0x9A, "boundary.invalid")
    code.mark("boundary.valid")
    code.emit(0x04)
    code.emit(0xAC)
    code.mark("boundary.invalid")
    code.emit(0x03)
    code.emit(0xAC)
    return Method(
        0x0009, "pyjs_string_boundary", "(Ljava/lang/String;I)Z",
        code.render(), 3, 2,
    )


def string_contains_method(class_file: ClassFile) -> Method:
    code = Bytecode()
    search = class_file.method_reference(
        "java/lang/String", "indexOf", "(Ljava/lang/String;I)I",
    )
    length = class_file.method_reference("java/lang/String", "length", "()I")
    boundary = class_file.method_reference(
        class_file.name, "pyjs_string_boundary", "(Ljava/lang/String;I)Z",
    )
    code.emit(0x03)
    code.local(0x36, 2)
    code.mark("contains.search")
    code.local(0x19, 0)
    code.local(0x19, 1)
    code.local(0x15, 2)
    code.emit(0xB6, search.to_bytes(2, "big"))
    code.local(0x36, 2)
    code.local(0x15, 2)
    code.branch(0x9B, "contains.missing")
    code.local(0x19, 0)
    code.local(0x15, 2)
    code.emit(0xB8, boundary.to_bytes(2, "big"))
    code.branch(0x99, "contains.next")
    code.local(0x19, 0)
    code.local(0x15, 2)
    code.local(0x19, 1)
    code.emit(0xB6, length.to_bytes(2, "big"))
    code.emit(0x60)
    code.emit(0xB8, boundary.to_bytes(2, "big"))
    code.branch(0x9A, "contains.found")
    code.mark("contains.next")
    code.emit(0x84, bytes((2, 1)))
    code.branch(0xA7, "contains.search")
    code.mark("contains.found")
    code.emit(0x04)
    code.emit(0xAC)
    code.mark("contains.missing")
    code.emit(0x03)
    code.emit(0xAC)
    return Method(
        0x0009, "pyjs_string_contains", "(Ljava/lang/String;Ljava/lang/String;)Z",
        code.render(), 3, 3,
    )


def string_affix_method(class_file: ClassFile, *, suffix: bool) -> Method:
    code = Bytecode()
    code.local(0x19, 0)
    code.local(0x19, 1)
    match = class_file.method_reference(
        "java/lang/String", "endsWith" if suffix else "startsWith",
        "(Ljava/lang/String;)Z",
    )
    code.emit(0xB6, match.to_bytes(2, "big"))
    code.branch(0x99, "affix.missing")
    code.local(0x19, 0)
    length = class_file.method_reference("java/lang/String", "length", "()I")
    if suffix:
        code.local(0x19, 0)
        code.emit(0xB6, length.to_bytes(2, "big"))
    code.local(0x19, 1)
    code.emit(0xB6, length.to_bytes(2, "big"))
    if suffix:
        code.emit(0x64)
    boundary = class_file.method_reference(
        class_file.name, "pyjs_string_boundary", "(Ljava/lang/String;I)Z",
    )
    code.emit(0xB8, boundary.to_bytes(2, "big"))
    code.emit(0xAC)
    code.mark("affix.missing")
    code.emit(0x03)
    code.emit(0xAC)
    name = "pyjs_string_endswith" if suffix else "pyjs_string_startswith"
    return Method(
        0x0009, name, "(Ljava/lang/String;Ljava/lang/String;)Z", code.render(), 3, 2,
    )


def string_repeat_method(class_file: ClassFile, *, throw_python) -> Method:
    code = Bytecode()
    empty_result = "string.repeat.empty"
    code.local(0x16, 1)
    code.emit(0x09)
    code.emit(0x94)
    code.branch(0x9E, empty_result)
    code.local(0x19, 0)
    length = class_file.method_reference("java/lang/String", "length", "()I")
    code.emit(0xB6, length.to_bytes(2, "big"))
    code.local(0x36, 3)
    code.local(0x15, 3)
    code.branch(0x99, empty_result)
    # Divide before comparing so even Long.MAX_VALUE cannot overflow the check.
    limit = class_file.constants.long(2**31 - 1)
    code.local(0x16, 1)
    code.emit(0x14, limit.to_bytes(2, "big"))
    code.local(0x15, 3)
    code.emit(0x85)
    code.emit(0x6D)
    code.emit(0x94)
    code.branch(0x9E, "string.repeat.valid")
    throw_python("MemoryError", "repeated string is too long", code, class_file)
    code.mark(empty_result)
    empty = class_file.constants.string("")
    if empty <= 255:
        code.emit(0x12, empty.to_bytes(1, "big"))
    else:
        code.emit(0x13, empty.to_bytes(2, "big"))
    code.emit(0xB0)
    code.mark("string.repeat.valid")
    builder = class_file.constants.class_("java/lang/StringBuilder")
    code.emit(0xBB, builder.to_bytes(2, "big"))
    code.emit(0x59)
    code.local(0x15, 3)
    code.local(0x16, 1)
    code.emit(0x88)
    code.emit(0x68)
    constructor = class_file.method_reference("java/lang/StringBuilder", "<init>", "(I)V")
    code.emit(0xB7, constructor.to_bytes(2, "big"))
    code.local(0x3A, 4)
    code.local(0x16, 1)
    code.emit(0x88)
    code.local(0x36, 3)
    code.mark("string.repeat.append")
    code.local(0x15, 3)
    code.branch(0x99, "string.repeat.done")
    code.local(0x19, 4)
    code.local(0x19, 0)
    append = class_file.method_reference(
        "java/lang/StringBuilder", "append", "(Ljava/lang/String;)Ljava/lang/StringBuilder;",
    )
    code.emit(0xB6, append.to_bytes(2, "big"))
    code.emit(0x57)
    code.emit(0x84, bytes((3, 255)))
    code.branch(0xA7, "string.repeat.append")
    code.mark("string.repeat.done")
    code.local(0x19, 4)
    to_string = class_file.method_reference(
        "java/lang/StringBuilder", "toString", "()Ljava/lang/String;",
    )
    code.emit(0xB6, to_string.to_bytes(2, "big"))
    code.emit(0xB0)
    return Method(
        0x0009,
        "pyjs_string_repeat",
        "(Ljava/lang/String;J)Ljava/lang/String;",
        code.render(),
        6,
        5,
    )
