from textwrap import dedent

import pytest

from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("kind, expression", [
    ("tuple", "values[:]"),
    ("tuple", "values[::-1]"),
    ("tuple", "values * 1"),
    ("tuple", "2 * values"),
    ("list", "values.copy()"),
    ("list", "values[:]"),
    ("list", "values * 2"),
    ("list", "2 * values"),
    ("list", "values + values"),
    ("dict", "values.copy()"),
    ("dict", "values | other"),
    *[(kind, expression) for kind in ("set", "frozenset") for expression in (
        "values.copy()", "values | other", "values & other", "values - other",
        "values ^ other", "values.union(other, values)",
        "values.intersection(other, values)", "values.difference(other, other)",
        "values.symmetric_difference(other)",
    )],
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_retained_collection_copies_own_borrowed_members(tmp_path, kind, expression, optimize):
    annotation = {"tuple": "tuple[str, ...]", "dict": "dict[str, list[str]]"}.get(kind, f"{kind}[str]")
    result = "[sorted(value) for value in SAVED]" if kind in {"set", "frozenset"} else "SAVED"
    library = LLVM().compile_library(f"""
        from pyjs.native import gc_collect, gc_set_threshold

        SAVED: list[{annotation}] = []

        def render(values: {annotation}, other: {annotation}) -> str:
            gc_set_threshold(1)
            SAVED.append({expression})
            gc_collect()
            return str({result})
    """, tmp_path, entry_point="render", optimize=optimize)
    expected = []
    try:
        for label in ("one", "two", "three"):
            values = [label, label + "-tail"]
            other = [label, label + "-right"]
            if kind == "tuple":
                values, other = tuple(values), tuple(other)
            elif kind == "dict":
                values = {value: [value + "-nested"] for value in values}
                other = {value: [value + "-replacement"] for value in other}
            elif kind in {"set", "frozenset"}:
                constructor = set if kind == "set" else frozenset
                values = constructor(values if label != "two" else [])
                other = constructor(other if label != "three" else [])
            copied = eval(expression, {}, {"values": values, "other": other})
            expected.append(sorted(copied) if kind in {"set", "frozenset"} else copied)
            assert library.render(values, other) == repr(expected)
    finally:
        library.close()


def test_local_sequence_copies_do_not_force_external_input_promotion():
    with analyze_source(dedent("""
        def main(values: list[str]) -> int:
            copied = values.copy() + values[:]
            return len(copied)
    """), environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        assert analysis.entry_point.ir.lifetime.external_parameters == set()
        assert analysis.entry_point.ir.lifetime.returned_parameters == set()


@pytest.mark.parametrize("expression, retained", [
    ("left.copy()", {"left"}),
    ("left - right", {"left"}),
    ("left.difference(right)", {"left"}),
    ("left.intersection(right)", {"left", "right"}),
])
def test_set_result_lifetimes_retain_only_possible_member_sources(expression, retained):
    with analyze_source(dedent(f"""
        SAVED: list[set[str]] = []

        def main(left: set[str], right: set[str]) -> int:
            SAVED.append({expression})
            return len(SAVED)
    """), environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        assert analysis.entry_point.ir.lifetime.external_parameters == retained
