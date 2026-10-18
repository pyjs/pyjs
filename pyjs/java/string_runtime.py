"""Demand-driven JVM helpers for Python string semantics."""

from functools import partial

from .classfile import Bytecode, ClassFile, ExceptionHandler, Method


def emit_string_helpers(class_file: ClassFile, required: set[str], throw_python) -> None:
    required = required | ({"length"} if "getitem" in required else set())
    if required & {"contains", "startswith", "endswith"}:
        required = required | {"boundary"}
    for name, factory in (
        ("length", string_length_method),
        ("getitem", partial(string_getitem_method, throw_python=throw_python)),
        ("repeat", partial(string_repeat_method, throw_python=throw_python)),
        ("strip", string_strip_method),
        ("int", partial(string_int_method, throw_python=throw_python)),
        ("boundary", string_boundary_method),
        ("contains", string_contains_method),
        ("startswith", partial(string_affix_method, suffix=False)),
        ("endswith", partial(string_affix_method, suffix=True)),
    ):
        if name in required:
            class_file.add_method(factory(class_file))


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
