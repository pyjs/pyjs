"""Closed builtin unions keep their runtime kind across the host boundary."""

import json
import sys

import pytest

from pyjs.native.llvm import transpile_llvm_module
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_inputs_render_finite_json_and_recover_from_invalid_values(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json
        from pyjs.native import gc_collect

        def render(value: int | float | str | list[int | str] | dict[str, int | str] | None) -> str:
            gc_collect()
            return json.dumps(value, ensure_ascii=False)
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        for value in (None, True, False, -2**63, 2**63 - 1, -0.0, 1.5,
                      float("inf"), float("nan"), "café 🚢", [], [1, "two", True],
                      {}, {"a": 1, "b": "é"}):
            assert library.render(value) == json.dumps(value, ensure_ascii=False)
        with pytest.raises(TypeError, match="must match"):
            library.render([1.5])
        with pytest.raises(OverflowError, match="signed 64-bit"):
            library.render(2**63)
        with pytest.raises(TypeError, match="must match"):
            library.render((1,))
        assert library.render(["recovered"]) == '["recovered"]'
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("raw", [False, True])
def test_union_inputs_preserve_aliases_and_retained_owned_payloads(tmp_path, optimize, raw):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold

        SAVED: list[list[str] | int] = []

        class Box:
            def __init__(self, value: list[str] | int):
                self.value = value

        def render(value: list[str] | int, plain: list[str], box: Box) -> str:
            gc_set_threshold(1)
            same = False
            if isinstance(value, list):
                same = value is plain and box.value is value
                value.append("native")
            SAVED.append(value)
            gc_collect()
            return str((same, SAVED))
    ''', tmp_path, entry_point="render", optimize=optimize)
    if raw:
        entry = library._library.pyjs_render_to_fd
        entry.argtypes, entry.restype = library._render.argtypes, library._render.restype
        library._render = entry
    try:
        shared = ["host"]
        assert library.render(shared, shared, {"value": shared}) == "(True, [['host', 'native']])"
        assert shared == ["host"]
        shared[0] = "changed"
        assert library.render(42, shared, {"value": 42}) == "(False, [['host', 'native'], 42])"
        assert library.render(shared, shared, {"value": shared}) == "(True, [['host', 'native'], 42, ['changed', 'native']])"
    finally:
        library.close()


def test_union_reference_kinds_and_direct_descriptor_entry(tmp_path):
    library = LLVM().compile_library('''
        from pyjs.web.domx import div
        from pyjs.web.ssr import write_html_fd
        from pyjs.native import gc_collect

        def render(value: bytes | tuple[int, str] | set[int] | frozenset[int], descriptor: int) -> int:
            gc_collect()
            return write_html_fd(div(repr(value)), descriptor)
    ''', tmp_path, entry_point="render", direct=True)
    try:
        for value in (b"\x00bytes", (3, "three"), {1}, frozenset({2}), set(), frozenset()):
            assert library.render(value) == "<div>" + repr(value) + "</div>"
    finally:
        library.close()


def test_union_inputs_do_not_promote_an_integer_to_a_float_arm(tmp_path):
    library = LLVM().compile_library('''
        def render(value: float | str) -> str:
            return repr(value)
    ''', tmp_path, entry_point="render")
    try:
        assert library.render(1.0) == "1.0"
        assert library.render("text") == "'text'"
        for value in (1, True):
            with pytest.raises(TypeError, match="must match"):
                library.render(value)
    finally:
        library.close()


def test_union_input_errors_use_public_container_names(tmp_path):
    library = LLVM().compile_library('''
        def render(value: set[int] | list[int]) -> str:
            return repr(value)
    ''', tmp_path, entry_point="render")
    try:
        with pytest.raises(TypeError, match=r"^value must match set \| list, not frozenset$"):
            library.render(frozenset({1}))
        assert library.render([1]) == "[1]"
    finally:
        library.close()


@pytest.mark.parametrize("annotation", ["int | float", "int | float | None", "int | None", "int", "int | str"])
def test_only_reference_bearing_inputs_need_promotion(annotation):
    module = transpile_llvm_module(f'''
        from pyjs.native import gc_collect
        def render(value: {annotation}) -> str:
            gc_collect()
            return repr(value)
    ''', target="library", entry_point="render")
    # The full module contains a large GC/formatting runtime. Pin just the
    # expensive entry operations, with a reference-union positive control.
    reference = "str" in annotation
    assert ("call ptr @pyjs.input.try.copy" in module.llvm_ir) is reference
    assert ("call ptr @pyjs.input.try.ownership" in module.llvm_ir) is reference


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("nested", [False, True])
def test_scalar_union_inputs_and_nested_slots_skip_copy_but_keep_values(tmp_path, optimize, nested):
    parameters = ", items: list[int | float], pair: tuple[int | float, int]" if nested else ""
    result = "(value, items, pair)" if nested else "value"
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect
        def render(value: int | float | None{parameters}) -> str:
            gc_collect()
            return repr({result})
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        for value in (None, True, -2**63, 2**63 - 1, -0.0, float("inf"), float("nan")):
            items, pair = [1, 2.5, True], (-0.0, 7)
            arguments = (value, items, pair) if nested else (value,)
            assert library.render(*arguments) == repr(arguments if nested else value)
    finally:
        library.close()


def test_union_inputs_normalize_declared_portable_scalars(tmp_path):
    from pyjs import float32

    library = LLVM().compile_library('''
        from pyjs import int8, float32
        def render(integer: int8 | str, floating: float32 | str) -> str:
            return str((integer, floating))
    ''', tmp_path, entry_point="render")
    try:
        assert library.render(257, 0.1) == repr((1, float32(0.1)))
        assert library.render("integer", "floating") == "('integer', 'floating')"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_application_union_inputs_preserve_concrete_aliases(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect
        class A:
            pass
        class B:
            pass
        def render(value: A | B, plain: A) -> str:
            gc_collect()
            return str((isinstance(value, A), value is plain))
    ''', tmp_path, entry_point="render", module_name="empty_application_inputs", optimize=optimize)
    module = sys.modules["empty_application_inputs"]
    try:
        first, second = module.A(), module.B()
        for value in (first, second, module.A()):
            assert library.render(value, first) == module.render(value, first)
        # Concrete headerless records still accept structural inputs; a union
        # needs nominal identity to choose its arm without guessing by fields.
        assert library.render(first, {}) == "(True, False)"
        with pytest.raises(TypeError, match="value must match A.*B"):
            library.render({}, first)
    finally:
        library.close()
