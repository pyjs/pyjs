import pytest

from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


def test_binary_literal_keeps_its_type_and_exact_payload_in_ir():
    with analyze_source(
        r'def main() -> bytes: return b"\0\xff"', environment=NATIVE_ENVIRONMENT,
    ) as analysis:
        assert analysis.types == (
            "def main() -> bytes:\n"
            "    block entry:\n"
            "        return b'\\x00\\xff'"
        )


@pytest.mark.parametrize("optimize", [0, 2])
def test_bytes_construction_codecs_and_raw_payloads(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
from pyjs.native import gc_collect, gc_set_threshold
def main() -> str:
    gc_set_threshold(1)
    items = [0, 1, 127, 128, 255]
    value = bytes(items)
    copied = bytes(value)
    items[0] = 99
    gc_collect()
    text = "é😀\0text"
    encoded = text.encode(encoding="utf8", errors="strict")
    boundaries = "\x7f\x80\u07ff\u0800\ud7ff\ue000\uffff\U00010000\U0010ffff"
    assert boundaries.encode().decode() == boundaries
    return "|".join([
        value.hex(), copied.hex(), bytes(3).hex(), bytes().hex(), bytes([]).hex(),
        str(value), b"a'b".__str__(),
        str(value[0]), str(value[-1]), str(len(value)),
        str(bool(value)), str(bool(bytes())),
        str(255 in value), str(b"\x7f\x80" in value),
        encoded.decode("utf-8"), str(encoded == text.encode()),
        (b"a" + b"\xff").hex(), (2 * b"\x00\xfe").hex(),
        str(b"ab"[True]), (b"xy" * False).hex(), "x".zfill(True),
    ])
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_binary_editing_never_decodes_utf8(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
from pyjs.native import gc_collect
def main() -> str:
    value = b" \xff\xc3\xa9\x00\xff "
    trimmed = value.strip()
    parts = trimmed.split(b"\xff")
    gc_collect()
    return "|".join([
        trimmed.hex(), value[::-1].hex(), value[1:-1:2].hex(),
        value.replace(b"", b"x", 3).hex(), b"::".join(parts).hex(),
        value.lstrip(b" \xff").hex(), value.rstrip(b" \xff").hex(),
        str(value.find(b"\xff", 2)), str(value.rfind(b"\xff", -5)),
        str(value.count(b"", 1, -1)), str(value.startswith(b"\xff", 1)),
        str(value.endswith(b"\xff", 1, -1)),
        b" \t \xff ".split()[0].hex(),
    ])
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_padding_tabs_affixes_and_partitions(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
from pyjs.native import gc_collect
def main() -> str:
    value = "é😀"
    parts = "é::😀::x".partition("::")
    missing = value.rpartition("missing")
    binary = b"a\xffb\xffc".rpartition(b"\xff")
    gc_collect()
    return "|".join([
        value.ljust(5, "😀"), value.rjust(5), value.center(5, "é"),
        "ab".center(5, "-"), "ab".center(4, "-"),
        "-é".zfill(5), "+".zfill(4), "".zfill(2),
        "é\t😀\t\r\nx\t".expandtabs(4), "a\tb".expandtabs(0),
        value.removeprefix("é"), value.removesuffix("😀"), value.removesuffix(""),
        parts[0], parts[1], parts[2], missing[0], missing[1], missing[2],
        binary[0].hex(), binary[1].hex(), binary[2].hex(),
        b"\xffa".removeprefix(b"\xff").hex(),
        b"a\xff".removesuffix(b"\xff").hex(),
    ])
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_splitlines_uses_different_binary_and_unicode_boundaries(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
def main() -> str:
    source = "a\r\nb\rc\nd\ve\ff\x1cg\x1dh\x1ei\x85j\u2028k\u2029"
    binary = source.encode()
    text_lines = source.splitlines(True)
    byte_lines = binary.splitlines(False)
    outputs: list[str] = []
    for value in text_lines:
        outputs.append(value.encode().hex())
    outputs.append("bytes")
    for line in byte_lines:
        outputs.append(line.hex())
    outputs.append(str(len("".splitlines())))
    outputs.append(str(len(b"\r\n".splitlines())))
    return "|".join(outputs)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_and_byte_errors_are_catchable_and_recoverable(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
from pyjs.native import gc_collect
def main() -> str:
    messages: list[str] = []
    try:
        bytes(-1)
    except ValueError as error:
        messages.append(str(error))
    try:
        bytes([256])
    except ValueError as error:
        messages.append(str(error))
    try:
        b"x"[2]
    except IndexError as error:
        messages.append(str(error))
    try:
        256 in b"x"
    except ValueError as error:
        messages.append(str(error))
    try:
        b"\xff".decode()
    except UnicodeDecodeError:
        messages.append("decode")
    invalid = [b"\x80", b"\xc0\x80", b"\xe0\x80\x80", b"\xed\xa0\x80",
               b"\xf4\x90\x80\x80", b"\xe2\x82", b"ok\xf0\x9f\x98"]
    for payload in invalid:
        try:
            payload.decode()
            messages.append("unexpected success")
        except UnicodeError:
            messages.append("invalid")
    try:
        "abc".index("x")
    except ValueError as error:
        messages.append(str(error))
    try:
        b"abc".rindex(b"x")
    except ValueError as error:
        messages.append(str(error))
    try:
        "abc".center(0, "")
    except TypeError as error:
        messages.append(str(error))
    try:
        b"x".partition(b"")
    except ValueError as error:
        messages.append(str(error))
    gc_collect()
    messages.append("ok".encode().decode())
    return "|".join(messages)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_byte_operand_effects_and_expansion_overflow(tmp_path, optimize):
    LLVM().assert_matches_python(r'''
def data(order: list[int]) -> bytes:
    order.append(2)
    return b"\x02"

def count(order: list[int]) -> int:
    order.append(1)
    return 2

def main() -> str:
    order: list[int] = []
    assert count(order) in data(order)
    assert order[0] == 1 and order[1] == 2
    order.clear()
    assert data(order).__contains__(count(order))
    assert order[0] == 2 and order[1] == 1
    order.clear()
    assert count(order) * data(order) == b"\x02\x02"
    assert order[0] == 1 and order[1] == 2
    caught = 0
    try:
        "é".center(9223372036854775807, "😀")
    except (MemoryError, OverflowError):
        caught += 1
    try:
        "é".zfill(9223372036854775807)
    except (MemoryError, OverflowError):
        caught += 1
    try:
        "\t\t".expandtabs(9223372036854775807)
    except (MemoryError, OverflowError):
        caught += 1
    return str(caught) + b"recovered".decode()
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("expression", [
    '"x".encode("latin1")', 'b"x".decode(errors="replace")',
    '"x".encode(encoding)', 'b"x".decode(errors="STRICT")',
])
def test_unsupported_codecs_fail_before_compilation(expression):
    with pytest.raises(LLVMUnsupported, match="literal UTF-8 encoding and strict errors"):
        transpile_llvm(f'''
def main() -> int:
    encoding = "utf-8"
    value = {expression}
    return len(value)
''')
