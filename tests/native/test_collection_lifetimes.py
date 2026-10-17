import ctypes

import pytest

from pyjs.native.runtime import collector, heap, roots
from pyjs.native.runtime.pointers import free
from pyjs.native.runtime.traces import _Exception
from pyjs.tooling.llvm import LLVM
from tests.native.runtime_support import String, runtime_functions, string


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_coallocated_string_remains_owned(optimize, tmp_path):
    source = '''
        from pyjs.native import gc_collect

        def join(left: str, right: str) -> str:
            return left + right

        def main() -> str:
            value = join("", "")
            gc_collect()
            return value + "after collection"
    '''
    result = LLVM().assert_matches_python(source, optimize=optimize)
    library = ctypes.CDLL(str(LLVM().compile(
        result.native.llvm_ir, tmp_path, shared=True, optimize=optimize,
    )))
    invoke = runtime_functions({
        "pyjs.gc.try.new": collector.new_heap,
        "pyjs.gc.pin": collector.pin,
        "pyjs.gc.unpin": roots.unpin,
        "pyjs.gc.try.collect": collector.try_collect,
        "pyjs.gc.find": collector.find,
        "pyjs.gc.destroy": roots.destroy_heap,
    }, library)
    join = getattr(library, "fn.join")
    join.argtypes = [ctypes.c_void_p] * 5
    join.restype = ctypes.c_void_p
    pointer = invoke("pyjs.gc.try.new")
    state = heap._Heap.from_address(pointer.address)
    empty = string(b"")
    exception = _Exception()
    try:
        address = join(None, pointer.address, ctypes.byref(exception),
                       ctypes.byref(empty), ctypes.byref(empty))
        assert not exception.active
        value = String.from_address(address)
        invoke("pyjs.gc.pin", pointer, address)
        assert value.length == 0 and state.count == 1
        data = value.data
        assert data == address + ctypes.sizeof(String)
        for _ in range(2):
            assert invoke("pyjs.gc.try.collect", pointer)
            assert state.count == 1
            assert invoke("pyjs.gc.find", pointer, address).address != 0
            assert value.data == data
            # Empty coallocated bytes start one-past the header. There is no
            # separate buffer or identity byte to trace or dereference.
            assert invoke("pyjs.gc.find", pointer, data).address == 0
        invoke("pyjs.gc.unpin", pointer, address)
        assert invoke("pyjs.gc.try.collect", pointer)
        assert state.count == 0
    finally:
        invoke("pyjs.gc.destroy", pointer)
        free(pointer)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("count", "threshold", "control"), [
    (5000, 4096, ""),
    (20, 1, ""),
    (20, 1, "gc_pin(parts)"),
    (20, 1, "gc_disable()"),
])
def test_local_string_list_survives_collection(optimize, count, threshold, control):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_set_threshold, gc_pin, gc_disable

        def render_part(index: int) -> str:
            return "<li>" + str(index) + "</li>"

        def main() -> int:
            gc_set_threshold({threshold})
            parts: list[str] = []
            {control}
            for index in range({count}):
                parts.append(render_part(index))
            total = 0
            for part in parts:
                total += len(part)
            return total % 251
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("loop", [False, True])
def test_local_object_string_fields_survive_collection(optimize, loop):
    main = '''
        def main() -> int:
            label = Label(7)
            gc_collect()
            churn = f"<i>{123456}</i>"
            more = f"<i>{654321}</i>"
            return len(label.text) * 100 + len(churn) + len(more)
    '''
    if loop:
        main = '''
        def main() -> int:
            gc_set_threshold(1)
            labels: list[Label] = []
            for index in range(20):
                labels.append(Label(index))
            total = 0
            for label in labels:
                total += len(label.text)
            return total
        '''
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold

        class Label:
            def __init__(self, index: int):
                self.text = f"<b>{index}</b>"

    ''' + main
    LLVM().assert_matches_python(source, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_arena_dom_copies_dynamic_tag_attribute_and_child_text(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import div, tag
        from pyjs.web.html import HTMLElement
        from pyjs.web.ssr import render_html

        def row(index: int) -> HTMLElement:
            return tag("h" + str(1), {"data-" + str(index): str(index)}, str(index))

        def main() -> str:
            gc_set_threshold(1)
            rows: list[HTMLElement] = []
            for index in range(12):
                rows.append(row(index))
            gc_collect()
            return render_html(div(*rows))
    ''', optimize=optimize)
    assert '<h1 data-0="0">0</h1>' in result.native.stdout
    assert '<h1 data-11="11">11</h1>' in result.native.stdout


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_container_truth_and_dictionary_keys(optimize):
    result = LLVM().assert_matches_python('''
        def main() -> int:
            empty_list: list[int] = []
            empty_dict: dict[str, int] = {}
            mapping = {"a": 1, "b": 2}
            seen = {3}
            total = int(bool(mapping)) + int(bool(seen)) + int(bool([1]))
            total += int(bool("value")) + int(bool(1)) + int(bool(1.0))
            total += int(bool(empty_list)) + int(bool(empty_dict))
            total += int(bool()) + int(bool("")) + int(bool(0)) + int(bool(0.0))
            for key in mapping.keys():
                total += mapping[key]
            return total
    ''', optimize=optimize)
    assert result.native.returncode == 9


@pytest.mark.parametrize(("annotation", "expression"), [
    ("set[int]", "set()"),
    ("dict[str, int]", "dict()"),
    ("list[int]", "list()"),
])
def test_typed_empty_collection_constructors(annotation, expression):
    LLVM().assert_matches_python(f'''
        def main() -> int:
            values: {annotation} = {expression}
            return len(values)
    ''')


def test_runtime_empty_tuple_constructor_preserves_dynamic_length():
    LLVM().assert_matches_python('''
        def main() -> int:
            values: tuple[int, ...] = tuple()
            assert not values
            return len(values)
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("initial", "iterable", "mutation"), [
    ("{0: 0}", "values", "values[count + 1] = count"),
    ("{0: 0}", "values.keys()", "values[count + 1] = count"),
    ("{0}", "values", "values.add(count + 1)"),
])
def test_collection_size_change_during_iteration_fails(optimize, initial, iterable, mutation):
    result = LLVM().compare_with_python(f'''
        def main() -> int:
            values = {initial}
            count = 0
            for key in {iterable}:
                if count < 40:
                    {mutation}
                count += 1
            return len(values) + count
    ''', optimize=optimize)
    assert result.python.returncode != 0
    assert "changed size during iteration" in result.python.stderr
    assert result.native.returncode < 0


@pytest.mark.parametrize("optimize", [0, 2])
def test_same_size_updates_and_list_growth_remain_valid(optimize):
    result = LLVM().assert_matches_python('''
        def main() -> int:
            mapping = {1: 2, 2: 3}
            seen = {1, 2}
            for key in mapping:
                mapping[key] = mapping[key] + 10
                for item in seen:
                    seen.add(item)
            values = [1]
            for value in values:
                if value < 3:
                    values.append(value + 1)
            return mapping[1] + mapping[2] + len(values)
    ''', optimize=optimize)
    assert result.native.returncode == 28
