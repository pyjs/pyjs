"""Nullable comparison branches reuse rich dispatch, not presence equality."""

import subprocess

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_equality_and_inequality_keep_distinct_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Value:
            def __init__(self, events: list[str]):
                self.events = events

            def __eq__(self, other: object) -> bool:
                self.events.append("eq")
                gc_collect()
                return True

            def __ne__(self, other: object) -> bool:
                self.events.append("ne")
                gc_collect()
                return True

        def compare(value: Value | None) -> str:
            return str((value == None, None == value, value != None, None != value,
                        value == value, value != value, [value] == [value]))

        def main() -> str:
            events: list[str] = []
            value = Value(events)
            return compare(value) + compare(None) + str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_membership_invokes_custom_none_equality_in_both_directions(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Value:
            def __init__(self, events: list[str]):
                self.events = events

            def __eq__(self, other: object) -> bool:
                self.events.append("compared")
                gc_collect()
                return other is None

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            data: dict[int, Value | None] = {1: Value(events)}
            target = Value(events)
            missing = {1: None}
            return str((None in data.values(), (1, None) in data.items(),
                        target in missing.values(), (1, target) in missing.items(),
                        target in iter([None]), events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation", ["Base", "Base | None", "Base | str | None"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_member_comparison_keeps_subtype_priority(tmp_path, annotation, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, events: list[str]):
                self.events = events

            def __eq__(self, other: Base) -> bool:
                self.events.append("base")
                gc_collect()
                return False

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                self.events.append("child")
                gc_collect()
                return True

        def search(value: {annotation}, target: {annotation}) -> str:
            data: dict[int, {annotation}] = {{1: value}}
            return str(((1, target) in data.items(), target in data.values(),
                        target in iter([value])))

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            base: Base = Base(events)
            child: Base = Child(events)
            return str((search(base, child), search(child, base), search(base, base), events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_virtual_argument_checks_apply_only_to_the_selected_override(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Base:
            def __eq__(self, other: Base) -> bool:
                return False

        class Child(Base):
            def __eq__(self, other: object) -> bool:
                return other is None

        def compare(left: Base | None, right: Base | None) -> bool:
            return left == right

        def main() -> str:
            return str((compare(Child(), None), compare(None, Child()),
                        compare(Base(), Base()), compare(None, None)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_comparison_preserves_notimplemented_and_generated_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass
        from types import NotImplementedType

        class Declines:
            def __init__(self, events: list[str]):
                self.events = events
            def __eq__(self, other: object) -> NotImplementedType:
                self.events.append("eq")
                return NotImplemented
            def __ne__(self, other: object) -> NotImplementedType:
                self.events.append("ne")
                return NotImplemented

        @dataclass
        class Row:
            number: int

        def compare(value: Declines | None) -> str:
            return str((value == None, None == value, value != None,
                        value == value, value != value, [value] == [value]))

        def rows(left: Row | None, right: Row | None) -> str:
            return str((left == right, left != right, [left] == [right]))

        def main() -> str:
            events: list[str] = []
            return (compare(Declines(events)) + compare(None) + str(events)
                    + rows(Row(1), None) + rows(None, Row(1))
                    + rows(Row(1), Row(1)) + rows(Row(1), Row(2)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_view_identity_distinguishes_direct_and_container_comparisons(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import KeysView

        class Key:
            def __init__(self):
                self.fail = False

            def __hash__(self) -> int:
                if self.fail:
                    raise ValueError("hash called")
                return 1

        def compare(view: KeysView[Key] | None) -> str:
            nested = [view] == [view]
            try:
                return str((nested, view == view))
            except ValueError as error:
                return str(nested) + str(error)

        def main() -> str:
            key = Key()
            view = {key: 1}.keys()
            key.fail = True
            return compare(view) + compare(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("operation", ["==", "!="])
@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_comparison_retention_survives_requests_and_callback_failure(tmp_path, operation, optimize):
    method = "__eq__" if operation == "==" else "__ne__"
    source = f'''
from pyjs.native import gc_collect
class Value:
    def __init__(self, number: int, fail: bool):
        self.number = number
        self.fail = fail
    def {method}(self, other: object) -> bool:
        SAVED.append(self)
        gc_collect()
        if self.fail:
            raise ValueError("saved before failure")
        return other is None
SAVED: list[Value] = []
def compare(value: Value | None) -> bool:
    return value {operation} None
def render(number: int, fail: bool) -> str:
    found = compare(Value(number, fail))
    gc_collect()
    return str((found, [value.number for value in SAVED]))
'''
    namespace = {}
    exec(source, namespace)
    requests = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for number, fail in requests:
        if fail:
            with pytest.raises(ValueError, match="saved before failure"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))
    # ctypes libraries are unsanitized; the standalone cases above use ASan/UBSan.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in requests:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="saved before failure"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_incompatible_optional_callback_arguments_fail_only_when_selected(tmp_path, optimize):
    # None is outside Narrow.__eq__'s declared argument contract. Native code
    # checks that selected arm instead of interpreting null as a Narrow object;
    # this intentionally tests the diagnostic boundary, not CPython parity.
    source = '''
        class Narrow:
            def __eq__(self, other: Narrow) -> bool:
                return True

        def compare(left: Narrow | None, right: Narrow | None) -> bool:
            return left == right

        def main() -> int:
            assert compare(Narrow(), Narrow())
            try:
                compare(Narrow(), None)
            except TypeError as error:
                assert str(error) == "__eq__ requires a compatible typed argument"
            else:
                return 1
            assert compare(None, None)
            assert compare(Narrow(), Narrow())
            return 0
    '''
    executable = LLVM().compile(transpile_llvm(source), tmp_path, optimize=optimize,
                                sanitizers=("address", "undefined"))
    result = subprocess.run([executable], capture_output=True, timeout=15)
    assert (result.returncode, result.stdout, result.stderr) == (0, b"", b"")


def test_statically_incompatible_callback_arguments_remain_a_compile_error():
    with pytest.raises(LLVMUnsupported, match="compatible typed argument"):
        transpile_llvm('''
            class Narrow:
                def __eq__(self, other: Narrow) -> bool:
                    return True
            def main() -> bool:
                return Narrow() == None
        ''')
