from textwrap import indent

import pytest

from pyjs.native.errors import LLVMUnsupported
from pyjs.native.runtime import heap
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.lifetime_fixtures import PERSISTENT_ALIAS_CASES, PERSISTENT_ALIAS_DEFINITIONS

WRAPPERS = [
    pytest.param('''def copied(value: Box) -> list[Box]:
    items: list[Box] = []
    result = items.copy()
    result.append(value)
    return result
''', "copied(Box(number))[0]", id="copy-then-append"),
    pytest.param('''def copied(value: Box) -> dict[int, Box]:
    items: dict[int, Box] = {}
    result = items.copy()
    result[0] = value
    return result
''', "copied(Box(number))[0]", id="dict-copy-then-store"),
    pytest.param('''def copied(value: Box) -> list[Box]:
    items: list[Box] = []
    other: list[Box] = []
    result = items + other
    result.append(value)
    return result
''', "copied(Box(number))[0]", id="concat-then-append"),
    pytest.param('''def copied(value: Box) -> list[Box]:
    return [value].copy()
''', "copied(Box(number))[0]", id="copied-member"),
    pytest.param('''def copied(value: list[Box]) -> list[Box]:
    return value.copy()
''', "copied([Box(number)])[0]", id="copied-source"),
    pytest.param('''def copied(value: Box) -> list[list[Box]]:
    return [[value]].copy()
''', "copied(Box(number))[0][0]", id="nested"),
    pytest.param('''def copied(value: Box) -> list[Box]:
    return [value].copy()
def outer(value: Box) -> list[Box]:
    return copied(value)
''', "outer(Box(number))[0]", id="transitive"),
    pytest.param('''def copied(value: Box, source: list[Box], choose: bool) -> list[Box]:
    if choose:
        return source
    return [value].copy()
''', "copied(Box(number), [Box(number + 100)], number % 2 == 0)[0]", id="mixed-alias-and-owned"),
    pytest.param('''def store(target: list[list[Box]], value: Box) -> None:
    target.insert(0, [value])
def copied(number: int) -> Box:
    target: list[list[Box]] = []
    store(target, Box(number))
    return target[0][0]
''', "copied(number)", id="nested-parameter-insert"),
    pytest.param('''def store(target: dict[int, list[Box]], value: Box) -> None:
    target.update({0: [value]})
def copied(number: int) -> Box:
    target: dict[int, list[Box]] = {}
    store(value=Box(number), target=target)
    return target[0][0]
''', "copied(number)", id="nested-parameter-update"),
    pytest.param('''def store(target: list[tuple[list[Box]]], value: Box) -> list[tuple[list[Box]]]:
    target.append(([value],))
    return target
def copied(number: int) -> Box:
    target: list[tuple[list[Box]]] = []
    return store(target, Box(number))[0][0][0]
''', "copied(number)", id="deep-returned-parameter"),
]

MEMBER_READS = [
    "dict[int, Box]().get(0, Box(number))",
    "dict[int, Box]().pop(0, Box(number))",
    "{0: Box(number)}.get(0, Box(number + 100))",
    "{0: Box(number)}.pop(0)",
    "[Box(number)].pop()",
    "{0: Box(number)}.popitem()[1]",
    "next(iter([Box(number)]))",
    "next(iter(list[Box]()), Box(number))",
    "next(enumerate([Box(number)]))[1]",
    "next(zip([Box(number)]))[0]",
    "list({0: Box(number)}.values())[0]",
    "sorted([Box(number)], key=lambda box: box.number)[0]",
    "[Box(number)][0:1][0]",
    "min([Box(number)], key=lambda box: box.number)",
    "max(Box(number), Box(number - 1), key=lambda box: box.number)",
    "min(list[Box](), default=Box(number), key=lambda box: box.number)",
]


def returned_source(helper, expression):
    return f'''
from pyjs.native import gc_collect
class Box:
    def __init__(self, number: int):
        self.number = number
SAVED: list[Box] = []
{helper}
def render(number: int, fail: bool) -> str:
    SAVED.append({expression})
    junk = [Box(999) for _ in range(64)]
    gc_collect()
    if fail:
        raise ValueError("retained before error")
    return repr([item.number for item in SAVED]) + str(len(junk))
'''


def assert_persistent_parity(source, tmp_path, optimize):
    namespace = {}
    exec(source, namespace)
    calls = [(1, False), (2, True), (3, False), (4, False)]
    expected = []
    for number, fail in calls:
        if fail:
            with pytest.raises(ValueError, match="retained before error"):
                namespace["render"](number, fail)
        else:
            expected.append(namespace["render"](number, fail))
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number, fail in calls:
            if fail:
                with pytest.raises(LLVMRuntimeError, match="retained before error"):
                    library.render(number, fail)
            else:
                actual.append(library.render(number, fail))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("declaration, expression", [
    ("def bucket(target: list[Box] = []) -> list[Box]:\n    return target", "bucket()"),
    ("def bucket(*, target: list[Box] = []) -> list[Box]:\n    return target", "bucket()"),
    ("class Holder:\n    def bucket(self, target: list[Box] = []) -> list[Box]:\n        return target", "Holder().bucket()"),
    ("DEFAULT: list[Box] = []\ndef bucket(target: list[Box] | None = None) -> list[Box]:\n    return DEFAULT if target is None else target", "bucket()"),
    ("DEFAULT: list[Box] = []\ndef bucket(*, target: list[Box] | None = None) -> list[Box]:\n    return DEFAULT if target is None else target", "bucket()"),
])
def test_direct_default_getter_writes_retain_scalars_between_requests(tmp_path, optimize, declaration, expression):
    # Keep the direct getter call and readback: a local alias or exception path
    # can independently force heap placement and mask the original regression.
    source = f'''
from pyjs.native import gc_collect
class Box:
    def __init__(self, number: int):
        self.number = number
{declaration}
def render(number: int) -> str:
    {expression}.append(Box(number))
    junk = [Box(999) for _ in range(64)]
    gc_collect()
    return repr([item.number for item in {expression}]) + str(len(junk))
'''
    namespace = {}
    exec(source, namespace)
    expected = [namespace["render"](number) for number in (1, 2, 3)]
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number in (1, 2, 3):
            actual.append(library.render(number))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("factory", ["fresh_list", "shared_items", "Factories.list",
                                     "same_class_list", "same_class_make_items",
                                     "ClassFactories.list", "ClassFactories.make_items"])
def test_dataclass_factory_members_survive_retention_and_request_resets(tmp_path, optimize, factory):
    # A user factory named list is not the builtin. Read the actual shared
    # storage after each request; retaining Bag itself would hide that mistake.
    factory_name = factory.removeprefix("same_class_")
    declaration = (f'''
    @staticmethod
    def {factory_name}() -> fresh_list[Box]:
        return SHARED
''' if factory.startswith("same_class_") else "")
    source = f'''
from builtins import list as fresh_list
from dataclasses import dataclass, field
from pyjs.native import gc_collect
class Box:
    def __init__(self, number: int):
        self.number = number
SHARED: fresh_list[Box] = []
def shared_items() -> fresh_list[Box]:
    return SHARED
class Factories:
    @staticmethod
    def list() -> fresh_list[Box]:
        return SHARED
class ClassFactories:
    @classmethod
    def list(cls) -> fresh_list[Box]:
        return SHARED
    @classmethod
    def make_items(cls) -> fresh_list[Box]:
        return SHARED
@dataclass
class Bag:
{declaration}
    items: fresh_list[Box] = field(default_factory={factory_name})
SAVED: fresh_list[Bag] = []
def render(number: int) -> str:
    bag = Bag()
    bag.items.append(Box(number))
    {"SAVED.append(bag)" if factory == "fresh_list" else "pass"}
    junk = [Box(999) for _ in range(64)]
    gc_collect()
    return repr({"[item.items[0].number for item in SAVED]" if factory == "fresh_list" else "[item.number for item in SHARED]"}) + str(len(junk))
'''
    namespace = {}
    exec(source, namespace)
    expected = [namespace["render"](number) for number in (1, 2, 3)]
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number in (1, 2, 3):
            actual.append(library.render(number))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("prefix, argument", [("", ""), ("*, ", ""), ("", "*()"), ("*, ", "**{}")])
@pytest.mark.parametrize("store_inside", [False, True], ids=["getter", "callee-store"])
def test_omitted_defaults_keep_members_across_successful_and_failed_requests(
    tmp_path, optimize, prefix, argument, store_inside,
):
    helper = (f'''def put(value: Box, {prefix}target: list[Box] = []) -> list[Box]:
    target.append(value)
    return target
''' if store_inside else f'''def bucket({prefix}target: list[Box] = []) -> list[Box]:
    return target
''')
    statement = (f"values = put(Box(number){', ' + argument if argument else ''})" if store_inside
                 else f"values = bucket({argument}); values.append(Box(number))")
    source = f'''
from pyjs.native import gc_collect
class Box:
    def __init__(self, number: int):
        self.number = number
{helper}
def render(number: int, fail: bool) -> str:
    {statement}
    junk = [Box(999) for _ in range(64)]
    gc_collect()
    if fail:
        raise ValueError("retained before error")
    return repr([item.number for item in values]) + str(len(junk))
'''
    assert_persistent_parity(source, tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("helper, expression", [*WRAPPERS, *(("", expression) for expression in MEMBER_READS)])
def test_returned_container_members_survive_wrapper_boundaries(tmp_path, optimize, helper, expression):
    assert_persistent_parity(returned_source(helper, expression), tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, empty, statement", [
    ("list[list[list[int]]]", "[]", "target.append([value])"),
    ("list[list[list[int]]]", "[]", "target.extend([[value]])"),
    ("dict[int, list[list[int]]]", "{}", "target.setdefault(0, [value])"),
])
def test_nested_parameter_stores_retain_scalar_lists(tmp_path, optimize, annotation, empty, statement):
    # Scalar-only members are arena-eligible. Pointer-bearing holders can hide
    # a missing escape summary because they already require traced allocation.
    source = f'''
from pyjs.native import gc_collect
SAVED: list[list[int]] = []
def store(target: {annotation}, value: list[int]) -> {annotation}:
    {statement}
    return target
def render(number: int, fail: bool) -> str:
    target: {annotation} = {empty}
    value = [number]
    SAVED.append(store(target, value)[0][0])
    junk = [[999, 999, 999] for _ in range(64)]
    gc_collect()
    if fail:
        raise ValueError("retained before error")
    return repr(SAVED) + str(len(junk))
'''
    assert_persistent_parity(source, tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, initial, statement, projection", [
    ("list[list[Box]]", "[[]]", "target[0].append(value)", "[0][0]"),
    ("dict[int, list[Box]]", "{0: []}", "target[0].append(value)", "[0][0]"),
    ("list[list[Box]]", "[[]]", "target[0].insert(0, value)", "[0][0]"),
    ("list[list[Box]]", "[[Box(0)]]", "target[0][0] = value", "[0][0]"),
    ("dict[int, dict[int, Box]]", "{0: {}}", "target[0][1] = value", "[0][1]"),
    ("list[list[Box]]", "[[]]", "member = target[0]; member.append(value)", "[0][0]"),
    ("list[list[Box]]", "[[]]", "next(iter(target)).append(value)", "[0][0]"),
    ("dict[int, list[Box]]", "{0: []}", "next(iter(target.values())).append(value)", "[0][0]"),
    ("Registry", "Registry()", "target.items.append(value)", ".items[0]"),
    ("Registry", "Registry()", "target.add(value)", ".items[0]"),
])
def test_entry_member_stores_survive_persistent_calls(
    tmp_path, optimize, annotation, initial, statement, projection,
):
    helper = f'''
class Registry:
    def __init__(self):
        self.items: list[Box] = []
    def add(self, value: Box) -> None:
        self.items.append(value)
def store(target: {annotation}, value: Box) -> None:
    {statement}
def relay(target: {annotation}, value: Box) -> {annotation}:
    store(value=value, target=target)
    return target
def copied(number: int) -> Box:
    target: {annotation} = {initial}
    return relay(target, Box(number)){projection}
'''
    assert_persistent_parity(returned_source(helper, "copied(number)"), tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("helper, expression", [WRAPPERS[0], WRAPPERS[5], WRAPPERS[8]])
def test_returned_container_members_with_sanitizers(tmp_path, optimize, helper, expression):
    source = returned_source(helper, expression) + '''
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
@pytest.mark.parametrize("annotation, initial, getter, member", [
    ("list[list[Box]]", "[[]]", "target[0]", "[0]"),
    ("dict[int, list[Box]]", "{0: []}", "target[0]", "[0]"),
    ("Registry", "Registry()", "target.items", ".items"),
    ("Registry", "Registry()", "target.bucket()", ".items"),
    ("list[list[Box]]", "[[]]", "next(iter(target))", "[0]"),
])
def test_returned_parameter_members_keep_caller_writes(tmp_path, optimize, annotation, initial, getter, member):
    helper = f'''
class Registry:
    def __init__(self):
        self.items: list[Box] = []
    def bucket(self) -> list[Box]:
        return self.items
def bucket(target: {annotation}) -> list[Box]:
    return {getter}
def relay(target: {annotation}) -> list[Box]:
    return bucket(target=target)
def copied(number: int) -> Box:
    target: {annotation} = {initial}
    items = relay(target)
    items.append(Box(number))
    return target{member}[0]
'''
    assert_persistent_parity(returned_source(helper, "copied(number)"), tmp_path, optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("label, body, external", PERSISTENT_ALIAS_CASES,
                         ids=[case[0] for case in PERSISTENT_ALIAS_CASES])
def test_persistent_storage_aliases_across_requests(tmp_path, optimize, label, body, external):
    source = (PERSISTENT_ALIAS_DEFINITIONS + '\nfrom pyjs.native import gc_collect\n'
              'def render(number: int) -> str:\n' + indent(body, '    ') + '''
    junk = [Box(999) for _ in range(64)]
    gc_collect()
    return repr(([item.number for item in SHARED], [item.number for item in MUTABLE[0]])) + str(len(junk))
''')
    namespace = {}
    exec(source, namespace)
    expected = [namespace["render"](number) for number in (1, 2, 3)]
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        actual = []
        for number in (1, 2, 3):
            actual.append(library.render(number))
            assert heap._Heap.from_address(library._heap).roots is None
        assert actual == expected
    finally:
        library.close()


def test_inherited_classmethod_factory_keeps_dynamic_identity_diagnostic(tmp_path):
    source = '''
from dataclasses import dataclass, field
class Base:
    number: int = 1
    @classmethod
    def list(cls) -> list[int]:
        return [cls.number]
class Derived(Base):
    number: int = 2
@dataclass
class Bag:
    items: list[int] = field(default_factory=Derived.list)
def main() -> list[int]:
    return Bag().items
'''
    # Native inherited class methods are not implemented yet. Do not silently
    # resolve this to Base.list or builtin list while constructing a factory.
    namespace = {}
    exec(source, namespace)
    assert namespace["main"]() == [2]
    with pytest.raises(LLVMUnsupported, match="class methods require dynamic class identity"):
        LLVM().compare_with_python(source, directory=tmp_path)
