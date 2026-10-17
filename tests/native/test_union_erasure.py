import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_casts_recover_tagged_unions_and_optional_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, value: int):
                self.value = value

            def __repr__(self) -> str:
                gc_collect()
                return "Item(" + str(self.value) + ")"

        class Child(Item):
            def __repr__(self) -> str:
                gc_collect()
                return "Child(" + str(self.value) + ")"

        type Value = bool | int | float | str | bytes | list[int] | tuple[int, str] | dict[str, int] | set[int] | frozenset[int] | Item | None

        def recover(value: object) -> Value:
            result = cast(Value, value)
            gc_collect()
            return result

        def optional_int(value: object) -> int | None:
            return cast(int | None, value)

        def optional_bool(value: object) -> bool | None:
            return cast(bool | None, value)

        def optional_float(value: object) -> float | None:
            return cast(float | None, value)

        def optional_list(value: object) -> list[int] | None:
            return cast(list[int] | None, value)

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [None, False, True, -7, 2.5, "café", b"bytes",
                                    [1, 2], (3, "four"), {"five": 5}, {6},
                                    frozenset([7]), Item(8), Child(9)]
            output = [repr(recover(value)) for value in values]
            for present in range(2):
                integer: object = -7 if present else None
                boolean: object = False if present else None
                floating: object = -0.0 if present else None
                original = [8] if present else None
                sequence: object = original
                recovered = optional_list(sequence)
                gc_collect()
                if recovered is not None:
                    recovered.append(9)
                output.append(str((optional_int(integer), optional_bool(boolean),
                                   optional_float(floating), recovered, recovered is original)))
            return "|".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_union_projection_without_formatting_or_type_tests(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect

        class Item:
            def __init__(self, value: int):
                self.value = value

        type Value = int | str | Item

        def erase(value: object) -> object:
            gc_collect()
            return value

        def main() -> int:
            first = cast(Value, erase(42))
            second = cast(Value, erase("café"))
            third = cast(Value, erase(Item(7)))
            gc_collect()
            return cast(int, first) + len(cast(str, second)) + cast(Item, third).value
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_erasure_preserves_runtime_kinds_across_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, value: int):
                self.value = value

            def __repr__(self) -> str:
                gc_collect()
                return "Item(" + str(self.value) + ")"

        class Child(Item):
            def __repr__(self) -> str:
                gc_collect()
                return "Child(" + str(self.value) + ")"

        class Box:
            def __init__(self, value: object):
                self.value = value

        type Value = int | bool | float | str | bytes | list[int] | tuple[int, str] | dict[str, int] | Item | None

        def identity(value: object) -> object:
            gc_collect()
            return value

        def erase(value: Value) -> object:
            return value

        def inspect(value: Value) -> str:
            local: object = value
            box = Box(value)
            values: list[object] = [value]
            gc_collect()
            return str([repr(local), repr(box.value), repr(values[0]),
                        repr(identity(value)), repr(erase(value)), repr(cast(object, value))])

        def main() -> str:
            gc_set_threshold(1)
            values: list[Value] = [None, False, True, 0, -5, 2.5, "café", b"bytes",
                                   [1, 2], (3, "four"), {"five": 5}, Item(6), Child(7)]
            return "\\n".join([inspect(value) for value in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_union_erasure_retains_cycles_and_container_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        type Value = int | str | list[Value] | None
        type Node = list[Node]

        def erase(value: Value) -> object:
            gc_collect()
            return value

        def erase_node(value: Node) -> object:
            return value

        def main() -> str:
            gc_set_threshold(1)
            values: list[Value] = [1, "two"]
            values.append(values)
            boxed = erase(values)
            gc_collect()
            cast(list[Value], boxed).append(None)
            node: Node = [[]]
            node.append(node)
            return repr(boxed) + repr(erase_node(node)) + str(boxed is values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_union_erasure_allocation_failure_preserves_previous_values(tmp_path, optimize, managed):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        class Box:
            def __init__(self, value: object):
                self.value = value

        type Value = int | str | list[int] | None

        def erase(value: Value) -> object:
            return value

        def boolean(value: bool | None) -> object:
            return value

        def main() -> int:
            original = [7]
            replacement = [42]
            values: list[Value] = [41, "changed", replacement]
            value: object = original
            box = Box(original)
            arm(1)
            if (erase(None) is not None or boolean(False) is not False
                    or boolean(True) is not True or boolean(None) is not None):
                return 3
            arm(0)
            for item in values:
                for mode in range(3):
                    caught = False
                    arm(1)
                    try:
                        if mode == 0:
                            value = item
                        elif mode == 1:
                            value = erase(item)
                        else:
                            box.value = item
                    except MemoryError:
                        caught = True
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if not caught or value is not original or box.value is not original:
                        return 1
            for item in values:
                value = erase(item)
                box.value = item
                {'gc_collect()' if managed else 'pass'}
                if repr(value) != repr(item) or repr(box.value) != repr(item):
                    return 2
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_erasure_preserves_none_payloads_and_reference_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        def integer(value: int | None) -> object:
            return value

        def floating(value: float | None) -> object:
            return value

        def boolean(value: bool | None) -> object:
            return value

        def text(value: str | None) -> object:
            return value

        def sequence(value: list[int] | None) -> object:
            return value

        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            for present in range(2):
                values: list[object] = [integer(-7 if present else None),
                                        floating(-0.0 if present else None),
                                        boolean(False if present else None),
                                        text("kept" if present else None)]
                output.append(repr(values))
                output.append(str([bool(value) for value in values]))
                original = [1, 2] if present else None
                boxed = sequence(original)
                gc_collect()
                if original is None:
                    output.append(str(boxed is None))
                else:
                    cast(list[int], boxed).append(3)
                    output.append(str(boxed is original))
                    output.append(repr(original))
            return "|".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_casts_preserve_boolean_identity_and_reference_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def integer(value: bool | int | str) -> str:
            result = cast(int, value)
            gc_collect()
            return repr(result) + str(result is True)

        def subset(value: int | str | list[int8] | None) -> list[int8] | None:
            return cast(list[int8] | None, value)

        def represented(value: int8 | str) -> int8:
            # An ordinary int annotation projects, rather than erases, the
            # selected arm's existing portable representation.
            return cast(int, value)

        def represented_optional(value: int8 | str | None) -> int8 | None:
            return cast(int8 | None, value)

        def main() -> str:
            gc_set_threshold(1)
            original = [int8(127)]
            recovered = subset(original)
            assert recovered is not None
            recovered.append(int8(130))
            cast(list[int], recovered).append(int8(131))
            gc_collect()
            return str((integer(True), integer(False), integer(7),
                        subset(None), recovered is original, original,
                        represented(int8(130)), represented_optional(None),
                        represented_optional(int8(130))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_casts_check_runtime_kind_and_erased_payload_layout(tmp_path, optimize):
    # typing.cast is unchecked on CPython. Native must validate the selected
    # arm before dereferencing a pointer or exposing a concrete scalar ABI.
    result = LLVM().run_source('''
        from typing import cast
        from pyjs import int8
        from pyjs.native import gc_collect

        class Base:
            def __init__(self, value: int):
                self.value = value

        class Child(Base):
            pass

        def child(value: Base | str) -> Child:
            return cast(Child, value)

        def erased(value: object) -> list[int] | str | None:
            return cast(list[int] | str | None, value)

        def scalar(value: int | str | None) -> str:
            return repr(cast(int, value))

        def subset(value: int | str | None) -> str | None:
            return cast(str | None, value)

        def optional(value: int | None) -> int:
            return cast(int, value)

        def represented(value: int8 | bool | str) -> int8:
            return cast(int8, value)

        def main() -> int:
            caught = 0
            wrong: list[object] = [1, True, [True], ["wrong"], (1,)]
            for value in wrong:
                try:
                    erased(value)
                except TypeError:
                    caught += 1
                gc_collect()
            for value in ["wrong", None]:
                try:
                    scalar(value)
                except TypeError:
                    caught += 1
            try:
                subset(1)
            except TypeError:
                caught += 1
            try:
                optional(None)
            except TypeError:
                caught += 1
            try:
                represented(True)
            except TypeError:
                caught += 1
            try:
                child(Base(7))
            except TypeError:
                caught += 1
            assert caught == 11
            assert scalar(0) == "0" and optional(7) == 7
            assert subset(None) is None and subset("good") == "good"
            assert represented(int8(130)) == int8(-126)
            original = Child(9)
            assert child(original) is original and child(original).value == 9
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0
    assert not result.stderr


@pytest.mark.parametrize("actual, expected, value", [
    ("list[bool] | str", "list[int]", "[True]"),
    ("object", "list[int] | list[str]", "[1]"),
    ("object", "int8 | str", "1"),
    ("object", "int8 | None", "1"),
    ("object", "int8", "1"),
])
def test_union_casts_reject_ambiguous_or_reinterpreted_layouts(actual, expected, value):
    with pytest.raises(LLVMUnsupported, match="layout|representation|storage"):
        transpile_llvm(f'''
            from typing import cast
            from pyjs import int8
            def recover(value: {actual}) -> {expected}:
                return cast({expected}, value)
            def main() -> str:
                return repr(recover({value}))
        ''')


@pytest.mark.parametrize("source, target, value", [
    ("int8 | str", "int16", "int8(1)"),
    ("list[int8] | str", "list[int16]", "[int8(1)]"),
])
def test_union_casts_cannot_change_portable_representation(source, target, value):
    with pytest.raises(CompilationError, match="cannot change.*representation"):
        transpile_llvm(f'''
            from typing import cast
            from pyjs import int8, int16
            def recover(value: {source}) -> {target}:
                return cast({target}, value)
            def main() -> str:
                return repr(recover({value}))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_boolean_identity_is_symmetric_and_allocation_free(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def compare(value: object, singleton: bool | None) -> str:
            gc_collect()
            return str((value is singleton, singleton is value,
                        value is not singleton, singleton is not value,
                        value is True, True is value,
                        value is False, False is value))

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [True, False, None, 0, 1, "", [], [1]]
            singletons: list[bool | None] = [True, False, None]
            return "|".join([compare(value, singleton)
                             for value in values for singleton in singletons])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
