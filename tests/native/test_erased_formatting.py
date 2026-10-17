import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations, run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("value", ["2.5", "True", "255", "number"])
def test_annotated_scalar_box_registers_its_formatting_type(tmp_path, optimize, value):
    # Compile each kind independently: boxing it elsewhere must not accidentally
    # populate the dispatch table and hide the annotated-assignment path.
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            number = 4
            value: object = {value}
            values: list[object] = [value]
            gc_collect()
            return str(value) + "|" + repr(value) + "|" + repr(values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_custom_specs_are_independent_of_unrelated_boxed_scalars(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Label:
            def __format__(self, spec: str) -> str:
                return "label:" + spec
        def custom(value: object) -> str:
            try:
                return format(value, "abc")
            except ValueError:
                return "invalid"
        def other(value: object) -> str:
            return str(value)
        def align(value: object) -> str:
            return f"{value:>6}|{value:08}|{value:*^12}"
        def main() -> str:
            return (custom(Label()) + other(1) + custom(1) + custom(1.5) + custom("text")
                    + align(1) + align(1.5) + align(-1.5) + align(1.0) + align(-0.0))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_erased_rendering_shares_one_growing_output_buffer(tmp_path, optimize):
    source = '''
        from tests.native.allocation_support import arm, remaining
        def wrap(value: object) -> object:
            return [value]
        def main() -> int:
            value: object = "leaf"
            for index in range(80):
                value = wrap(value)
            arm(1000)
            rendered = repr(value)
            allocations = 1000 - remaining()
            arm(0)
            assert rendered == "[" * 80 + "'leaf'" + "]" * 80
            # Output growth and the final string allocate; nested container
            # dispatch must not allocate an intermediate string per level.
            assert 0 < allocations < 20
            return 0
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_formatting_preserves_concrete_nested_layouts(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def render(value: object) -> str:
            gc_collect()
            return str(value) + " / " + repr(value)
        def main() -> str:
            gc_set_threshold(1)
            nested: list[object] = [1, "two", [3, 4]]
            values: list[object] = [None, False, True, 42, -7, 2.5, "café\\n'",
                                    b"bytes\\x00", [1, 2], ["one", "two"],
                                    [[1], [2, 3]], (1, "two"), (3.5, False),
                                    {1: [2, 3]}, {"x": "y"}, {4}, frozenset({5}), nested,
                                    list[int](), dict[str, int](), set[int](), frozenset[int](), ()]
            return "\\n".join([render(value) for value in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_format_specs_use_concrete_protocols_and_error_types(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Label:
            def __format__(self, spec: str) -> str:
                gc_collect()
                return "label[" + spec + "]"
            def __str__(self) -> str: return "str"
            def __repr__(self) -> str: return "repr"
        def render(value: object) -> str:
            output = f"{value}|{value!s}|{value!r}|"
            try:
                output += format(value, "04d")
            except TypeError:
                output += "TypeError"
            except ValueError:
                output += "ValueError"
            return output
        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [Label(), 7, True, 1.5, "text", None, [1, 2]]
            return "\\n".join([render(value) for value in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_numeric_specs_retain_float_runtime_dependencies(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def render(value: object) -> str:
            return format(value, ".2f") + f"|{value:.1%}"
        def main() -> str:
            return render(1.25) + render(3) + render(True)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_represented_containers_and_string_consumers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8, int64, float32
        from pyjs.native import gc_collect, gc_set_threshold
        def render(value: object) -> str:
            gc_collect()
            return f"{value!r}|{value!s}|{value!a}"
        def main() -> str:
            gc_set_threshold(1)
            small: list[int8] = [int8(128), int8(7)]
            rounded: list[float32] = [float32(16777217), float32(1.5)]
            nested = {"items": small}
            boxed: object = nested
            output = render(small) + render(rounded) + render("é中") + render(range(1, 8, 2))
            output += render((int64(9007199254740993), int8(-1)))
            output += render({int64(9007199254740993): float32(2.5)})
            small.append(int8(-128))
            output += render(boxed)
            nested.clear()
            gc_collect()
            return output + render(boxed) + render((int64(-2**63), int64(2**63 - 1)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_mutating_callbacks_and_recursive_mapping(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self): self.values: list[object] = []
            def __repr__(self) -> str:
                self.values.clear()
                gc_collect()
                return "item"
        def render(value: object) -> str: return repr(value)
        def main() -> str:
            gc_set_threshold(1)
            item = Item()
            item.values.append(item)
            item.values.append("discarded")
            mapping: dict[str, object] = {}
            mapping['self'] = mapping
            return render(item.values) + render(item.values) + render(mapping)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_formatter_allocation_failure_restores_all_nested_scopes(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_count, gc_set_threshold
        from tests.native.allocation_support import arm
        class Plain: pass
        class Item:
            def __repr__(self) -> str:
                gc_collect()
                return "Item(" + "x" * 100 + ")"
        def render(value: object) -> str: return repr(value)
        def main() -> int:
            gc_set_threshold(1)
            values: list[object] = [Item(), Plain(), "é" * 100, [1, 2]]
            values.append(values)
            expected = render(values)
            failures = 0
            for attempt in range(1, 100):
                complete = False
                result = "unchanged"
                arm(attempt)
                try:
                    result = render(values)
                    arm(0)
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert render(values) == expected and gc_count() == 0
                if complete:
                    assert result == expected and failures > 0
                    return 0
                assert result == "unchanged"
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_fstrings_dunders_and_print_retain_distinct_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Label:
            def __str__(self) -> str:
                gc_collect()
                return "label"
            def __repr__(self) -> str:
                gc_collect()
                return "Label()"
        class Child(Label):
            def __str__(self) -> str:
                gc_collect()
                return "child"
        def render(value: object) -> str:
            print(value, sep="|", end=";")
            return f"{value}|{value!s}|{value!r}|" + value.__str__() + value.__repr__()
        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [Label(), Child(), "quoted'", 1, False, [1, 2], 2.5]
            return "\\n".join([render(value) for value in values])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_formatter_failure_trace_names_authored_calls_not_helpers(tmp_path, optimize):
    source = '''from tests.native.allocation_support import arm
def render(value: object) -> str:
    return repr(value)
def main() -> int:
    value: object = ["text"]
    arm(1)
    return len(render(value))
'''
    llvm_ir = transpile_llvm(source, filename="erased_failure.py")
    executable = LLVM().compile(_fail_allocations(llvm_ir, False), tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        '  File "erased_failure.py", line 7, in main\n'
        '  File "erased_failure.py", line 3, in render\n'
        'MemoryError: native text output allocation failed\n'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_cycles_and_callback_failures_share_formatter_cleanup(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self, value: int): self.value = value
            def __repr__(self) -> str:
                gc_collect()
                if self.value == 9: raise ValueError("repr")
                return "Item(" + str(self.value) + ")"
        class Child(Item):
            def __str__(self) -> str:
                gc_collect()
                return "child"
        def render(value: object) -> str:
            return str(value) + ":" + repr(value)
        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = []
            values.append(values)
            output = [render(values), render(Item(1)), render(Child(2))]
            items: list[Item] = [Item(3), Child(4)]
            output.append(render(items))
            try:
                output.append(render([Item(9)]))
            except ValueError as error:
                output.append(str(error))
            gc_collect()
            output.append(render([Item(5)]))
            return "\\n".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
