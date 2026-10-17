"""Recursive value construction/traversal, independently of recursive host IO."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm_module
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    RECURSIVE_EQUALITY_CONTRACT,
    RECURSIVE_OPTIONAL_CONTRACT,
    RECURSIVE_TREE_CONTRACT,
    RECURSIVE_UNION_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_aliases_survive_conditional_and_literal_dom_scan(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
type Tree = int | list[Tree]
def pick(flag: bool, a: Tree, b: Tree) -> Tree:
    return a if flag else b
def wrap(value: Tree) -> str:
    items = [value]
    gc_collect()
    return repr(items)
def main() -> str:
    return repr(pick(True, [1, [2]], 3)) + wrap([1, [2]])
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_shared_recursive_tree_contract(tmp_path):
    result = LLVM().run_source(RECURSIVE_TREE_CONTRACT.source, directory=tmp_path,
                               sanitizers=("address", "undefined"))
    assert result.returncode == 0, RECURSIVE_TREE_CONTRACT.failure(result.returncode)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [RECURSIVE_UNION_CONTRACT, RECURSIVE_OPTIONAL_CONTRACT])
def test_shared_recursive_union_contract(tmp_path, optimize, contract):
    result = LLVM().run_source(contract.source, directory=tmp_path,
                               optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0, contract.failure(result.returncode)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_recursive_self_append_survives_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Nest = list[Nest | None]
        def main() -> str:
            gc_set_threshold(1)
            root: Nest = [None]
            root.append(root)
            gc_collect()
            return repr(root) + str(root) + ascii(root) + format(root) + f"{root!r:>20}"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_container_values_keep_aliases_under_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Tree = str | int | list[Tree] | dict[str, Tree] | None

        def count(value: Tree) -> int:
            gc_collect()
            if value is None:
                return 0
            if isinstance(value, int):
                return int(value)
            if isinstance(value, str):
                return len(value)
            total = 0
            if isinstance(value, list):
                for item in value:
                    total += count(item)
            else:
                for item in value.values():
                    total += count(item)
            return total

        def main() -> str:
            gc_set_threshold(1)
            child: Tree = [1, "three", None]
            root: Tree = {"first": child, "second": [child, 7]}
            saved: list[Tree] = [root]
            first = count(root)
            if isinstance(child, list):
                child.append(11)
            root = None
            gc_collect()
            return str((first, count(saved[0])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_optional_tuple_chain(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        type Chain = tuple[int, Chain] | None

        def total(chain: Chain) -> int:
            result = 0
            while chain is not None:
                result += chain[0]
                chain = chain[1]
                gc_collect()
            return result

        def main() -> int:
            chain: Chain = None
            for item in range(12):
                chain = (item, chain)
            return total(chain)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_recursive_container_retains_a_runtime_cycle(tmp_path):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Tree = int | list[Tree]

        def main() -> int:
            gc_set_threshold(1)
            root: Tree = []
            if not isinstance(root, list):
                return -1
            root.append(root)
            saved = root[0]
            root = []
            gc_collect()
            if isinstance(saved, list):
                child = saved[0]
                if isinstance(child, list):
                    return len(child)
            return -2
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_recursive_repr_output_is_supported():
    LLVM().assert_matches_python('''
        type Tree = int | list[Tree]
        def main() -> str:
            value: Tree = [1, [2]]
            return repr(value)
    ''')


def test_recursive_json_output_is_supported():
    LLVM().assert_matches_python('''
        import json
        type Tree = int | list[Tree]
        def main() -> str:
            value: Tree = [1, [2]]
            return json.dumps(value)
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("erased", [False, True])
def test_recursive_comparisons_and_membership(optimize, erased):
    source = RECURSIVE_EQUALITY_CONTRACT.source
    if erased:
        source = source.replace("a: Tree, b: Tree", "a: object, b: object")
    result = LLVM().run_source(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0, RECURSIVE_EQUALITY_CONTRACT.failure(result.returncode)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind", ["list", "dict"])
@pytest.mark.parametrize("erased", [False, True])
def test_recursive_comparison_cycles_raise_and_recover(kind, optimize, erased):
    annotation = "list[Tree]" if kind == "list" else "dict[str, Tree]"
    empty = "[]" if kind == "list" else "{}"
    link = "left.append(left); right.append(right)" if kind == "list" else "left['self'] = left; right['self'] = right"
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        type Tree = int | {annotation}

        def compare(left: Tree, right: Tree) -> str:
            try:
                return str(left == right)
            except RecursionError:
                return 'recursive'

        def main() -> str:
            gc_set_threshold(1)
            left: {annotation} = {empty}
            right: {annotation} = {empty}
            {link}
            results: list[str] = []
            for attempt in range(3):
                results.append(compare(left, right))
                gc_collect()
                results.append(compare(left, left))
                results.append(compare(1, 1))
            return '|'.join(results)
    '''.replace("left: Tree, right: Tree", "left: object, right: object" if erased else "left: Tree, right: Tree"),
        optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_comparison_callbacks_keep_roots_dispatch_and_cleanup(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        EVENTS: list[str] = []

        class Box:
            def __init__(self, value: int):
                self.value = value
            def __eq__(self, other: object) -> bool:
                EVENTS.append('equal')
                gc_collect()
                if self.value < 0:
                    raise ValueError('comparison')
                return isinstance(other, Box) and self.value == other.value
            def __ne__(self, other: object) -> bool:
                EVENTS.append('not equal')
                gc_collect()
                return False

        type Tree = Box | list[Tree] | None

        def compare(left: Tree, right: Tree) -> str:
            EVENTS.clear()
            try:
                result = str((left == right, left != right, left in [right]))
            except ValueError:
                result = 'caught'
            gc_collect()
            return result + str(EVENTS)

        def main() -> str:
            gc_set_threshold(1)
            shared: Tree = Box(1)
            return '|'.join([compare(shared, shared), compare(Box(1), Box(2)),
                             compare([Box(1), [Box(2)]], [Box(1), [Box(2)]]),
                             compare([Box(-1)], [Box(2)]),
                             compare([Box(3)], [Box(3)]), compare(None, Box(1))])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_inner_optional_union(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        type Tree = int | list[Tree | None]
        def count(value: Tree) -> int:
            if isinstance(value, int):
                return int(value)
            result = 0
            for item in value:
                gc_collect()
                if item is not None:
                    result += count(item)
            return result
        def main() -> int:
            value: Tree = [1, None, [2, None]]
            return count(value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_union_inclusion_ignores_local_declaration_order(tmp_path, reverse, optimize):
    declarations = ["a: A = [1, None]", "b: B = None"]
    if reverse:
        declarations.reverse()
    source = '''
from pyjs.native import gc_collect
type A = int | list[B]
type B = A | None
def use(value: B) -> int:
    gc_collect()
    if value is None:
        return 0
    if isinstance(value, int):
        return int(value)
    return len(value)
def main() -> str:
'''
    source += "".join(f"    {line}\n" for line in declarations)
    source += "    return str((use(a), use(b)))\n"
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                               sanitizers=("address", "undefined"))
    assert not comparison.native.stderr
