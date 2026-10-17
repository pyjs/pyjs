import pytest

from pyjs.native.llvm import LLVMUnsupported
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_union_keys_have_matching_hashes_after_promotion_and_mutation(tmp_path, optimize):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
type Key = str | bytes | int | float | bool | None
SAVED: list[dict[Key, str]] = []
def render(values: dict[Key, str], members: set[Key]) -> str:
    gc_set_threshold(1)
    SAVED.append(values)
    gc_collect()
    result: list[str] = []
    for mapping in SAVED:
        for key in mapping:
            result.append(mapping[key])
    for key in values:
        assert key in members
    copied = values.copy()
    copied["new"] = "inserted"
    assert copied.pop("new") == "inserted"
    members.add("new")
    members.discard("new")
    gc_collect()
    return str((result, len(copied), len(members)))
'''
    namespace = {}
    exec(source, namespace)
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        requests = [
            {"é": "text", b"\xc3\xa9\0": "bytes", None: "null", 1: "one", 2.5: "fraction"},
            {False: "false", True: "true", 9007199254740993: "exact", float("inf"): "infinite"},
            {},
            {"last": "after empty", -1: "negative", -0.0: "zero"},
        ]
        for values in requests:
            expected = namespace["render"](values.copy(), set(values))
            assert library.render(values, set(values)) == expected
            assert "new" not in values
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_union_key_normalization_merges_first_position_and_last_value(tmp_path, optimize):
    library = LLVM().compile_library('''
from pyjs import int8
from pyjs.native import gc_collect
def render(values: dict[int8 | str, str], members: set[int8 | str]) -> str:
    gc_collect()
    result = str(values) + "|" + str(len(members))
    for key in values:
        assert key in members
        result += "|" + values[key]
    return result
''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render({1: "first", "1": "text", 257: "last"}, {1, "1", 257}) == (
            "{1: 'last', '1': 'text'}|2|last|text")
    finally:
        library.close()


@pytest.mark.parametrize("annotation", ["dict[tuple[int, int], str]", "set[tuple[int, int]]"])
def test_host_non_scalar_hash_keys_keep_explicit_initialization_boundary(tmp_path, annotation):
    with pytest.raises(LLVMUnsupported, match="reference-key inputs require native hash initialization"):
        LLVM().compile_library(f"def render(value: {annotation}) -> str:\n    return str(value)\n",
                               tmp_path, entry_point="render")
