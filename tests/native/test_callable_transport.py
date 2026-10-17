"""Argument provenance and scalar refinements across native callback calls."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("base", "scalar", "first", "second"), [
    ("IntEnum", "int", "1", "2"), ("StrEnum", "str", "'one'", "'two'"),
])
def test_enum_callback_arguments_and_optional_results(tmp_path, optimize, base, scalar, first, second):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from enum import {base}
        class State({base}):
            ONE = {first}
            TWO = {second}
        def read(value: {scalar}) -> State:
            return State(value)
        def apply(callback: Callable[[{scalar}], State | None]) -> str:
            return repr(callback({first})) + ':' + repr(callback({second}))
        def identity(value: State) -> State:
            return value
        def visit(callback: Callable[[State], State]) -> str:
            return repr(callback(State.ONE)) + ':' + repr(callback(State.TWO))
        def main() -> str:
            return apply(read) + ':' + visit(identity)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("base", "scalar", "value"), [
    ("IntEnum", "int", "1"), ("StrEnum", "str", "'one'"),
])
def test_callback_arguments_do_not_implicitly_erase_enums(base, scalar, value):
    with pytest.raises(LLVMUnsupported, match="scalar enums cannot be erased or widened"):
        transpile_llvm(f'''
            from collections.abc import Callable
            from enum import {base}
            class State({base}):
                ONE = {value}
            def read(value: {scalar}, equal_value: {scalar}) -> str:
                return repr(value)
            def apply(callback: Callable[[{scalar}, {scalar}], str]) -> str:
                return callback(State.ONE, {value})
            def main() -> str:
                return apply(read)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_enum_callback_consumers_preserve_item_types(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from enum import IntEnum
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold
        class State(IntEnum):
            ONE = 1
            TWO = 2
        def read(value: int) -> State:
            gc_collect()
            return State(value)
        def key(value: State) -> str:
            gc_collect()
            return value.name
        def accumulate(total: int, value: State) -> int:
            gc_collect()
            return total + value.value
        def keep(value: State) -> bool:
            return value is State.TWO
        def main() -> str:
            gc_set_threshold(1)
            values = list(map(read, [2, 1]))
            ordered = sorted(values, key=key)
            values.sort(key=key, reverse=True)
            return repr((values, ordered, max(values, key=key), min(values, key=key),
                         reduce(accumulate, values, 0), list(filter(keep, values))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ['Literal["yes", "no"]', 'Literal["yes"] | Literal["no"]'])
def test_multivalue_literal_callback_result(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from typing import Literal
        def answer(value: bool) -> {annotation}:
            return "yes" if value else "no"
        def consume(callback: Callable[[bool], str]) -> str:
            return callback(True) + ':' + callback(False)
        def main() -> str:
            assert answer(True).upper() == "YES"
            assert len(answer(False)) == 2
            return answer(True) + ':' + answer(False) + ':' + consume(answer)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ['Literal["yes", "no"] | None', 'Literal["yes"] | Literal["no"] | None'])
def test_optional_literal_callback_result(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Callable
        from typing import Literal
        def answer(value: int) -> {annotation}:
            if value == 0:
                return None
            return "yes" if value == 1 else "no"
        def consume(callback: Callable[[int], str | None]) -> str:
            return repr((callback(0), callback(1), callback(2)))
        def main() -> str:
            return consume(answer)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("annotation", "first", "second"), [
    ("list[int] | list[str]", "[1]", "['one']"),
    ("dict[str, int] | dict[str, str]", "{'key': 1}", "{'key': 'one'}"),
])
def test_literal_runtime_deduplication_does_not_merge_container_layouts(annotation, first, second):
    with pytest.raises(LLVMUnsupported, match="unions cannot distinguish different layouts"):
        transpile_llvm(f'''
            def choose(flag: bool) -> {annotation}:
                return {first} if flag else {second}
            def main() -> str:
                return repr(choose(True))
        ''')


@pytest.mark.parametrize("target", ["str", 'Literal["yes", "no"]'])
def test_optional_literal_refinement_does_not_widen_mutable_items(target):
    with pytest.raises(LLVMUnsupported, match="optional storage requires matching concrete payload types"):
        transpile_llvm(f'''
            from collections.abc import Callable
            from typing import Literal
            def answer() -> list[Literal["yes"]] | None:
                return ["yes"]
            def consume(callback: Callable[[], list[{target}] | None]) -> str:
                return repr(callback())
            def main() -> str:
                return consume(answer)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ['Literal["yes", "no"]', 'Literal["yes"] | Literal["no"]'])
def test_literal_text_helpers_use_normalized_receivers(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from typing import Literal
        def pick(value: int) -> {annotation} | None:
            if value == 0:
                return None
            return "yes" if value == 1 else "no"
        def text(value: {annotation}) -> str:
            return repr((value.replace("e", "E"), value.startswith("y"),
                         value.center(7, "-"), value * 2, 2 * value,
                         value.split("e"), value.partition("e"),
                         value.join(["left", "right"]), value.strip("s")))
        def optional(value: int) -> str:
            selected = pick(value)
            return "missing" if selected is None else text(selected) + selected.removeprefix("n")
        def main() -> str:
            return text("yes") + text("no") + optional(0) + optional(1) + optional(2)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", [
    'Literal["no"]', 'Literal["yes", "no"]', 'Literal["yes"] | Literal["no"]',
])
def test_optional_literal_equality_uses_string_values(tmp_path, optimize, annotation):
    present = '"no"' if annotation == 'Literal["no"]' else '"yes" if value == 1 else "no"'
    comparison = LLVM().assert_matches_python(f'''
        from typing import Literal
        def pick(value: int) -> {annotation} | None:
            if value == 0:
                return None
            return {present}
        def check(value: {annotation} | None) -> str:
            return repr((value == "no", value != "no", value == "yes", "no" == value,
                         "no" != value, value == None, value != None))
        def main() -> str:
            direct: {annotation} | None = "no"
            return check(pick(0)) + check(pick(1)) + check(pick(2)) + check(direct)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ['Literal["1", "2"]', 'Literal["1"] | Literal["2"]'])
def test_literal_runtime_classifiers_share_text_semantics(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from typing import Literal
        from pyjs.native import gc_collect, gc_set_threshold
        def pick(flag: bool) -> {annotation}:
            return "1" if flag else "2"
        def main() -> str:
            gc_set_threshold(1)
            first, second = pick(True), pick(False)
            values = [second, first, second]
            mapping: dict[{annotation}, int] = {{first: 1, second: 2}}
            optional: dict[{annotation} | None, int] = {{None: 0, first: 1}}
            gc_collect()
            ordered = sorted(values)
            return repr((first in "123", second in "1", ",".join(values),
                         ",".join(ordered), ",".join(sorted(set(values))),
                         int(first), float(second), bool(first), first or "fallback",
                         mapping[first], mapping[second], optional[None], optional[first]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
