import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_byte_membership_dispatches_union_needles_and_checks_empty_haystacks(tmp_path, optimize):
    result = LLVM().assert_matches_python(r'''
from pyjs.native import gc_collect, gc_set_threshold
def check(needle: bytes | int | None, value: bytes) -> str:
    try:
        return str((needle in value, needle not in value))
    except (ValueError, TypeError) as error:
        return str(error)
def main() -> str:
    gc_set_threshold(1)
    needles: list[bytes | int | None] = [b"", b"\xff", b"missing", 0, 1, 255, 97,
                                       True, False, -1, 256, -9223372036854775808,
                                       9223372036854775807, None]
    result: list[str] = []
    for needle in needles:
        gc_collect()
        for value in [b"", b"a\0\x01\xff"]:
            result.append(check(needle, value))
    return "|".join(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_membership_keeps_optional_and_portable_scalar_representations(tmp_path, optimize):
    result = LLVM().assert_matches_python(r'''
from pyjs import int8, int64, uint32
from enum import IntEnum, StrEnum
class Byte(IntEnum):
    ZERO = 0
    LAST = 255
class Letter(StrEnum):
    A = "a"
def text(needle: str | None) -> str:
    try:
        return str(needle in "abc")
    except TypeError as error:
        return str(error)
def integer(needle: int | None) -> str:
    try:
        return str(needle in b"\0\x01\xff")
    except TypeError as error:
        return str(error)
def main() -> str:
    results = [text(None), text("a"), text("x"), integer(None), integer(1), integer(42)]
    results.append(str((int8(0) in b"\0", Byte.LAST in b"\xff", Letter.A in "abc")))
    try:
        results.append(str(uint32(4294967295) in b""))
    except ValueError as error:
        results.append(str(error))
    try:
        results.append(str(int64(9223372036854775807) in b""))
    except ValueError as error:
        results.append(str(error))
    return "|".join(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_membership_evaluates_operands_once_in_python_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def needle(events: list[str], number: bool) -> bytes | int:
    events.append("needle")
    gc_collect()
    return 97 if number else (b"xabc" * 2)[1:3]
def haystack(events: list[str]) -> bytes:
    events.append("haystack")
    gc_collect()
    return (b"abc" * 3)[1:]
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    result: list[bool] = []
    for number in [False, True]:
        result.append(needle(events, number) in haystack(events))
        result.append(needle(events, number) not in haystack(events))
        result.append(haystack(events).__contains__(needle(events, number)))
    return repr((result, events))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_byte_membership_does_not_allocate_a_needle(tmp_path, optimize):
    source = transpile_llvm(r'''
from tests.native.allocation_support import arm, remaining
def check(needle: bytes | int) -> bool:
    return needle in b"a\xffb\xff"
def main() -> int:
    needles: list[bytes | int] = [255, b"\xff"]
    for needle in needles:
        arm(1000)
        result = check(needle)
        allocations = 1000 - remaining()
        arm(0)
        if not result or allocations != 0:
            return 1
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=False, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("annotation, value", [("str | int", '"a"'), ("object", "97")])
def test_membership_does_not_reinterpret_unsupported_needle_storage(annotation, value):
    with pytest.raises(LLVMUnsupported, match="membership requires"):
        transpile_llvm(f'''
def check(needle: {annotation}) -> bool:
    return needle in b"abc"
def main() -> bool:
    return check({value})
''')
