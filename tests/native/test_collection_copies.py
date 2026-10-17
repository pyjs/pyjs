"""Copied slots can widen; shared mutable payloads cannot be reinterpreted."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.analysis.diagnostics import CompilationError
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("expression", ["left + right", "left.__add__(right)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_concatenation_converts_copied_slots_and_keeps_input_order(tmp_path, expression, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        def make_left(events: list[str]) -> list[bool | str]:
            events.append("left")
            gc_collect()
            return ["start", False]
        def make_right(events: list[str]) -> list[bool]:
            events.append("right")
            gc_collect()
            return [True, False]
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            first = {expression.replace('left', 'make_left(events)').replace('right', 'make_right(events)')}
            left: list[bool | str] = ["é", False]
            right = [True, False]
            copied = {expression}
            copied.append("tail")
            right.append(True)
            gc_collect()
            nested: list[list[str] | str] = ["header"]
            words = ["雪"]
            joined = nested + [words]
            words.append("tail")
            return str((first, events, copied, left, right, joined,
                        copied is left, copied is right))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("source", ["original", "tuple(original)", "iter(original)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_copy_upcasts_objects_without_widening_source_alias(tmp_path, source, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __init__(self, value: int): self.value = value
        class Child(Base):
            def __init__(self, value: int):
                super().__init__(value)
                self.extra = 42
        def main() -> str:
            gc_set_threshold(1)
            original = [Child(1), Child(2)]
            copied = list[Base]({source})
            copied.append(Base(3))
            widened: list[Base] = [Base(4)]
            combined = widened + original
            original[0].value = 10
            gc_collect()
            return str((len(original), original[0].extra,
                        copied[0] is original[0], combined[1] is original[0],
                        [item.value for item in copied],
                        [item.value for item in combined],
                        isinstance(copied[2], Child)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", [
    "numbers + words", "empty + words", "numbers + empty",
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_concatenation_boxes_items_in_destination_storage(tmp_path, expression, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            numbers: list[object] = [1, True]
            empty: list[object] = []
            words = ["hello", "雪"]
            copied = {expression}
            words.clear()
            gc_collect()
            return str((copied, len(empty), len(numbers)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("source", ["children", "iter(children)", "(child for child in children)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_staging_upcasts_items_without_widening_source(tmp_path, source, optimize):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, value: int): self.value = value
class Child(Base):
    pass
def main() -> str:
    gc_set_threshold(1)
    children = [Child(7), Child(8)]
    first = children[0]
    values: list[Base] = [Base(1), Base(2), Base(3), Base(4)]
    values[::2] = {source}
    assert values[0] is first and values[2] is children[1]
    error = ""
    try:
        values[::2] = [Child(9)]
    except ValueError as caught:
        error = str(caught)
    assert [item.value for item in values] == [7, 2, 8, 4]
    values[1:3] = {source}
    children.clear()
    first.value = 70
    gc_collect()
    assert values[0] is first and values[1] is first
    return repr(([item.value for item in values], children, error))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["words + empty", "empty + []"])
def test_concatenation_preserves_analyzer_operand_contract(expression):
    # The existing declaration accepts list[T] on a list[T] receiver. Native
    # copied-slot adaptation does not change shared binary type inference.
    with pytest.raises(CompilationError, match="Operator '\\+' is not supported"):
        transpile_llvm(f'''
            def main() -> int:
                words = ["hello"]
                empty: list[object] = []
                return len({expression})
        ''')


@pytest.mark.parametrize("expression", ["list[Base](original)", "wide + original"])
def test_copy_does_not_widen_nested_mutable_aliases(expression):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
            class Item: pass
            class Child(Item): pass
            type Base = list[Item]
            def main() -> int:
                original = [[Child()]]
                wide: list[list[Item]] = [[Item()]]
                copied = {expression}
                return len(copied)
        ''')


@pytest.mark.parametrize("expression", ["list[int](source)", "values + source"])
def test_copy_retains_explicit_numeric_conversion_boundary(expression):
    with pytest.raises(LLVMUnsupported, match="matching item types"):
        transpile_llvm(f'''
            def main() -> int:
                values = [1]
                source = [True, False]
                copied: list[int] = {expression}
                return len(copied)
        ''')
