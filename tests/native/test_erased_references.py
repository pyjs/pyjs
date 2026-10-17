import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_argument_packs_keep_boxing_roots_through_calls_and_constructors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def read(value: object) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, bytes):
                return value.decode()
            if isinstance(value, bool):
                return str(value)
            if isinstance(value, int):
                return str(int(value))
            return "none"

        def fixed(value: object = 7, *, label: object = "default") -> str:
            gc_collect()
            return read(value) + ":" + read(label)

        def collect(*values: object, **named: object) -> str:
            gc_collect()
            output = ""
            for value in values:
                output += read(value) + "/"
            for key, value in named.items():
                output += key + "=" + read(value) + "/"
            return output

        class Packed:
            def __init__(self, *values: object, **named: object):
                gc_collect()
                self.label = collect(*values, **named)

        def broken(*values: object, **named: object) -> str:
            gc_collect()
            if len(values) + len(named) > 0:
                raise ValueError("failed")
            return "empty"

        def main() -> str:
            gc_set_threshold(1)
            empty: list[int] = []
            small = [int(int8(130))]
            output = fixed(*[3]) + fixed(*empty) + fixed(**{"label": 9})
            output += fixed(*small) + fixed(None, label=True)
            output += collect(3, "x" + str(4), b"bytes", a=7, b="text")
            output += collect(*small, **{"a": "word"})
            output += Packed(3, "four", a=b"bytes").label
            output += Packed(*small, **{"x": True}).label
            for repeat in range(12):
                try:
                    broken(repeat, "x", value=repeat)
                except ValueError:
                    gc_collect()
                    output += fixed(*[repeat])
            return output + broken()
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_arguments_through_typed_callbacks_use_boxing_and_roots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def read(value: object) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, bytes):
                return value.decode()
            if isinstance(value, int):
                return str(int(value))
            return "none"

        def pair(left: object, right: object) -> str:
            gc_collect()
            return read(left) + "/" + read(right)

        class Bound:
            def __init__(self, prefix: str):
                self.prefix = prefix
            def pair(self, left: object, right: object) -> str:
                gc_collect()
                return self.prefix + pair(left, right)

        def use(callback: Callable[[object, object], str]) -> str:
            return callback("label" + str(1), b"bytes") + callback(42, None)

        def main() -> str:
            gc_set_threshold(1)
            return use(pair) + use(Bound("bound:").pair) + use(lambda a, b: pair(a, b))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_collections_retain_typed_payloads_and_mutable_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def erase(value: object) -> object:
            gc_collect()
            return value

        def union(value: list[int8] | str) -> object:
            return value

        def optional(value: list[int8] | None) -> object:
            return value

        def main() -> str:
            gc_set_threshold(1)
            integers = [1, 2]
            strings = {"a": "first"}
            numbers = {1, 2}
            frozen = frozenset(numbers)
            pair = (7, "label")
            small: list[int8] = [int8(120)]
            a = erase(integers)
            b = erase(strings)
            c = erase(numbers)
            d = erase(frozen)
            e = erase(pair)
            f = erase(small)
            g = union(small)
            h = optional(small)
            cast(list[int], a).append(3)
            cast(dict[str, str], b)["b"] = "second"
            cast(set[int], c).add(3)
            cast(list[int8], f).append(int8(130))
            gc_collect()
            return str((cast(list[int], a), cast(dict[str, str], b),
                        len(cast(set[int], c)), len(cast(frozenset[int], d)),
                        cast(tuple[int, str], e), cast(list[int8], f),
                        a is integers, b is strings, c is numbers, d is frozen, e is pair, f is small,
                        cast(list[int8], g) is small, cast(list[int8], h) is small,
                        optional(None) is None,
                        isinstance(a, list), isinstance(b, dict), isinstance(c, set),
                        isinstance(d, frozenset), isinstance(e, tuple), isinstance(a, dict)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_cast_rejects_incompatible_collection_layouts(tmp_path, optimize):
    # typing.cast is unchecked on CPython. Native deliberately checks physical
    # layouts before exposing an unboxed view, so this is a native boundary test.
    cases = [
        ("[True]", "list[int]"),
        ("small", "list[int]"),
        ("[[True]]", "list[list[int]]"),
        ("{'x': True}", "dict[str, int]"),
        ("(1, 'x')", "tuple[int, str, int]"),
    ]
    checks = []
    for index, (value, target) in enumerate(cases):
        checks.append(f'''
    value{index}: object = {value}
    try:
        cast({target}, value{index})
        return {index + 1}
    except TypeError:
        gc_collect()
''')
    source = '''
from typing import cast
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def main() -> int:
    gc_set_threshold(1)
    small: list[int8] = [int8(1)]
''' + "".join(checks) + "\n    return 0\n"
    result = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["object", "object | None"])
def test_erased_text_and_bytes_keep_contents_identity_and_gc_roots(tmp_path, optimize, annotation):
    source = '''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: object):
                self.value = value

        class Empty:
            pass

        def identity(value: object) -> object:
            gc_collect()
            return value

        def read(value: object) -> str:
            if isinstance(value, str):
                return "text:" + value
            if isinstance(value, bytes):
                return "bytes:" + value.decode()
            return "other"

        def text(index: int) -> str:
            gc_collect()
            return "β:" + str(index)

        def pair(left: object, right: object) -> str:
            gc_collect()
            return read(left) + "/" + read(right)

        def main() -> str:
            gc_set_threshold(1)
            original = text(7)
            data = original.encode()
            a: object = original
            b = identity(original)
            box = Box(identity(data))
            empty = Empty()
            erased = identity(empty)
            result = read(a) + "/" + read(b) + "/" + read(box.value)
            result += str((a is b, a is original, box.value is data,
                           erased is empty, cast(str, a) is original,
                           cast(bytes, box.value) is data))
            result += pair(text(1), text(2).encode())
            for index in range(8):
                box.value = text(index)
                gc_collect()
                result += read(box.value)
            return result
    '''
    result = LLVM().assert_matches_python(source.replace("object", annotation), directory=tmp_path,
                                          optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_and_tagged_references_rebox_once(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def erase(value: str | bytes | int) -> object:
            return value

        def optional(value: str | None) -> object:
            return value

        def read(value: object) -> str:
            gc_collect()
            if isinstance(value, str):
                return value
            if isinstance(value, bytes):
                return value.decode()
            if isinstance(value, int):
                return str(int(value))
            return "none"

        def main() -> str:
            gc_set_threshold(1)
            text = "hello" + str(5)
            data = text.encode()
            first = erase(text)
            second = erase(data)
            third = optional(text)
            fourth = optional(None)
            return (read(first) + read(second) + read(third) + read(fourth)
                    + read(erase(42)) + str((first is text, second is data, third is text,
                                            fourth is None)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_reference_casts_and_stale_field_proofs_are_checked(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: object | None):
                self.value = value

        def change(box: Box):
            box.value = b"changed"
            gc_collect()

        def main() -> str:
            gc_set_threshold(1)
            box = Box("text")
            result = ""
            if isinstance(box.value, str):
                change(box)
                try:
                    # Native checks the invalidated proof at the load; Python
                    # rejects the same str+bytes operation at concatenation.
                    result += "prefix:" + box.value
                except TypeError:
                    result += "stale"
            result += cast(bytes, box.value).decode()
            box.value = None
            gc_collect()
            return result + str(box.value is None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
