import subprocess

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import _fail_allocations, run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_union_value_survives_key_repr_deletion_and_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Value = int | list[Value]

        class Key:
            def __init__(self):
                self.owner: dict[Key, Value] = {}

            def __hash__(self) -> int:
                return 1

            def __repr__(self) -> str:
                self.owner.clear()
                gc_collect()
                return "key"

        def populate(key: Key) -> None:
            # Construct outside the rendering frame: no stale local/temporary
            # root may accidentally keep the captured dictionary value alive.
            key.owner[key] = [[12345, 67890]]

        def main() -> str:
            gc_set_threshold(1)
            key = Key()
            populate(key)
            return repr(key.owner) + repr(key.owner)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_format_consumers_and_optional_tuple(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        type Chain = tuple[str, Chain] | None

        def main() -> str:
            value: Chain = None
            for item in ["café", "\\n'", "🙂"]:
                value = (item, value)
            print(value)
            return (str(value) + repr(value) + ascii(value) + format(value)
                    + f"{value!s}|{value!r}|{value!a}")
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_repr_depth_failure_unwinds_and_preserves_cycle_detection(tmp_path, optimize):
    # Native formatting has a checked 1000-container/protocol-frame budget,
    # not CPython's interpreter recursion limit. Do not raise that host limit.
    result = LLVM().run_source('''
        from pyjs.native import gc_collect
        type Tree = int | list[Tree]

        def main() -> int:
            value: Tree = 1
            for index in range(1000):
                value = [value]
            if len(repr(value)) != 2001:
                return 1
            value = [value]
            caught = False
            try:
                repr(value)
            except RecursionError:
                caught = True
            if not caught:
                return 2
            gc_collect()
            cycle: list[Tree] = []
            cycle.append(cycle)
            if repr(cycle) != "[[...]]" or repr([1, 2]) != "[1, 2]":
                return 3
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0, result.stderr
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_alias_repr_matches_python_for_shared_and_cyclic_values(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        type Value = str | int | float | bool | list[Value] | dict[str, Value] | None

        def render(value: Value) -> str:
            return repr(value) + "|" + str(value)

        def main() -> int:
            gc_set_threshold(1)
            for value in ["quoted'\\n✓", 7, 2.5, True, None]:
                print(render(value))
            values: list[Value] = ["one", 2, {"three": 3}]
            print(render(values))
            print(repr([values, values]))
            values.append(values)
            gc_collect()
            print(render(values))
            mapping: dict[str, Value] = {"left": values}
            mapping["self"] = mapping
            gc_collect()
            print(render(mapping))
            print(f"{mapping!r}")
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_single_container_and_mutually_recursive_alias_repr(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        type Node = list[Node]
        type Tree = str | list[Branch]
        type Branch = int | dict[str, Tree]

        def render_node(value: Node) -> str:
            return repr(value)

        def render_tree(value: Tree) -> str:
            return str(value) + "|" + repr(value)

        def main() -> int:
            gc_set_threshold(1)
            node: Node = [[]]
            print(render_node(node))
            node.append(node)
            gc_collect()
            print(render_node(node))
            tree: Tree = [1, {"label": "hello'✓"}]
            branch: Branch = {"left": tree, "right": tree}
            print(repr(branch))
            if isinstance(tree, list):
                tree.append(branch)
            gc_collect()
            print(render_tree(tree))
            print(render_tree("plain'✓"))
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_alias_callbacks_collect_and_recover_from_exceptions(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        type Value = Item | list[Value]

        class Item:
            def __init__(self):
                self.owner: list[Value] = []
                self.fail = True

            def __repr__(self) -> str:
                gc_collect()
                if self.fail:
                    raise ValueError("broken")
                return repr(self.owner)

        def main() -> int:
            gc_set_threshold(1)
            item = Item()
            nested: list[Value] = [[item]]
            item.owner = nested
            for step in range(4):
                saved = "unchanged"
                try:
                    saved = repr(nested)
                except ValueError as error:
                    gc_collect()
                    print(str(error), saved)
                item.fail = False
                print(repr(nested))
                print(repr([nested, nested]))
                item.fail = True
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_repr_retains_borrowed_cycles_across_library_calls(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold

        type Value = str | int | list[Value] | dict[str, Value] | None
        SAVED: list[Value] = []

        def render(value: Value) -> str:
            gc_set_threshold(1)
            SAVED.append(value)
            gc_collect()
            return repr(SAVED) + "|" + str(value)
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        cycle = ["quoted'✓", None]
        cycle.append(cycle)
        mapping = {"shared": cycle}
        mapping["self"] = mapping
        saved = []
        for value in (cycle, mapping, "later", 7, None):
            saved.append(value)
            assert library.render(value) == repr(saved) + "|" + str(value)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_repr_allocation_failures_unwind_helpers_and_allow_retry(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect, gc_count
        from tests.native.allocation_support import arm, remaining

        type Value = str | int | list[Value] | dict[str, Value] | None

        def render(value: Value) -> str:
            return repr(value) + "|" + str(value)

        def main() -> int:
            values: list[Value] = ["quoted'✓", {"child": [1, None]}]
            values.append(values)
            expected = render(values)
            arm(1000)
            probe = render(values)
            stages = 1000 - remaining()
            arm(0)
            if probe != expected or stages < 10:
                return 1
            failure = 1
            while failure <= stages:
                result = "unchanged"
                caught = False
                arm(failure)
                try:
                    result = render(values)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result != "unchanged" or gc_count() != 0:
                    return 2
                if render(values) != expected:
                    return 3
                failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_repr_helper_reports_current_call_site(tmp_path, optimize):
    source = '''from pyjs import llvm

type Node = list[Node]

@llvm.inline("store i64 {value}, ptr @test.remaining")
def arm(value: int) -> None:
    pass

def first(value: Node) -> str:
    return repr(value)

def second(value: Node) -> str:
    return repr(value)

def main() -> int:
    value: Node = [[[]]]
    first(value)
    arm(3)
    second(value)
    return 0
'''
    emitted = transpile_llvm(source, filename="recursive_repr.py")
    managed = "define ptr @pyjs.gc.new()" in emitted
    executable = LLVM().compile(_fail_allocations(emitted, managed), tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        '  File "recursive_repr.py", line 19, in main\n'
        '  File "recursive_repr.py", line 13, in second\n'
        'MemoryError: native text output allocation failed\n'
    )
