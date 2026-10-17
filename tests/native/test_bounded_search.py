import shutil
import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_bounded_text_search_contract(optimize):
    from tests.backend_semantics import BOUNDED_TEXT_SEARCH_CONTRACT
    result = LLVM().assert_matches_python(BOUNDED_TEXT_SEARCH_CONTRACT.source,
                                         optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("binary", [False, True], ids=["unicode", "bytes"])
def test_search_bounds_and_tuple_affixes_match_python(optimize, binary):
    values = ["", "aé\0界😀é", "éé"]
    needles = ["", "é", "\0", "missing"]
    if binary:
        values = [b"", b"a\xc3\xa9\0\xff\x80b\xc3\xa9", b"\xc3\xa9\xc3\xa9"]
        needles = [b"", b"\xc3\xa9", b"\xa9", b"\xff"]
    empty = b"" if binary else ""
    result = LLVM().assert_matches_python(f'''
        def main() -> str:
            bounds: list[int | None] = [None, -9223372036854775808, -1, 0, 2, 9223372036854775807]
            result: list[str] = []
            for value in {values!r}:
                for needle in {needles!r}:
                    for start in bounds:
                        for stop in bounds:
                            result.append(str((value.find(needle, start, stop),
                                value.rfind(needle, start, stop), value.count(needle, start, stop),
                                value.startswith((needle, {empty!r}), start, stop),
                                value.endswith((needle, {empty!r}), start, stop))))
                            try:
                                result.append(str(value.index(needle, start, stop)))
                            except ValueError as error:
                                result.append(str(error))
                            try:
                                result.append(str(value.rindex(needle, start, stop)))
                            except ValueError as error:
                                result.append(str(error))
            return "|".join(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_byte_needles_preserve_bounds_errors_and_union_kinds(optimize):
    result = LLVM().assert_matches_python(r'''
        def search(value: bytes, needle: bytes | int, start: int | None, stop: int | None) -> str:
            result = str((value.find(needle, start, stop), value.rfind(needle, start, stop),
                          value.count(needle, start, stop)))
            try:
                result += str(value.index(needle, start, stop))
            except ValueError:
                result += "missing"
            try:
                result += str(value.rindex(needle, start, stop))
            except ValueError:
                result += "missing"
            return result
        def main() -> str:
            result: list[str] = []
            needles: list[bytes | int] = [b"", b"\xff", 0, 97, 255]
            for value in [b"", b"a\xff\0a\xff"]:
                for needle in needles:
                    for start in [None, -9223372036854775808, -1, 0, 99]:
                        result.append(search(value, needle, start, None))
                        result.append(search(value, needle, start, -1))
            for needle in [-1, 256]:
                try:
                    result.append(search(b"", needle, 99, 0))
                except ValueError as error:
                    result.append(str(error))
            result.append(str(b"\0\1".find(True)))
            return "|".join(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_bound_callbacks_run_after_arguments_before_search_and_retain_temporaries(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Bound:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events
            def __index__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                if self.value == 99:
                    raise ValueError("bad bound")
                return self.value
        class Derived(Bound):
            def __index__(self) -> int:
                gc_collect()
                self.events.append(77)
                return 1
        def bound(value: int, events: list[int]) -> Bound:
            events.append(-value)
            return Bound(value, events)
        def find(value: object) -> int:
            return "aé😀".find("é", value)
        def inherited(value: Bound) -> bool:
            return "aé😀".startswith(("bad", "é"), value)
        def prefix(events: list[int]) -> str:
            events.append(55)
            return ("é" * 3)[1:]
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = ("aé😀" * 2)[1:].find("é", bound(1, events), bound(-1, events))
            second = (b"a\\xc3\\xa9" * 2)[1:].rfind(169, bound(1, events), bound(-1, events))
            found = inherited(Derived(0, events))
            found = found and ("aéé" * 2)[3:].startswith(
                (prefix(events), "missing"), bound(1, events), bound(3, events))
            try:
                "text".startswith((), bound(99, events), bound(2, events))
            except ValueError:
                events.append(88)
            try:
                b"".find(256, bound(99, events), bound(2, events))
            except ValueError as error:
                events.append(44 if str(error) == "bad bound" else 33)
            result = [find(None), find(0), find(Bound(1, events))]
            for invalid in [1.5, "bad"]:
                try:
                    find(invalid)
                except TypeError:
                    events.append(66)
            return repr((first, second, found, result, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_affix_tuple_views_and_single_or_tuple_union_needles(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def check(value: str, prefixes: str | tuple[str, ...], start: int | None) -> str:
            return str(value.startswith(prefixes, start)) + str(value.endswith(prefixes, start))
        def main() -> str:
            gc_set_threshold(1)
            prefixes = tuple(["absent", "é"])
            gc_collect()
            return (check("é😀é", prefixes, None) + check("é😀é", "é", 1)
                    + check("é😀é", (), 0) + str(b"x".endswith(())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_invalid_bound_messages_match_python_through_optional_and_erased_views(optimize):
    result = LLVM().assert_matches_python('''
        class Missing:
            pass
        def optional(value: float | None) -> int:
            return "text".find("e", value)
        def erased(value: object) -> bool:
            return b"text".endswith((b"t",), 0, value)
        def main() -> str:
            messages: list[str] = []
            for invalid in [1.5, "x", b"x", Missing()]:
                try:
                    erased(invalid)
                except TypeError as error:
                    messages.append(str(error))
            try:
                optional(1.5)
            except TypeError as error:
                messages.append(str(error))
            messages.append(str(optional(None)))
            return repr(messages)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_anchored_affixes_keep_long_haystacks_out_of_the_candidate_scan(optimize):
    # Validate the direct-comparison path on large Unicode/binary sources and
    # both long and short candidates. Timing is measured separately, not gated.
    result = LLVM().assert_matches_python(r'''
        def main() -> str:
            middle = "é😀\0" * 4096
            text = "head" + middle + "tail"
            data = b"head" + b"\xff\x80\0" * 4096 + b"tail"
            return repr((text.startswith(("absent", "head")),
                         text.endswith(("absent", "tail")),
                         not text.startswith(("absent", "tail")),
                         not text.endswith(("absent", "head")),
                         text.startswith("head" + middle),
                         text.endswith(middle + "tail"),
                         data.startswith((b"absent", b"head")),
                         data.endswith((b"absent", b"tail")),
                         text.startswith((middle,), 4, -4),
                         text.endswith((middle,), 4, -4),
                         "".startswith(("x", "")), b"".endswith((b"x", b""))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_bounded_searches_do_not_allocate(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining
        def search(text: str, data: bytes, prefixes: tuple[str, str], raw: tuple[bytes, bytes]) -> bool:
            return (text.find("😀", 1, -1) == 3 and text.rfind("é", 1, None) == 5
                    and text.count("", 1, -1) == 5 and text.startswith(prefixes, 1, 4)
                    and text.endswith(prefixes, 0, -1) and data.find(169, 1, -1) == 2
                    and data.rfind(b"\\xc3\\xa9", 1, None) == 4 and data.count(169, 1) == 2
                    and data.startswith(raw, 1, 4) and data.endswith(raw, 0, -1))
        def main() -> int:
            text = ("aé界😀bé" * 2)[6:]
            data = (b"a\\xc3\\xa9b\\xc3\\xa9" * 2)[6:]
            prefixes = ("é", "b")
            raw = (b"\\xc3\\xa9", b"\\xc3")
            for index in range(512):
                arm(1)
                success = search(text, data, prefixes, raw)
                untouched = remaining() == 1
                arm(0)
                if not success or not untouched:
                    return 1
                {'gc_collect()' if managed else 'pass'}
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert not result.stdout and not result.stderr


def test_search_bound_temporaries_do_not_accumulate_on_the_stack(tmp_path):
    limiter = shutil.which("prlimit")
    if limiter is None:
        pytest.skip("requires Linux prlimit for bounded native execution")
    source = transpile_llvm('''
        def search(start: int | None) -> bool:
            return "aé".startswith("é", start, None)
        def main() -> int:
            for index in range(100000):
                start: int | None = 1
                if not "aé".startswith("é", start, None) or not search(start):
                    return 1
            return 0
    ''')
    executable = LLVM().compile(source, tmp_path, optimize=0)
    result = subprocess.run([limiter, "--as=67108864", "--stack=262144", "--core=0", executable],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, (result.stdout, result.stderr)
