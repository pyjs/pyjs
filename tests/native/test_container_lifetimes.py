import pytest

from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError

CASES = [
    pytest.param("dict[Key, Key]", "{}", "items.setdefault(Key(number), Key(number + 100))", id="setdefault"),
    pytest.param("dict[Key, Key]", "{}", "items.update({Key(number): Key(number + 100)})", id="update-dict"),
    pytest.param("dict[Key, Key]", "{}", "items.update([(Key(number), Key(number + 100))])", id="update-pairs"),
    pytest.param("dict[Key, Key]", "{}", "items |= {Key(number): Key(number + 100)}", id="dict-inplace-union"),
    pytest.param("dict[Key, Key]", "{}", "items = dict.fromkeys([Key(number)], Key(number + 100))", id="fromkeys"),
    pytest.param("dict[Key, Key]", "{}", "items = {Key(number): Key(number + 100)}.copy()", id="dict-copy"),
    pytest.param("dict[Key, Key]", "{}", "items = items | {Key(number): Key(number + 100)}", id="dict-union"),
    pytest.param("list[Key]", "[]", "items.extend([Key(number)])", id="extend"),
    pytest.param("list[Key]", "[]", "items.insert(0, Key(number))", id="insert"),
    pytest.param("list[Key]", "[]", "items += [Key(number)]", id="list-inplace-add"),
    pytest.param("list[Key]", "[]", "items = [Key(number)].copy()", id="list-copy"),
    pytest.param("list[Key]", "[]", "items = items + [Key(number)]", id="list-add"),
    pytest.param("set[Key]", "set()", "items.add(Key(number))", id="add"),
    pytest.param("set[Key]", "set()", "items.update([Key(number)], {Key(number + 100)})", id="set-update"),
    pytest.param("set[Key]", "set()", "items = {Key(number)}.copy()", id="set-copy"),
    pytest.param("set[Key]", "set()", "items |= {Key(number)}", id="set-inplace-union"),
    pytest.param("set[Key]", "set()", "items = items.union({Key(number)})", id="set-union"),
    pytest.param("list[Key]", "[]", "items.extend({0: Key(number)}.values())", id="extend-values"),
    pytest.param("list[Key]", "[]", "items.extend({Key(number): 0}.keys())", id="extend-keys"),
    pytest.param("list[Key]", "[]", "items.extend(iter([Key(number)]))", id="extend-iterator"),
    pytest.param("list[Key]", "[]", "items.extend(reversed([Key(number)]))", id="extend-reversed"),
    pytest.param("list[Key]", "[]", "items.extend([Key(number)][:])", id="extend-slice"),
    pytest.param("list[Key]", "[]", "items.extend(sorted([Key(number)], key=lambda x: x.number))", id="extend-sorted"),
    pytest.param("set[Key]", "set()", "items.update({Key(number): 0}.keys())", id="update-keys"),
    pytest.param("dict[Key, Key]", "{}", "items.update(zip([Key(number)], [Key(number + 100)]))", id="update-zip"),
    pytest.param("dict[Key, Key]", "{}", "items.update({Key(number): Key(number + 100)}.items())", id="update-items"),
    pytest.param("dict[Key, Key]", "{}", "items = dict.fromkeys({Key(number): 0}.keys(), Key(number + 100))", id="fromkeys-keys"),
    pytest.param("set[Key]", "set()", "items = items.union({0: Key(number)}.values())", id="union-values"),
    pytest.param("set[Key]", "set()", "items.add({Key(number)}.pop())", id="set-pop-member"),
]


def container_source(annotation, initial, statement):
    read = ("repr([(key.number, value.number) for key, value in item.items()])"
            if annotation.startswith("dict") else
            "repr(sorted(value.number for value in item))")
    return f'''
from pyjs.native import gc_collect
class Key:
    def __init__(self, number: int):
        self.number = number
    def __hash__(self) -> int:
        return self.number
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Key) and self.number == other.number
SAVED: list[{annotation}] = []
def render(number: int, fail: bool) -> str:
    items: {annotation} = {initial}
    {statement}
    SAVED.append(items)
    junk = [Key(999) for _ in range(64)]
    gc_collect()
    if fail:
        raise ValueError("saved before failure")
    return "|".join({read} for item in SAVED) + str(len(junk))
'''


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, initial, statement", CASES)
def test_builtin_container_members_survive_successful_and_failed_library_calls(
    tmp_path, optimize, annotation, initial, statement,
):
    source = container_source(annotation, initial, statement)
    namespace = {}
    exec(source, namespace)
    calls = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for number, fail in calls:
        if fail:
            with pytest.raises(ValueError, match="saved before failure"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))
    # Request-arena reuse is essential: one executable invocation can leave
    # misclassified local objects readable even after their containers escape.
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in calls:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="saved before failure"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, initial, statement", [CASES[0], CASES[2], CASES[7], CASES[13], CASES[17], CASES[24]])
def test_builtin_container_members_with_sanitizers(tmp_path, optimize, annotation, initial, statement):
    source = container_source(annotation, initial, statement) + '''
def main() -> str:
    first = render(1, False)
    try:
        render(2, True)
    except ValueError:
        pass
    return first + render(3, False)
'''
    comparison = LLVM().compare_with_python(source, directory=tmp_path, optimize=optimize,
                                            sanitizers=("address", "undefined"))
    assert comparison.matches
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_setdefault_retains_the_existing_member_as_well_as_the_default(tmp_path, optimize):
    source = '''
from pyjs.native import gc_collect
class Box:
    def __init__(self, value: int):
        self.value = value
SAVED: list[Box] = []
def choose(source: dict[int, Box], default: Box) -> Box:
    return source.setdefault(0, default)
def render(number: int) -> str:
    source = {0: Box(number)}
    result = choose(source, Box(number + 100))
    SAVED.append(result)
    junk = [Box(999) for _ in range(64)]
    gc_collect()
    return repr([item.value for item in SAVED]) + str(len(junk))
'''
    namespace = {}
    exec(source, namespace)
    expected = [namespace["render"](number) for number in (1, 2, 3)]
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        assert [library.render(number) for number in (1, 2, 3)] == expected
        assert heap._Heap.from_address(library._heap).roots is None
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("nested", [False, True], ids=["scalar", "nested"])
@pytest.mark.parametrize("expression", [
    "[Box(Child(number))].copy()[0]",
    "([Box(Child(number))] + [Box(Child(number + 1))])[0]",
    "([Box(Child(number))] * 2)[0]",
    "{0: Box(Child(number))}.copy()[0]",
    "dict.fromkeys([0], Box(Child(number)))[0]",
    "({0: Box(Child(number))} | {1: Box(Child(number + 1))})[0]",
])
def test_immediately_indexed_result_keeps_its_member_not_only_the_members_fields(tmp_path, optimize, expression, nested):
    if not nested:
        expression = expression.replace("Child(number + 1)", "number + 1").replace("Child(number)", "number")
    field_type = "Child" if nested else "int"
    churn_value = "Child(999)" if nested else "999"
    observed = "box.child.value" if nested else "box.child"
    source = f'''
from pyjs.native import gc_collect
class Child:
    def __init__(self, value: int):
        self.value = value
class Box:
    def __init__(self, child: {field_type}):
        self.child = child
SAVED: list[Box] = []
def render(number: int) -> str:
    SAVED.append({expression})
    junk = [Box({churn_value}) for _ in range(64)]
    gc_collect()
    return repr([{observed} for box in SAVED]) + str(len(junk))
'''
    namespace = {}
    exec(source, namespace)
    expected = [namespace["render"](number) for number in (1, 2, 3)]
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        assert [library.render(number) for number in (1, 2, 3)] == expected
        assert heap._Heap.from_address(library._heap).roots is None
    finally:
        library.close()
