import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("arguments", ["*choose(flag, values, events)",
                                     '"before", *choose(flag, values, events), "after"'])
def test_union_star_sources_keep_keyword_mutation_and_evaluation_order(tmp_path, optimize, arguments):
    result = LLVM().assert_matches_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
def choose(flag: bool, values: list[str], events: list[str]) -> list[str] | tuple[str]:
    events.append("choose")
    return values if flag else ("tuple",)
def grow(values: list[str], events: list[str]) -> str:
    events.append("grow")
    gc_collect()
    values.append("new")
    return "keyword"
def consume(*values: str, suffix: str) -> str:
    gc_collect()
    return str(values) + suffix
def main() -> str:
    gc_set_threshold(1)
    results: list[str] = []
    for flag in [False, True]:
        values = ["old"]
        events: list[str] = []
        results.append(consume({arguments}, suffix=grow(values, events)))
        results.append(str(events))
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_star_arms_keep_independent_binding_positions_and_numeric_layouts(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.native import gc_collect
def choose(flag: bool) -> tuple[int8, int8] | list[int8]:
    return (int8(127), int8(2)) if flag else [int8(127)]
def consume(first: int8, second: int8, *rest: int8) -> str:
    gc_collect()
    return str((first + second, rest))
def main() -> str:
    results: list[str] = []
    for flag in [False, True]:
        results.append(consume(*choose(flag), int8(3), int8(4)))
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_star_binding_failures_preserve_sources_and_allow_retry(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def choose(flag: bool, values: list[int], events: list[str]) -> tuple[int, int] | list[int]:
    events.append("choose")
    return (10, 20) if flag else values
def keywords(duplicate: bool, events: list[str]) -> dict[str, int]:
    events.append("keywords")
    gc_collect()
    return {"first": 99} if duplicate else {}
def consume(first: int, second: int = 2) -> int:
    gc_collect()
    return first + second
def main() -> str:
    gc_set_threshold(1)
    results: list[str] = []
    for flag in [False, True]:
        for duplicate in [False, True]:
            for count in range(4):
                values = list(range(count))
                events: list[str] = []
                try:
                    results.append(str(consume(*choose(flag, values, events), **keywords(duplicate, events))))
                except TypeError:
                    results.append("TypeError")
                gc_collect()
                results.append(str(values))
                results.append(str(events))
                results.append(str(consume(*choose(flag, [3, 4], events))))
    return str(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
