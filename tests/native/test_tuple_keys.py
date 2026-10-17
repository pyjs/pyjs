import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("stored, query", [
    ("tuple(range(2))", "(0, 1)"),
    ("(0, 1)", "tuple(range(2))"),
    ("(0, 1)", "tuple(range(1))"),
    ("(0, 1)", "tuple(range(3))"),
    ("(0, True)", "(0, 1)"),
    ("((0, True), None, frozenset([1, 2]))", "((0, 1), None, frozenset([2, 1]))"),
])
def test_tuple_queries_keep_their_own_layout(tmp_path, optimize, stored, query):
    comparison = LLVM().compare_with_python(f'''
def main() -> str:
    key = {stored}
    data = {{key: 7}}
    keys = {{key}}
    query = {query}
    membership = str(query in data) + str(query in keys)
    try:
        value = str(data[query])
    except KeyError as error:
        value = str(error)
    return membership + ":" + value
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_fixed_keys_can_be_stored_in_compatible_runtime_tuple_mappings(tmp_path, optimize):
    # Preserved foundation contract: homogeneous fixed tuples share the runtime
    # view's item layout. This does not permit the reverse narrowing insertion.
    comparison = LLVM().compare_with_python('''
from pyjs.native import gc_collect
def main() -> str:
    numbers: dict[tuple[int, ...], int] = {tuple(range(2)): 1}
    numbers[tuple(range(3))] = 2
    numbers[(0, 1, 2, 3)] = 3
    gc_collect()
    return str((numbers[tuple(range(2))], numbers[tuple(range(3))],
                numbers[(0, 1)], (0, 1, 2) in numbers,
                numbers[tuple(range(4))]))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_heterogeneous_fixed_and_runtime_queries_check_lengths_before_fields(tmp_path, optimize):
    comparison = LLVM().compare_with_python('''
def main() -> str:
    fixed = (True, 1.0)
    data = {fixed: 7}
    results: list[bool] = []
    for length in range(4):
        variable = tuple([1 for _ in range(length)])
        results.extend([variable in data, fixed in {variable},
                        variable == fixed, fixed == variable])
    return repr(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("clear", [False, True])
def test_tuple_query_only_callbacks_and_mutation_restart(tmp_path, optimize, clear):
    comparison = LLVM().compare_with_python(f'''
from pyjs.native import gc_collect, gc_set_threshold
events: list[str] = []
class Stored:
    def __init__(self):
        self.owner: dict[tuple[Stored, ...], int] | None = None
    def __hash__(self) -> int:
        events.append("stored hash")
        return 1
    def __eq__(self, other: object) -> bool:
        events.append("stored eq")
        owner = self.owner
        self.owner = None
        if owner is not None:
            owner.clear()
        gc_collect()
        return isinstance(other, Query)
class Query:
    def __init__(self):
        self.fail = True
    def __hash__(self) -> int:
        events.append("query hash")
        gc_collect()
        if self.fail:
            raise ValueError("retry")
        return 1
    def __eq__(self, other: object) -> bool:
        events.append("query eq")
        return False
    def __repr__(self) -> str:
        events.append("query repr")
        gc_collect()
        return "Query"
def main() -> str:
    gc_set_threshold(1)
    stored = Stored()
    data: dict[tuple[Stored, ...], int] = {{tuple([stored]): 1}}
    if {clear}:
        stored.owner = data
    member = Query()
    query = (member,)
    try:
        query in data
    except ValueError:
        events.append("caught")
    member.fail = False
    found = str(query in data)
    try:
        found += str(data[query])
    except KeyError as error:
        found += str(error)
    gc_collect()
    return found + str(len(data)) + repr(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("write", ["data[key] = 3", "data.setdefault(key, 3)"])
def test_runtime_tuple_queries_do_not_enable_narrowing_insertions(write):
    with pytest.raises(CompilationError, match="expects tuple"):
        transpile_llvm(f'''
def main() -> str:
    data = {{(1, 2): 10}}
    key = tuple(range(2))
    {write}
    return str(data)
''')


@pytest.mark.parametrize("stored, query", [
    ("(Key(),)", "(int8(3),)"),
    ("tuple([Key(), Key()])", "(int8(3), int8(3))"),
    ("(Key(), Key())", "tuple([int8(3), int8(3)])"),
])
@pytest.mark.parametrize("expression, message", [
    ("query in data", "Collection membership uses incompatible item representations"),
    ("data[query]", "Dictionary lookup uses an incompatible key representation"),
])
def test_tuple_query_callbacks_do_not_erase_portable_representations(stored, query, expression, message):
    # Shared analysis already protects this boundary; lookup lowering must not
    # circumvent it just because two tuple references both use pointer storage.
    with pytest.raises(CompilationError, match=message):
        transpile_llvm(f'''
from pyjs import int8
class Key:
    def __hash__(self) -> int:
        return 3
    def __eq__(self, other: object) -> bool:
        return isinstance(other, int) and other + 125 == -128
def main() -> bool:
    data = {{{stored}: True}}
    query = {query}
    return {expression}
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_tuple_inputs_initialize_hash_caches(tmp_path, optimize):
    library = LLVM().compile_library('''
def render(pair: tuple[int, str], values: tuple[int, ...]) -> str:
    return str((hash(pair) == hash((pair[0], pair[1])),
                hash(values) == hash(tuple(list(values)))))
''', tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render((1, "one"), (2, 3)) == "(True, True)"
        assert library.render((4, "four"), (5, 6, 7)) == "(True, True)"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_key_updates_and_set_algebra_reuse_value_hashing(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def main() -> str:
    gc_set_threshold(1)
    data = {("one", 1): 10, ("two", 2): 20}
    data[("one", 1)] = 11
    copied = data.copy()
    copied.update({("three", 3): 30})
    removed = copied.pop(("two", 2))
    gc_collect()
    left = {(1, 10), (2, 20)}
    right = {(2, 20), (3, 30)}
    both = left | right
    common = left & right
    difference = left - right
    changed = left ^ right
    frozen = frozenset(left)
    return str((data, copied, removed, left == frozen,
                both == {(1, 10), (2, 20), (3, 30)},
                common == {(2, 20)}, difference == {(1, 10)},
                changed == {(1, 10), (3, 30)}, common < left))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
