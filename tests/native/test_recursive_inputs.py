"""Recursive copy-in schemas preserve graph identity, ownership and failures."""

import itertools
import sys

import pytest

from pyjs.analysis.source import create_module
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm_module
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_host_tree_traversal_and_failed_input_recovery(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect
        type Tree = int | str | list[Tree] | dict[str, Tree] | None

        def count(value: Tree) -> int:
            gc_collect()
            if value is None:
                return 0
            if isinstance(value, int):
                return int(value)
            if isinstance(value, str):
                return len(value)
            result = 0
            if isinstance(value, list):
                for child in value:
                    result += count(child)
            else:
                for child in value.values():
                    result += count(child)
            return result

        def render(value: Tree) -> str:
            return str(count(value))
    '''
    shared = [7, "café🚢", None]
    value = {"left": shared, "right": [shared, 3]}
    comparison = LLVM().compare_library_with_python(source, value, directory=tmp_path,
                                                     entry_point="render", optimize=optimize)
    library = comparison.library
    try:
        assert comparison.matches
        for invalid in ({"bad": [1.5]}, [2**63], [object()]):
            with pytest.raises((TypeError, OverflowError)):
                library.render(invalid)
            assert library.render(value) == comparison.python
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("raw", [False, True])
def test_host_cycles_shared_views_and_retained_native_graph(tmp_path, optimize, raw):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Tree = int | list[Tree] | dict[str, Tree]
        SAVED: list[Tree] = []

        def render(value: Tree, shared: list[Tree]) -> str:
            gc_set_threshold(1)
            same = False
            cyclic = False
            if isinstance(value, list):
                same = value is shared
                child = value[0]
                if isinstance(child, list):
                    cyclic = child is value
                value.append(9)
            elif isinstance(value, dict):
                child = value['self']
                if isinstance(child, dict):
                    cyclic = child is value
                other = value['shared']
                if isinstance(other, list):
                    same = other is shared
                shared.append(11)
            SAVED.append(value)
            gc_collect()
            previous = SAVED[0]
            length = len(previous) if isinstance(previous, list) else -1
            return str((same, cyclic, len(shared), length, len(SAVED)))
    ''', tmp_path, entry_point="render", optimize=optimize)
    if raw:
        entry = library._library.pyjs_render_to_fd
        entry.argtypes, entry.restype = library._render.argtypes, library._render.restype
        library._render = entry
    try:
        cycle = []
        cycle.append(cycle)
        assert library.render(cycle, cycle) == "(True, True, 2, 2, 1)"
        assert len(cycle) == 1 and cycle[0] is cycle
        cycle.clear()  # Retained native cycle is independent of the host.
        shared = [1]
        mapping = {"shared": shared}
        mapping["self"] = mapping
        assert library.render(mapping, shared) == "(True, True, 2, 2, 2)"
        assert shared == [1] and mapping["self"] is mapping
        bad = []
        bad.extend([bad, None])  # Valid cyclic backedge, then invalid child.
        with pytest.raises(TypeError, match="must match"):
            library.render(bad, [])
        deep = 0
        for _ in range(2000):
            deep = [deep]
        with pytest.raises(RecursionError):
            library.render(deep, [])
        assert library.render(3, []) == "(False, False, 0, 2, 3)"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_optional_tuple_host_chain(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect
        type Chain = tuple[int, Chain] | None

        def render(value: Chain) -> str:
            result = 0
            while value is not None:
                result += value[0]
                value = value[1]
                gc_collect()
            return str(result)
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render(None) == "0"
        assert library.render((3, (7, None))) == "10"
        with pytest.raises(TypeError, match="contain 2 values"):
            library.render((3, (7,)))
        assert library.render((5, None)) == "5"
    finally:
        library.close()


def test_singleton_recursive_union_uses_tagged_host_storage(tmp_path):
    library = LLVM().compile_library('''
        type Nest = list[Nest]
        def render(value: Nest) -> str:
            if isinstance(value, list):
                return str(len(value))
            return "invalid"
    ''', tmp_path, entry_point="render")
    try:
        cycle = []
        cycle.append(cycle)
        assert library.render(cycle) == "1"
        assert library.render([]) == "0"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_normalized_optional_host_cycle_is_copied_and_retained(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Nest = list[Nest | None]
        SAVED: list[Nest] = []
        def render(value: Nest) -> str:
            gc_set_threshold(1)
            SAVED.append(value)
            gc_collect()
            return repr(SAVED[0]) + "|" + repr(value)
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        cycle = [None]
        cycle.append(cycle)
        expected = repr(cycle)
        assert library.render(cycle) == expected + "|" + expected
        assert cycle[1] is cycle
        cycle.clear()
        assert library.render([None, []]) == expected + "|[None, []]"
        with pytest.raises(TypeError):
            library.render([42])
        assert library.render([]) == expected + "|[]"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_normalized_optional_host_tuple_chain(tmp_path, optimize):
    comparison = LLVM().assert_library_matches_python('''
        type Link = tuple[int, Link | None]
        def render(value: Link) -> str:
            return repr(value)
    ''', (1, (2, (3, None))), directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        with pytest.raises(TypeError):
            comparison.library.render((1, (2, [])))
        assert comparison.library.render((4, None)) == "(4, None)"
    finally:
        comparison.library.close()


def test_recursive_abi_schema_is_finite_and_hashable():
    module = transpile_llvm_module('''
        type Tree = int | list[Tree]
        def main(value: Tree) -> str:
            return "tree"
    ''', target="library")
    root = module.parameters[0].value_type
    assert root.kind == "alias" and root.reference == 0
    assert len(module.type_definitions) == 1
    definition = root.resolve(module.type_definitions)
    assert definition.kind == "union"
    assert definition.members[1].item_type == root
    # Runtime shape/ctypes caches use structural keys; a cyclic dataclass graph
    # would recurse while hashing either the definition or its child reference.
    shapes = {root: definition, definition: root}
    assert shapes[definition.members[1].item_type] is definition
    assert shapes[module.type_definitions[0]] is root


@pytest.mark.parametrize("parameters", ["tree: Tree, record: Record", "record: Record, tree: Tree",
                                       "tree: Tree", "record: Record"])
def test_recursive_application_record_boundary_ignores_parameter_order(parameters):
    with pytest.raises(LLVMUnsupported, match="cannot contain recursive Record at line"):
        transpile_llvm_module(f'''
            from dataclasses import dataclass
            type Tree = list[Record] | None
            @dataclass
            class Record:
                value: int
                child: Tree
            def main({parameters}) -> str:
                return "unreachable"
        ''', target="library")


@pytest.mark.parametrize("record_container", ["tuple[Record, int]", "dict[str, Record]"])
def test_mutual_alias_record_cycles_reject_every_entry_order(record_container):
    parameters = ("tree: Tree", "branch: Branch", "record: Record")
    for count in range(1, len(parameters) + 1):
        for order in itertools.permutations(parameters, count):
            with pytest.raises(LLVMUnsupported, match="cannot contain recursive Record"):
                transpile_llvm_module(f'''
                    from dataclasses import dataclass
                    type Tree = list[Branch] | None
                    type Branch = list[Tree] | {record_container}
                    @dataclass
                    class Record:
                        child: Tree
                    def main({", ".join(order)}) -> str:
                        return "unreachable"
                ''', target="library")


def test_mutual_aliases_allow_finite_record_leaves_and_wrappers():
    # The record leaf is reachable FROM the cycle, and the wrapper reaches the
    # cycle, but neither record lies ON a cycle. Checking reachability of any
    # cycle (rather than a path back to that record) would falsely reject them.
    parameters = ("tree: Tree", "branch: Branch", "wrapper: Wrapper")
    for order in itertools.permutations(parameters):
        transpile_llvm_module(f'''
            from dataclasses import dataclass
            type Tree = tuple[Leaf, Branch] | None
            type Branch = list[Tree] | int
            @dataclass
            class Leaf:
                value: int
            @dataclass
            class Wrapper:
                tree: Tree
                branch: Branch
                leaf: Leaf
            def main({", ".join(order)}) -> str:
                return "finite records"
        ''', target="library")


@pytest.mark.parametrize("record_first", [False, True])
def test_finite_record_wrapping_recursive_containers_remains_supported(tmp_path, record_first):
    parameters = "record: Record, tree: Tree" if record_first else "tree: Tree, record: Record"
    library = LLVM().compile_library(f'''
        from dataclasses import dataclass
        from pyjs.native import gc_collect
        type Tree = int | list[Tree]
        @dataclass
        class Record:
            tree: Tree
        def main({parameters}) -> str:
            gc_collect()
            child = record.tree
            if isinstance(tree, list) and isinstance(child, list):
                return str(tree is child)
            return "wrong kind"
    ''', tmp_path)
    try:
        value = []
        value.append(value)
        record = {"tree": value}
        arguments = (record, value) if record_first else (value, record)
        assert library.render(*arguments) == "True"
    finally:
        library.close()


def test_same_named_imported_recursive_schemas_keep_distinct_definitions(tmp_path):
    names = ("_pyjs_input_numbers", "_pyjs_input_strings")
    try:
        for name, leaf in zip(names, ("int", "str"), strict=True):
            create_module(f"type Tree = {leaf} | list[Tree]\n", f"{name}.py", name)
        library = LLVM().compile_library(f'''
            from {names[0]} import Tree as Numbers
            from {names[1]} import Tree as Strings
            def render(numbers: Numbers, strings: Strings) -> str:
                if isinstance(numbers, list) and isinstance(strings, list):
                    n = numbers[0]
                    s = strings[0]
                    if isinstance(n, int) and isinstance(s, str):
                        return str(n) + s
                return "empty"
        ''', tmp_path, entry_point="render")
        try:
            assert library.parameters[0].value_type.reference != library.parameters[1].value_type.reference
            assert library.render([7], ["seven"]) == "7seven"
            for arguments in ((["wrong"], ["ok"]), ([1], [2])):
                with pytest.raises(TypeError, match="must match"):
                    library.render(*arguments)
            assert library.render([3], ["three"]) == "3three"
        finally:
            library.close()
    finally:
        for name in names:
            sys.modules.pop(name, None)


def test_recursive_input_direct_descriptor_renderer(tmp_path):
    library = LLVM().compile_library('''
        from pyjs.web.domx import div
        from pyjs.web.ssr import write_html_fd
        type Tree = int | list[Tree]
        def render(value: Tree, descriptor: int) -> int:
            count = len(value) if isinstance(value, list) else int(value)
            return write_html_fd(div(str(count)), descriptor)
    ''', tmp_path, entry_point="render", direct=True)
    try:
        cycle = []
        cycle.append(cycle)
        assert library.render(cycle) == "<div>1</div>"
        assert library.render(3) == "<div>3</div>"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_mutually_recursive_host_aliases(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect
        type Tree = str | list[Branch]
        type Branch = int | dict[str, Tree]

        def tree(value: Tree) -> int:
            gc_collect()
            if isinstance(value, str):
                return len(value)
            result = 0
            for child in value:
                result += branch(child)
            return result

        def branch(value: Branch) -> int:
            if isinstance(value, int):
                return int(value)
            result = 0
            for child in value.values():
                result += tree(child)
            return result

        def render(value: Tree) -> str:
            return str(tree(value))
    '''
    comparison = LLVM().compare_library_with_python(source,
        [{"title": "café", "children": [1, {"leaf": "done"}]}],
        directory=tmp_path, entry_point="render", optimize=optimize)
    try:
        assert comparison.matches
    finally:
        comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("mutual", [False, True])
def test_retained_recursive_host_graphs_compare_members_after_collection(tmp_path, optimize, mutual):
    declarations = ("type Tree = str | list[Branch]\n        type Branch = int | dict[str, Tree]" if mutual
                    else "type Tree = str | int | list[Tree] | dict[str, Tree] | None")
    library = LLVM().compile_library(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        {declarations}
        SAVED: list[Tree] = []

        def render(value: Tree) -> str:
            gc_set_threshold(1)
            SAVED.append(value)
            gc_collect()
            root = SAVED[0]
            if not isinstance(root, list):
                return 'invalid root'
            branch = root[{0 if mutual else 1}]
            if not isinstance(branch, dict):
                return 'invalid branch'
            return str((branch['cycle'] is root, branch['name'] == 'tree', len(SAVED)))
    ''', tmp_path, entry_point="render", optimize=optimize)
    root = []
    if not mutual:
        root.append(root)
    root.append({"cycle": root, "name": "tree"})
    try:
        assert library.render(root) == "(True, True, 1)"
        root.clear()  # The retained native cycle must not depend on host storage.
        assert library.render("later") == "(True, True, 2)"
        if not mutual:
            assert library.render(None) == "(True, True, 3)"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_input_promotion_from_immutable_foreign_cycle_under_asan(tmp_path, optimize):
    module = transpile_llvm_module('''
        from pyjs.native import gc_collect, gc_set_threshold
        type Tree = int | list[Tree]
        SAVED: list[Tree] = []

        def render(value: Tree) -> str:
            gc_set_threshold(1)
            if not isinstance(value, list):
                return "bad kind"
            child = value[0]
            if not isinstance(child, list):
                return "bad child"
            value.append(7)
            SAVED.append(value)
            gc_collect()
            return str((value is child, len(child)))
    ''', target="library", entry_point="render")
    # Constant foreign storage makes accidental borrowing observable. Every
    # union slot is inline; its active reference must point to the same promoted
    # list, even when first reached through a different tagged slot.
    source = module.llvm_ir + '''
        @test.items = private constant [1 x { i64, i64 }] [
          { i64, i64 } { i64 6, i64 ptrtoint (ptr @test.list to i64) } ]
        @test.list = private constant %pyjs.list { i64 1, i64 1,
          ptr @test.items, ptr null, ptr null, i64 0 }
        @test.root = private constant { i64, i64 } {
          i64 6, i64 ptrtoint (ptr @test.list to i64) }
        define private void @test.error(ptr %trace, ptr %message, ptr %type) {
          ret void
        }
        define i32 @main() {
          %heap = call ptr @pyjs_gc_new()
          %first = call i32 @pyjs_render_to_fd(ptr %heap, i32 1,
            ptr @test.error, ptr @test.root)
          %second = call i32 @pyjs_render_to_fd(ptr %heap, i32 1,
            ptr @test.error, ptr @test.root)
          call void @pyjs_gc_delete(ptr %heap)
          %status = or i32 %first, %second
          ret i32 %status
        }
    '''
    result = LLVM()._run_ir(source, tmp_path, name="recursive-input", optimize=optimize,
                            pass_fds=(), sanitizers=("address", "undefined"), timeout=10, artifacts=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "(True, 2)(True, 2)"
    assert result.stderr == ""
