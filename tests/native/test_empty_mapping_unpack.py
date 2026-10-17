import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_unpack_uses_sibling_storage_without_copying_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def mapping(events: list[str]) -> dict[str, list[int]]:
            events.append("mapping")
            gc_collect()
            return {"filled": [1, 2]}
        def item(events: list[str]) -> list[int]:
            events.append("item")
            return [3]
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            original = mapping(events)
            combined = {"before": [], **{}, **original,
                        **{}, "after": item(events), **{}}
            combined["before"].append(4)
            combined["filled"].append(5)
            gc_collect()
            return str((combined, original, events,
                        combined["filled"] is original["filled"]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("body,name", [
    ("values = {**{}}; return len(values)", "values"),
    ("empty = {}; values = {**empty, 'x': 1}; return len(values)", "empty"),
])
def test_empty_unpack_does_not_guess_storage_or_retype_aliases(body, name):
    with pytest.raises(CompilationError, match=f"Type of '{name}' cannot be inferred"):
        transpile_llvm(f"def main() -> int:\n    {body}\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_unpack_preserves_nested_portable_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        import json
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect
        def main() -> str:
            small = {**{}, "first": [], "filled": [int8(120)], **{}}
            wide = {**{}, "first": [], "filled": [int64(9007199254740993)]}
            floats = {"value": float32(0.1), **{}}
            small["first"].append(int8(130))
            wide["first"].append(int64(9007199254740995))
            gc_collect()
            return json.dumps((small, wide, floats))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
