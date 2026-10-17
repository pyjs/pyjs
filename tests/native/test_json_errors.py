import json

import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_enums_use_their_value_not_the_unsupported_object_path(optimize):
    comparison = LLVM().assert_matches_python('''
        from enum import IntEnum, StrEnum
        import json

        class Code(IntEnum):
            ZERO = 0
            HIGH = 9007199254740993

        class Label(StrEnum):
            EMPTY = ""
            TEXT = "雪"

        def optional(value: Code | None) -> str:
            return json.dumps(value)

        def text(value: Label | None) -> str:
            return json.dumps([value], ensure_ascii=False)

        def main() -> str:
            result = json.dumps((Code.HIGH, Label.TEXT, Code.ZERO, Label.EMPTY))
            result += optional(Code.HIGH) + optional(None)
            return result + text(Label.TEXT) + text(None)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_unsupported_values_are_catchable_and_preserve_first_error(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json

        type JSON = str | float | bytes | list[JSON] | dict[str, JSON] | None

        def render(value: JSON) -> str:
            try:
                return json.dumps(value, allow_nan=False)
            except TypeError:
                return "type error"
            except ValueError:
                return "value error"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        cycle = []
        cycle.append(cycle)
        for value in (
            b"", [b"invalid", float("nan")], [float("nan"), b"invalid"],
            [cycle, b"invalid"], [b"invalid", cycle],
            {"nested": {"value": b"invalid"}},
            {"valid": ["recovered", 2.0, None]},
        ):
            try:
                expected = json.dumps(value, allow_nan=False)
            except TypeError:
                expected = "type error"
            except ValueError:
                expected = "value error"
            assert library.render(value) == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_skipped_entries_do_not_reject_unsupported_values(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json

        def render(values: dict[str | bytes, bytes]) -> str:
            try:
                return json.dumps(values, skipkeys=True)
            except TypeError:
                return "unsupported value"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render({b"skip": b"unsupported"}) == "{}"
        assert library.render({"keep": b"unsupported"}) == "unsupported value"
        assert library.render({}) == "{}"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_key_error_precedes_value_error(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json

        def render(values: dict[float, bytes]) -> str:
            try:
                return json.dumps(values, allow_nan=False)
            except ValueError:
                return "nonfinite key"
            except TypeError:
                return "unsupported value"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render({float("inf"): b"unsupported"}) == "nonfinite key"
        assert library.render({2.0: b"unsupported"}) == "unsupported value"
        assert library.render({}) == "{}"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_rejects_sets_and_objects_without_calling_repr(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json

        class Record:
            def __repr__(self) -> str:
                raise ValueError("JSON must not call repr")

        def main() -> str:
            result = ""
            try:
                json.dumps((1, {2, 3}, "later"))
            except TypeError:
                result += "set"
            try:
                json.dumps(Record())
            except TypeError:
                result += "|object"
            try:
                json.dumps([b"invalid"])
            except TypeError as error:
                assert "not JSON serializable" in str(error)
                result += "|bytes"
            return result + "|" + json.dumps(["recovered"])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_unsupported_object_error_names_the_runtime_subclass(optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        class Record:
            def __init__(self, value: int):
                self.value = value
        class Child(Record):
            pass
        def encode(value: Record) -> str:
            try:
                return json.dumps([value])
            except TypeError as error:
                return str(error)
        def main() -> str:
            return encode(Record(1)) + "|" + encode(Child(2))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("virtual", [False, True])
def test_equal_key_sorting_retains_values_even_when_entries_are_skipped(tmp_path, optimize, nested, virtual):
    declaration = "class Saving(Item):" if virtual else "class Item:"
    base = ("class Item:\n    def __init__(self, rank: int):\n        self.rank = rank\n"
            "    def __lt__(self, other: Item) -> bool: return False") if virtual else ""
    constructor = "Saving" if virtual else "Item"
    left, right = f"{constructor}(rank)", f"{constructor}(rank + 1)"
    if nested:
        left, right = f"[{left}]", f"[{right}]"
    value_type = "list[Item]" if nested else "Item"
    source = f'''
import json
from pyjs.native import gc_collect
class Key:
    def __init__(self, rank: int):
        self.rank = rank
    def __hash__(self) -> int:
        return self.rank
    def __eq__(self, other: Key) -> bool:
        return True
{base}
{declaration}
    def __init__(self, rank: int):
        self.rank = rank
    def __lt__(self, other: Item) -> bool:
        SAVED.append(self)
        SAVED.append(other)
        gc_collect()
        if self.rank < 0:
            raise ValueError("saved value")
        return self.rank < other.rank
SAVED: list[Item] = []
def render(rank: int) -> str:
    values: dict[Key, {value_type}] = {{Key(1): {left}, Key(2): {right}}}
    try:
        result = json.dumps(values, sort_keys=True, skipkeys=True)
    except ValueError:
        result = "failed"
    gc_collect()
    return result + "|" + str([item.rank for item in SAVED])
'''
    namespace = {}
    exec(source, namespace)
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        for rank in (1, -10, 100, 1000):
            assert library.render(rank) == namespace["render"](rank)
            assert heap._Heap.from_address(library._heap).roots is None
    finally:
        library.close()
