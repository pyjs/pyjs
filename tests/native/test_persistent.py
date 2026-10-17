import ctypes
import textwrap

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm_module
from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMLibrary, LLVMRuntimeError
from tests.native.allocation_support import _fail_allocations


@pytest.mark.parametrize("optimize", [0, 2])
def test_transformed_collections_and_strings_survive_library_returns(tmp_path, optimize):
    # Compare retained content across host calls, not historical allocator
    # object counts: sharing/caching may change without losing ownership.
    source = textwrap.dedent('''
        from pyjs.native import gc_collect, gc_set_threshold

        def retain(seed: int, lists: list[list[int]] = [],
                   mappings: list[dict[int, int]] = [], sets: list[set[int]] = [],
                   texts: list[str] = [], pairs: list[tuple[int, int]] = []) -> str:
            gc_collect()
            if lists:
                lists[0].append(seed)
            values = [seed, seed + 1]
            lists.extend([values.copy(), values[:], values + [seed + 2], values * 2,
                          sorted(values, reverse=True), list(values), list(range(seed))])
            mapping = {seed: seed + 1}.copy()
            mappings.extend([mapping, dict(mapping), mapping | {seed + 2: seed + 3}])
            pairs.append(mapping.popitem())
            members = {seed, seed + 1}.copy()
            union = members | {seed + 2}
            sets.extend([members, set(values), union, union & {seed + 1, seed + 2},
                         union - {seed}, union ^ {seed + 1, seed + 3}])
            value = 'É,A,' + str(seed)
            parts = value.split(',')
            texts.extend([value[0], value[1:], value.lower(), value.replace(',', '-'),
                          ':'.join(parts), value.removeprefix('É'), value.removesuffix(str(seed)),
                          ('  ' + value + '  ').strip()])
            texts.extend(parts)
            texts.extend(value)
            gc_collect()
            return str((lists, mappings, [sorted(item) for item in sets], texts, pairs))

        def render(seed: int) -> str:
            gc_set_threshold(1)
            return retain(seed)
    ''')
    namespace = {}
    exec(compile(source, 'retained-library-oracle.py', 'exec'), namespace)
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        for seed in (2, 4, 1):
            assert library.render(seed) == namespace['render'](seed)
    finally:
        library.close()


@pytest.mark.parametrize("declaration, message", [
    ('values: list[int] = [len("effect")]', "requires a literal initializer"),
    ('values = []', "needs a complete collection annotation"),
    ('values: tuple[int, str] = (1,)', "tuple length does not match"),
    ('values: list[int] = []\nvalues = values', "alias 'values' is cyclic"),
    ('if True:\n    values = [1]', "requires a direct literal initializer"),
    ('values: list[int]\nexec("values = [1]")', "requires a direct literal initializer"),
    ('from builtins import set as Set\ndef set() -> Set[int]:\n    return {7}\nvalues: Set[int] = set()', "requires a literal initializer"),
])
def test_module_literal_boundaries_have_focused_diagnostics(declaration, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm_module(declaration + '\n\ndef main() -> int:\n    return len(values)\n')


@pytest.mark.parametrize("declaration", [
    'values = [1, 2]\nvalues.append(3)',
    'values = [1, 2]\nvalues += [5]',
    'values = {"a": 1}\nvalues["b"] = 2',
    'values: dict[str, int] = {}\nfor key in ["x", "y"]:\n    values[key] = 1',
    'values = [1]\ndef register() -> None:\n    values.append(5)\nregister()',
    'values = {"a": 1, "b": 2}\nvalues["a"] = values.pop("a")',
    'values = [1]\nvalues[0] = True',
    'values = [-0.0]\nvalues[0] = 0.0',
    'values: list[list[int]] = [[], []]\nvalues[1] = values[0]',
])
def test_import_time_mutation_is_rejected_instead_of_reconstructed(declaration):
    with pytest.raises(CompilationError, match="changed during import") as caught:
        transpile_llvm_module(declaration + '\n\ndef main() -> int:\n    return len(values)\n')
    assert caught.value.diagnostic.primary.span.start_position.line == 0


@pytest.mark.parametrize("declaration", ['values = [1, 2]', 'values = {"a": "b"}'])
def test_jvm_module_collections_keep_a_located_unsupported_boundary(declaration):
    from pyjs.java import JVMUnsupported, transpile_jvm

    with pytest.raises(JVMUnsupported, match="module collection state is not implemented at line"):
        transpile_jvm(declaration + '\n\ndef main() -> int:\n    return len(values)\n')


@pytest.mark.parametrize("keyword_only", [False, True])
@pytest.mark.parametrize("change", ["items.append(2)", "items[0] = True"])
def test_import_time_default_mutation_is_rejected(keyword_only, change):
    parameter = "*, " if keyword_only else ""
    attribute = '__kwdefaults__["items"]' if keyword_only else '__defaults__[0]'
    with pytest.raises(LLVMUnsupported, match="literal default changed during import at line"):
        transpile_llvm_module(f'''
            def values({parameter}items: list[int] = [1]) -> list[int]:
                return items
            items = values.{attribute}
            {change}
            def main() -> str:
                return str(values())
        ''')


@pytest.mark.parametrize("source", [
    '''
    first: list[int] = []
    second: list[int] = []
    globals()["second"] = first
    def main() -> int:
        return int(first is second)
    ''',
    '''
    def first(items: list[int] = []) -> list[int]:
        return items
    def second(items: list[int] = []) -> list[int]:
        return items
    second.__defaults__ = first.__defaults__
    def main() -> int:
        return int(first() is second())
    ''',
    '''
    items: list[int] = []
    def values(default: list[int] = []) -> list[int]:
        return default
    values.__defaults__ = (items,)
    def main() -> int:
        return int(values() is items)
    ''',
])
def test_import_time_aliases_between_distinct_literal_roots_are_rejected(source):
    with pytest.raises(LLVMUnsupported, match="during import.*at line"):
        transpile_llvm_module(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_module_state_retains_host_values_after_failed_library_calls(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect

        VALUES: list[list[str]] = []
        SEEN: set[str] = set()
        PAYLOAD: tuple[bytes, float, bool] = (b"data", -1.25, True)

        def render(label: str, fail: bool) -> str:
            VALUES.append([label])
            SEEN.add(label)
            gc_collect()
            if fail:
                raise ValueError("saved before failure")
            return str((VALUES, sorted(SEEN), PAYLOAD))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render("one", False) == "([['one']], ['one'], (b'data', -1.25, True))"
        with pytest.raises(LLVMRuntimeError, match="saved before failure"):
            library.render("two", True)
        assert library.render("three", False) == "([['one'], ['two'], ['three']], ['one', 'three', 'two'], (b'data', -1.25, True))"
        assert heap._Heap.from_address(library._heap).roots is None
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_state_preserves_union_members_and_signed_values(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        VALUES: list[int | str | None] = [-2, "module", None]

        def update(values: list[int | str | None] = [-1, "default", None]) -> str:
            values.append(len(values))
            gc_collect()
            return str(values)

        def main() -> str:
            VALUES.append("new")
            return str(VALUES) + update() + update()
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_module_literals_share_storage_and_survive_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        VALUES: list[int] = [1, 2]
        ALIAS = VALUES
        NESTED: dict[str, list[int]] = {"a": [9]}
        PAIR: tuple[list[str], set[int]] = (["x"], {3})
        UNUSED: list[int] = [len("do not compile this initializer")]

        def update() -> str:
            ALIAS.append(len(VALUES))
            NESTED["a"].append(len(VALUES))
            PAIR[0].append("y")
            PAIR[1].add(4)
            gc_collect()
            return str((VALUES, NESTED, PAIR[0], sorted(PAIR[1]), ALIAS is VALUES))

        def main() -> str:
            first = update()
            gc_collect()
            return first + update()
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_imported_literals_have_canonical_identity_and_owned_mutations(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import tests.native.persistent_values as state
        from tests.native.persistent_values import ALIAS, VALUES, PAIR, UNUSED, remember
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            remember("second")
            gc_collect()
            state.PAIR[0].append(2)
            PAIR[1].add("new")
            remember("third")
            gc_collect()
            return str((ALIAS is VALUES, VALUES is state.VALUES, state.ALIAS is VALUES,
                        VALUES, state.PAIR[0], sorted(PAIR[1]), state.PAIR is PAIR,
                        sorted(PAIR[2])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_imported_literal_alias_can_be_rebound_without_resolving_unused_values(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from tests.native.persistent_values import PAIR, UNUSED
        from tests.native.persistent_values import PAIR as replacement

        replacement: tuple[list[int], set[str], frozenset[str]] = ([9], {"new"}, frozenset({"other"}))

        def main() -> int:
            return int(replacement is not PAIR) + int("new" in replacement[1])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.returncode == 2
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_defaults_share_identity_across_calls_and_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def update(values: list[int] = [1, 2], *, nested: dict[str, list[int]] = {"items": [10]}) -> int:
            values.append(len(values))
            nested["items"].append(len(values))
            gc_collect()
            return sum(values) + sum(nested["items"])

        def defaults(pair: tuple[list[int], set[str], tuple[str, ...]] = ([1], {"a"}, ("x", "y"))) -> str:
            pair[0].append(len(pair[0]))
            pair[1].add("b")
            gc_collect()
            return str((pair[0], sorted(pair[1]), pair[2]))

        def main() -> str:
            gc_set_threshold(1)
            first = str(update()) + defaults()
            gc_collect()
            return first + str(update()) + defaults()
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_literal_defaults_bind_through_dynamic_expansion(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def update(values: list[int] = [], *, seen: list[int] = []) -> str:
            values.append(len(values))
            seen.append(len(values))
            gc_collect()
            return str(values) + str(seen)

        def empty_set(values: set[str] = set[str]()) -> int:
            values.add(str(len(values)))
            return len(values)

        def main() -> str:
            positional: list[list[int]] = []
            named: dict[str, list[int]] = {}
            first = update(*positional, **named)
            second = update()
            return first + second + update([9], seen=[8]) + update() + str((empty_set(), empty_set()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_defaults_are_lazy_and_heap_local_across_library_calls(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect

        def update(values: list[int] = [1]) -> int:
            values.append(len(values))
            gc_collect()
            return len(values)

        def render(use_default: bool) -> str:
            return str(update() if use_default else update([9]))
    '''
    first = LLVM().compile_library(source, tmp_path / "first", entry_point="render", optimize=optimize)
    second = LLVM().compile_library(source, tmp_path / "second", entry_point="render", optimize=optimize)
    try:
        assert first.render(False) == "2"
        assert heap._Heap.from_address(first._heap).modules is None
        assert first.render(True) == "2"
        assert first.render(True) == "3"
        assert second.render(True) == "2"
        assert second.render(True) == "3"
        assert first.render(False) == "2"
        assert first.render(True) == "4"
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("location", ["default", "module"])
@pytest.mark.parametrize("set_kind", ["set", "frozenset"])
def test_initialization_failure_does_not_publish_partial_state(tmp_path, optimize, location, set_kind):
    annotation = f"tuple[list[int], dict[str, list[int]], {set_kind}[str]]"
    items = '{"a","b"}' if set_kind == "set" else 'frozenset({"a","b"})'
    literal = '([1,2,3,4,5,6,7,8,9], {"one": [11,12], "two": [21,22]}, ' + items + ')'
    declaration = (f"def state(values: {annotation} = {literal}) -> {annotation}:"
                   if location == "default" else f"values: {annotation} = {literal}\n\n        def state() -> {annotation}:")
    module = transpile_llvm_module(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        {declaration}
            return values

        def main() -> str:
            try:
                saved = state()
            except MemoryError:
                return "failed"
            arm(0)
            gc_collect()
            saved[0][0] += 1
            return str((saved[0], saved[1], sorted(saved[2])))
    ''', target="library")
    source = _fail_allocations(module.llvm_ir, True, extra=[
        ("pyjs.gc.try.module.root", "ptr %heap, i64 %key"),
    ]).replace("@test.remaining = private global", "@test.remaining = global")
    path = LLVM().compile(source, tmp_path, shared=True, optimize=optimize)
    for fail_at in range(1, 100):
        library = LLVMLibrary(path, source, module.parameters, module.direct, module.managed,
                              module.exceptions, module.type_definitions)
        remaining = ctypes.c_int64.in_dll(library._library, "test.remaining")
        state = heap._Heap.from_address(library._heap)
        try:
            remaining.value = fail_at
            result = library.render()
            assert state.roots is None
            assert state.pins is None
            remaining.value = 0
            expected = "([2, 2, 3, 4, 5, 6, 7, 8, 9], {'one': [11, 12], 'two': [21, 22]}, ['a', 'b'])"
            failed = result == "failed"
            if not failed:
                assert result == expected and fail_at > 8
            # A failed initialization must be retryable on the same heap, then
            # retain that recovered state through another collecting call.
            first = 2 if failed else 3
            for value in (first, first + 1):
                assert library.render() == expected.replace("([2,", f"([{value},")
                assert state.roots is None
                assert state.pins is None
            if not failed:
                break
        finally:
            remaining.value = 0
            library.close()
    else:
        pytest.fail("did not exhaust persistent-initialization failure points")
