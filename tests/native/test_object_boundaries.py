import subprocess
import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_argument_conversion_uses_argument_not_call_result_representation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        def inspect(value: object) -> int8:
            return int8(7 if isinstance(value, int) else 3)
        def main() -> int:
            return int(inspect(42))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_object_none_comparisons_keep_presence_semantics(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        def present(value: object | None) -> bool:
            return value != None
        def main() -> str:
            values: list[object | None] = [None, "a"]
            mapping: dict[str, object] = {"a": 1}
            return str((None in values, values.count(None), mapping.get("a") == None,
                        mapping.get("b") == None, mapping.get("b") != None,
                        present(None), present(0), present("")))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_bare_collection_narrowing_allows_header_queries_without_inventing_item_layout(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Holder:
            def __init__(self, value: object): self.value = value
            @property
            def item(self) -> object:
                gc_collect()
                return self.value
        def query(value: object) -> str:
            if isinstance(value, list):
                return str((len(value), bool(value), value.__len__(), isinstance(value, list)))
            if isinstance(value, dict): return str((len(value), bool(value)))
            if isinstance(value, set): return str((len(value), bool(value)))
            if isinstance(value, frozenset): return str((len(value), bool(value)))
            return "other"
        def read(holder: Holder) -> str:
            result = ""
            if isinstance(holder.value, list): result += str(len(holder.value))
            if isinstance(holder.item, list): result += str(len(holder.item))
            return result
        def main() -> str:
            gc_set_threshold(1)
            small: list[int8] = [int8(-1)]
            output = query([1, 2]) + query([True]) + query(small) + query(list[int]())
            output += query({'a': 1}) + query({2}) + query(frozenset({3}))
            return output + read(Holder([1, 2, 3]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_header_queries_still_check_stale_kinds_and_explicit_cast_layouts(tmp_path, optimize):
    result = LLVM().run_source('''
        from typing import cast
        class Holder:
            def __init__(self): self.value: object = [True]
        def change(holder: Holder) -> None: holder.value = 42
        def main() -> int:
            holder = Holder()
            checked = 0
            try:
                len(cast(list[int], holder.value))
            except TypeError:
                checked += 1
            if isinstance(holder.value, list):
                change(holder)
                try:
                    len(holder.value)
                except TypeError:
                    checked += 1
            return 0 if checked == 2 else 1
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0 and result.stderr == ""


@pytest.mark.parametrize("numeric,value", [("int8", "200"), ("uint8", "250"), ("float32", "0.1")])
@pytest.mark.parametrize("declaration", [
    "values: list[object] = [VALUE]",
    "values: tuple[object, str] = (VALUE, 'text')",
    "values: dict[str, object] = {'value': VALUE}",
])
def test_object_collection_literals_require_explicit_scalar_conversion(numeric, value, declaration):
    with pytest.raises((CompilationError, LLVMUnsupported), match="represent|explicit int"):
        transpile_llvm(f"from pyjs import {numeric}\ndef main() -> int:\n    "
                      + declaration.replace("VALUE", f"{numeric}({value})") + "\n    return len(values)")


@pytest.mark.parametrize("numeric,value", [("int8", "100"), ("uint8", "250"), ("float32", "0.1")])
@pytest.mark.parametrize("boundary", ["argument", "local", "return", "cast", "expanded"])
def test_represented_scalar_erasure_requires_explicit_conversion(numeric, value, boundary):
    declarations = {
        "argument": "def erase(value: object) -> object: return value",
        "local": f"def erase(value: {numeric}) -> object:\n    result: object = value\n    return result",
        "return": f"def erase(value: {numeric}) -> object: return value",
        "cast": f"def erase(value: {numeric}) -> object: return cast(object, value)",
        "expanded": "def erase(value: object) -> object: return value",
    }
    argument = f"{numeric}({value})"
    invocation = f"erase(*[{argument}])" if boundary == "expanded" else f"erase({argument})"
    with pytest.raises((CompilationError, LLVMUnsupported), match="represented|representation"):
        transpile_llvm(f"from pyjs import {numeric}\nfrom typing import cast\n"
                      + declarations[boundary] + f"\ndef main() -> int:\n    {invocation}\n    return 0")


@pytest.mark.parametrize("source", [
    "from typing import cast\ndef main() -> int: return cast(list[int], [True] * 9)[8]",
    '''
from typing import cast
class Base:
    def __init__(self): self.x = 1
class Child(Base):
    def __init__(self):
        super().__init__()
        self.text = "child"
def main() -> str:
    unused = Child()
    return cast(Child, Base()).text
''',
])
def test_incompatible_concrete_casts_are_diagnosed_before_memory_access(source):
    with pytest.raises(LLVMUnsupported, match="cast|layout|storage"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_properties_project_payloads_and_recheck_stale_proofs(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self, text: str): self.text = text
        class Holder:
            def __init__(self, value: object): self.value = value
            @property
            def item(self) -> object:
                gc_collect()
                return self.value
        def change(holder: Holder) -> None:
            holder.value = None
            gc_collect()
        def read(holder: Holder) -> str:
            if isinstance(holder.item, str):
                return str(len(holder.item))
            if isinstance(holder.item, int):
                return str(holder.item)
            if isinstance(holder.item, Item):
                change(holder)
                try:
                    return holder.item.text
                except Exception:
                    return "checked"
            return "other"
        def main() -> str:
            gc_set_threshold(1)
            return read(Holder("abc")) + read(Holder(True)) + read(Holder(Item("text")))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_float_only_in_erased_cast_still_emits_required_runtime(tmp_path, optimize):
    # The physical cast is intentionally stricter than CPython typing.cast.
    result = LLVM().run_source('''
        from typing import cast
        def read(value: object) -> str:
            try:
                return str(cast(list[float], value))
            except TypeError:
                return "checked"
        def main() -> str:
            return read([1, 2])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "checked"
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_collection_slots_box_literals_mutations_and_defaults(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def make(value: str) -> str:
            gc_collect()
            return value + "!"
        def read(value: object) -> str:
            if isinstance(value, str): return value
            if isinstance(value, int): return str(int(value))
            return "none"
        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = [make("a"), make("b"), 3]
            mapping: dict[str, object] = {"a": make("c"), "b": make("d")}
            pair: tuple[object, object] = (make("e"), 4)
            values.append("f")
            values.insert(1, 7)
            values[0] = 9
            mapping["a"] = 8
            mapping.setdefault("missing")
            output = ""
            gc_collect()
            for value in values: output += read(value)
            for key, value in mapping.items(): output += key + read(value)
            output += read(pair[0]) + read(pair[1])
            output += read(mapping.get("absent", 12)) + read(mapping.pop("absent", "fallback"))
            output += read(mapping.setdefault("absent", "new")) + read(mapping["absent"])
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_object_collection_box_failure_preserves_existing_contents(tmp_path, optimize, managed):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        def read(value: object) -> int:
            if isinstance(value, int): return int(value)
            return -1
        def main() -> int:
            values: list[object] = [7]
            mapping: dict[str, object] = {{"value": 8}}
            for mode in range(6):
                for repeat in range(4):
                    caught = False
                    arm(1)
                    try:
                        if mode == 0: values[0] = 42
                        elif mode == 1: values.append(42)
                        elif mode == 2: values.insert(0, 42)
                        elif mode == 3: mapping["value"] = 42
                        elif mode == 4: mapping.setdefault("new", 42)
                        else: values = [42, 43]
                    except MemoryError:
                        caught = True
                    arm(0)
                    {'gc_collect()' if managed else 'pass'}
                    if not caught or len(values) != 1 or read(values[0]) != 7:
                        return 1
                    if len(mapping) != 1 or read(mapping["value"]) != 8:
                        return 2
            values.append(9)
            mapping.setdefault("new", 10)
            {'gc_collect()' if managed else 'pass'}
            return 0 if read(values[1]) == 9 and read(mapping["new"]) == 10 else 3
    ''')
    run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)


def test_concrete_upcasts_and_matching_container_casts_remain_supported(tmp_path):
    LLVM().assert_matches_python('''
        from typing import cast
        class Base:
            def __init__(self, x: int): self.x = x
        class Child(Base): pass
        def main() -> int:
            values = cast(list[int], [1, 2])
            item = cast(Base, Child(40))
            return item.x + values[1]
    ''', directory=tmp_path)


def test_object_union_defaults_keep_erased_truth_and_kind(tmp_path):
    LLVM().assert_matches_python('''
        def identity(value: object | int) -> object | int:
            return value
        def main() -> str:
            values: dict[str, object] = {"empty": "", "text": "yes"}
            defaulted = values.get("absent", 2)
            return str((isinstance(values.get("text", 2), str),
                        isinstance(values.get("absent", 2), int),
                        bool(values.get("empty", 2)), bool(values.get("absent", 2)),
                        isinstance(identity(True), bool), isinstance(identity("yes"), str),
                        isinstance(defaulted, int), bool(defaulted)))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_overload_results_project_before_direct_consumption(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import overload
        from pyjs.native import gc_collect, gc_set_threshold
        class Item:
            def __init__(self, x: int): self.x = x
        @overload
        def text(value: int) -> str: ...
        def text(value: int) -> object:
            gc_collect()
            return "abc" if value else None
        @overload
        def number(value: int) -> int: ...
        def number(value: int) -> object:
            gc_collect()
            return True if value else 7
        @overload
        def record(value: int) -> Item: ...
        def record(value: int) -> object:
            gc_collect()
            return Item(value)
        def main() -> str:
            gc_set_threshold(1)
            value = number(1)
            checked = False
            try:
                len(text(0))
            except TypeError:
                checked = True
            return str((len(text(1)), text(1)[2], str(value), isinstance(value, bool),
                        int(number(0)), record(5).x, checked))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_collection_equality_matches_python(tmp_path, optimize):
    # These formerly unsupported consumers now share erased comparison. Check
    # their observable results together instead of retaining obsolete negatives.
    result = LLVM().assert_matches_python('''
        def erase(value: object) -> object: return value
        def main() -> str:
            erased = erase(1)
            values: list[object] = [erased, 'x']
            mapping: dict[str, object] = {'value': erased}
            pair: tuple[object, str] = (erased, 'x')
            text = erase('a')
            checks = (1 in values, values.count(1), values.index(1), 'x' in values,
                      1 in mapping.values(), pair == (1, 'x'),
                      mapping.get('value', 0) == 1, True in [True, erased],
                      [True, erased] == [True, erased], text in ['a'], text in ('a',))
            removed = values.remove(1)
            return str(checks) + str(removed) + str(values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "key in {'a'}", "key in mapping", "mapping[key]",
])
def test_erased_hashed_lookup_never_reads_an_object_box_as_text(expression):
    with pytest.raises(LLVMUnsupported, match="erased object (equality|keys)"):
        transpile_llvm(f'''
            def erase(value: object) -> object: return value
            def main() -> int:
                key = erase('a')
                mapping = {{'a': 1}}
                {expression}
                return 0
        ''')


@pytest.mark.parametrize("expression", [
    "mapping.get(key)", "mapping.pop(key)", "mapping.pop(key, 0)",
    "del mapping[key]", "mapping[key] = 2", "['a'].count(key)",
])
def test_typed_collection_methods_reject_erased_keys_during_analysis(expression):
    with pytest.raises(CompilationError, match="expects str, got object"):
        transpile_llvm(f'''
            def erase(value: object) -> object: return value
            def main() -> int:
                key = erase('a')
                mapping = {{'a': 1}}
                {expression}
                return 0
        ''')


@pytest.mark.parametrize("body", [
    "return int", "return take(int)", "return User",
    "return User is take(1)", "return take(1) is User",
])
def test_class_values_diagnose_before_local_slot_lookup(body):
    with pytest.raises(LLVMUnsupported, match="class objects are not runtime values"):
        transpile_llvm(f'''
            class User: pass
            def take(value: object) -> object: return value
            def main() -> object: {body}
        ''')


@pytest.mark.parametrize("body", [
    "return str(ValueError in ['a'])",
    "return str(ValueError in {'a': 1})",
    "return str(ValueError in {'a'})",
    "return str(ValueError is take(1))",
    "return str(ValueError is not take('a'))",
    "return str(take(ValueError) is ValueError)",
    "return str(token() is ValueError)",
    "return str(ValueError is values(False))",
    "return str(values(True) is ValueError)",
    "return str(ValueError is Item())",
    "return str(Item() is not ValueError)",
    "return str(take(ValueError) is Item())",
    "Item(); return str(ValueError is values(False))",
    "Item(); return str(values(True) is not ValueError)",
    "return str(elements(True) is ValueError) + str(ValueError is not elements(False))",
])
def test_exception_tokens_are_not_instance_boxes_on_a_cold_compile(body):
    # Keep the original no-DOM cold process as well as reached DOM controls.
    prelude = '''
from pyjs.web.domx import CustomElement
class Item(CustomElement):
    pass
def elements(flag: bool) -> Item | str:
    return Item() if flag else "s"
''' if "Item()" in body or "elements(" in body else ""
    source = prelude + f'''
def take(value: object) -> object: return value
def token() -> object: return ValueError
def values(flag: bool) -> str | list[str]: return "a" if flag else ["a"]
def main() -> str:
    {body}
'''
    script = f'''
from pyjs.tooling.llvm import LLVM
for optimize in (0, 2):
    result = LLVM().assert_matches_python({source!r}, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert not result.native.stderr, result.native.stderr
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("needle, haystack", [
    ("'a'", "'abc'"), ("''", "'abc'"), ("1", "'abc'"),
    ("b'a'", "b'abc'"), ("97", "b'abc'"), ("'a'", "b'abc'"),
])
def test_erased_text_membership_never_reinterprets_box_storage(needle, haystack):
    with pytest.raises(LLVMUnsupported, match="erased text membership requires narrowing"):
        transpile_llvm(f'''
            def erase(value: object) -> object: return value
            def main() -> int:
                return int(erase({needle}) in {haystack})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_membership_accepts_literal_refinements(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Literal
        def text(needle: Literal['a', 'q']) -> bool:
            return needle in 'abc'
        def choose() -> Literal['b']:
            return 'b'
        def byte(needle: int) -> bool:
            return needle in b'abc'
        def boolean(needle: bool) -> bool:
            return needle in b'\\x01'
        def main() -> str:
            return str((text('a'), text('q'), choose() in 'abc',
                        byte(97), byte(120), boolean(True)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "token(events) is ValueError is token(events)",
    "ValueError is token(events) is ValueError",
    "token(events) is not KeyError is not token(events)",
    "token(events) is KeyError is token(events)",
])
def test_chained_exception_token_identity_is_cold_safe(expression):
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold
def token(events: list[int]) -> object:
    events.append(1)
    gc_collect()
    return ValueError
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    matched = {expression}
    return str((matched, events))
'''
    script = f'''
from pyjs.tooling.llvm import LLVM
for optimize in (0, 2):
    result = LLVM().assert_matches_python({source!r}, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert not result.native.stderr, result.native.stderr
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("kind, haystack, present, absent", [
    ("str", "'abc'", "'ab'", "'z'"),
    ("bytes", "b'abc'", "b'ab'", "b'z'"),
    ("int", "b'abc'", "97", "0"),
    ("bool", "b'\\x01'", "True", "False"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_text_needles_check_presence_before_reading_payload(tmp_path, kind, haystack, present, absent, optimize):
    result = LLVM().assert_matches_python(f'''
        def contains(needle: {kind} | None) -> str:
            try:
                return str(needle in {haystack})
            except TypeError as error:
                return str(error)
        def main() -> str:
            return contains({present}) + '|' + contains({absent}) + '|' + contains(None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("collection", ["tuple[str]", "tuple[str, ...]"])
def test_tuple_class_token_search_has_a_cold_diagnostic(collection):
    source = f'''
def search(values: {collection}) -> bool:
    return ValueError in values
def main() -> int:
    return int(search(('a',)))
'''
    script = f'''
from pyjs.native.llvm import transpile_llvm, LLVMUnsupported
for attempt in range(2):
    try:
        transpile_llvm({source!r})
    except LLVMUnsupported as error:
        assert 'tuple/view searches do not support class-token needles' in str(error), error
    else:
        raise AssertionError('expected unsupported class-token search')
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_view_class_token_search_matches_python(tmp_path, optimize):
    # Mapping views already support incompatible key domains as a false
    # membership result. Keep this distinct from unsupported tuple needles.
    result = LLVM().assert_matches_python('''
        def search(values: dict[str, int]) -> bool:
            return ValueError in values.keys()
        def main() -> str:
            return str((search({'a': 1}), search({})))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "(False, False)"
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", [
    "str([True, erased])", "str(values)", "repr((1, erased))",
    "str(mapping.get('value', 'default'))", "str(mapping.get('absent', 1))",
    "f'{erased}'",
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_union_formatting_keeps_erased_storage(tmp_path, expression, optimize):
    result = LLVM().assert_matches_python(f'''
        def erase(value: object) -> object: return value
        def main() -> str:
            erased = erase(1)
            values: list[int | object] = [1, erased]
            mapping: dict[str, object] = {{'value': erased}}
            return {expression}
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", ["hash(value)", "int(value)", "float(value)", "len(value)"])
def test_erased_union_scalar_consumers_diagnose_before_closed_union_dispatch(expression):
    with pytest.raises(LLVMUnsupported, match="erased object.*require"):
        transpile_llvm(f'''
            def erase(value: object) -> object: return value
            def main() -> int:
                mapping: dict[str, object] = {{'value': erase(1)}}
                value = mapping.get('value', 2)
                {expression}
                return 0
        ''')


@pytest.mark.parametrize("selected, first, second", [
    ("str | None", '"abc"', "None"),
    ("int | str", "42", '"abc"'),
    ("list[int] | None", "[42]", "None"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_overload_union_results_use_checked_projection(tmp_path, optimize, selected, first, second):
    result = LLVM().assert_matches_python(f'''
        from typing import overload
        from pyjs.native import gc_collect, gc_set_threshold
        @overload
        def read(value: int) -> {selected}: ...
        def read(value: int) -> object:
            gc_collect()
            return {first} if value else {second}
        def main() -> str:
            gc_set_threshold(1)
            return repr([read(0), read(1), read(0)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize(("actual", "selected", "value", "diagnostic"), [
    ("list[int] | int", "list[str]", "[1]", "matching concrete item storage and element types"),
    ("list[int] | int", "list[str] | str", "[1]", "matching concrete item storage and element types"),
    ("list[int] | int", "list[str] | None", "[1]", "matching concrete item storage and element types"),
    ("dict[str, int] | int", "dict[str, str] | None", "{'a': 1}", "matching concrete item storage and element types"),
    ("list[list[int]] | int", "list[list[str]] | None", "[[1]]", "matching concrete item storage and element types"),
    ("list[int8] | int", "list[int64] | str", "[int8(1)]", "matching representations"),
    ("list[int8] | int", "list[int64] | None", "[int8(1)]", "matching representations"),
    ("list[int]", "list[str]", "[1]", "matching concrete item storage and element types"),
    ("list[int]", "list[str] | None", "[1]", "matching concrete item storage and element types"),
    ("list[int] | None", "list[str]", "[1]", "matching concrete item storage and element types"),
    ("list[int] | None", "list[str] | None", "[1]", "matching concrete item storage and element types"),
    ("list[int8] | None", "list[int64] | None", "[int8(1)]", "matching representations"),
    ("list[int8]", "list[int64]", "[int8(1)]", "matching representations"),
    ("str", "list[int]", "'abc'", "compatible concrete types"),
    ("str | None", "bytes | None", "'abc'", "compatible concrete types"),
    ("None", "list[int]", "None", "compatible concrete types"),
])
def test_union_overload_projection_rejects_payload_reinterpretation(actual, selected, value, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(f'''
            from typing import overload
            from pyjs import int8, int64
            @overload
            def read(kind: int) -> {selected}: ...
            @overload
            def read(kind: str) -> {actual}: ...
            def read(kind: int | str) -> {actual}: return {value}
            def main() -> str: return str(read(0))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_overload_projection_preserves_matching_concrete_and_optional_storage(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from typing import overload
        from pyjs import int8
        @overload
        def tagged(kind: int) -> list[int]: ...
        @overload
        def tagged(kind: str) -> list[int] | int: ...
        def tagged(kind: int | str) -> list[int] | int: return [4, 7]
        @overload
        def optional(kind: int) -> list[int]: ...
        @overload
        def optional(kind: str) -> list[int] | None: ...
        def optional(kind: int | str) -> list[int] | None: return [8, 9]
        @overload
        def pointer(kind: int) -> list[int8] | None: ...
        @overload
        def pointer(kind: str) -> list[int8]: ...
        def pointer(kind: int | str) -> list[int8]: return [int8(100), int8(30)]
        @overload
        def flag(kind: int) -> int: ...
        @overload
        def flag(kind: str) -> bool: ...
        def flag(kind: int | str) -> bool: return True
        @overload
        def absent(kind: int) -> list[int] | None: ...
        @overload
        def absent(kind: str) -> None: ...
        def absent(kind: int | str) -> None: return None
        def main() -> str:
            value = pointer(0)
            if value is not None:
                return str((sum(tagged(0)), sum(optional(0)), int(sum(value, int8(0))),
                            flag(0) + 1, absent(0) is None))
            return 'missing'
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_overload_optional_results_can_select_none(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from typing import Callable, overload
        @overload
        def text(key: int) -> str: ...
        @overload
        def text(key: None) -> None: ...
        def text(key: int | None) -> str | None:
            return None if key is None else 'v' + str(key)
        @overload
        def items(key: int) -> list[int]: ...
        @overload
        def items(key: None) -> None: ...
        def items(key: int | None) -> list[int] | None:
            return None if key is None else [key]
        @overload
        def number(key: int) -> int: ...
        @overload
        def number(key: None) -> None: ...
        def number(key: int | None) -> int | None:
            return None if key is None else key + 1
        @overload
        def callback(key: int) -> Callable[[int], int]: ...
        @overload
        def callback(key: None) -> None: ...
        def callback(key: int | None) -> Callable[[int], int] | None:
            if key is None: return None
            return lambda value: value + 1
        def main() -> str:
            return str((text(None) is None, items(None) is None, number(None) is None,
                        callback(None) is None, text(3), items(3)[0], number(3), callback(1)(3)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_overload_and_self_results_check_application_subclasses(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from typing import overload, Self
        class Base:
            def __init__(self): self.n = 1
            def bump(self) -> Self:
                self.n += 1
                return self
            def name(self) -> str: return 'base'
        class Derived(Base):
            def __init__(self):
                super().__init__()
                self.extra = 7
            def name(self) -> str: return 'derived'
            def detail(self) -> str: return str(self.n) + ':' + str(self.extra)
        @overload
        def make(kind: int) -> Derived: ...
        @overload
        def make(kind: str) -> Base: ...
        def make(kind: int | str) -> Base:
            return Derived() if isinstance(kind, int) else Base()
        @overload
        def optional(kind: int) -> Derived | None: ...
        @overload
        def optional(kind: str) -> Base | None: ...
        def optional(kind: int | str) -> Base | None:
            return Derived() if kind == 1 else None
        def main() -> str:
            value = Derived().bump()
            base: Base = Derived().bump()
            maybe = optional(1)
            extra = maybe.extra if maybe is not None else 0
            return str((value.detail(), base.n, make(1).name(), make(1).extra,
                        make('x').name(), extra, optional(0) is None))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_overload_result_guards_reject_incorrect_none_and_subclass(tmp_path, optimize):
    result = LLVM().run_source('''
        from typing import overload
        class Base:
            def __init__(self): self.n = 1
        class Derived(Base):
            def __init__(self):
                super().__init__()
                self.extra = 7
        @overload
        def absent(kind: int) -> None: ...
        def absent(kind: int) -> str | None: return 'present'
        @overload
        def child(kind: int) -> Derived: ...
        def child(kind: int) -> Base: return Base()
        @overload
        def maybe_child(kind: int) -> Derived | None: ...
        def maybe_child(kind: int) -> Base | None: return Base()
        def main() -> str:
            Derived()  # Materialize the selected layout independently of the lying body.
            events: list[str] = []
            try: absent(0)
            except TypeError: events.append('presence')
            try: child(0).extra
            except TypeError: events.append('class')
            try: maybe_child(0)
            except TypeError: events.append('optional class')
            return str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # The overload bodies deliberately violate their selected signatures.
    assert result.returncode == 0
    assert result.stdout == "['presence', 'class', 'optional class']"
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("actual", "selected"), [
    ("tuple[Derived]", "tuple[Base]"),
    ("tuple[Derived]", "tuple[Base, ...]"),
    ("tuple[Derived, Base]", "tuple[Base, ...]"),
    ("tuple[Derived, ...]", "tuple[Base, ...]"),
    ("tuple[tuple[Derived]]", "tuple[tuple[Base]]"),
])
def test_overload_tuple_results_preserve_application_upcasts(tmp_path, optimize, actual, selected):
    nested = actual == "tuple[tuple[Derived]]"
    value = ("((Derived(5),),)" if nested else "(Derived(5), Base(7))"
             if actual == "tuple[Derived, Base]" else "(Derived(5),)")
    comparison = LLVM().assert_matches_python(f'''
        from typing import overload
        class Base:
            def __init__(self, value: int): self.value = value
        class Derived(Base):
            def label(self) -> str: return 'derived'
        @overload
        def read(kind: int) -> {selected}: ...
        @overload
        def read(kind: str) -> {actual}: ...
        def read(kind: int | str) -> {actual}:
            return {value}
        def main() -> str:
            item = read(0)[0]{'[0]' if nested else ''}
            total = 0
            for entry in read(0){'[0]' if nested else ''}:
                total += entry.value
            return str((item.value, total))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("actual", "selected", "value"), [
    ("tuple[Base]", "tuple[Derived]", "(Base(),)"),
    ("tuple[Base, ...]", "tuple[Derived]", "(Base(),)"),
    ("tuple[list[Derived]]", "tuple[list[Base]]", "([Derived()],)"),
])
def test_overload_tuple_results_reject_item_downcasts_and_mutable_covariance(actual, selected, value):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
            from typing import overload
            class Base: pass
            class Derived(Base): pass
            @overload
            def read(kind: int) -> {selected}: ...
            def read(kind: int) -> {actual}: return {value}
            def main() -> str:
                Derived()
                return str(read(0))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_overload_optional_projection_preserves_matching_payloads(tmp_path, optimize):
    result = LLVM().run_source('''
        from typing import overload
        @overload
        def read(kind: int) -> list[int] | None: ...
        @overload
        def read(kind: str) -> list[int] | int | None: ...
        def read(kind: int | str) -> list[int] | int | None:
            if kind == 0: return [4, 7]
            if kind == 1: return None
            return 9
        def main() -> str:
            events: list[str] = []
            for kind in range(3):
                try:
                    value = read(kind)
                    if value is None: events.append('none')
                    else: events.append(str(sum(value)))
                except TypeError:
                    events.append('checked')
            return str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # CPython overloads are unchecked; native must reject the integer result
    # without treating its bits as an optional container pointer.
    assert result.returncode == 0
    assert result.stdout == "['11', 'none', 'checked']"
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_conditional_boxes_only_selected_arm(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        events: list[str] = []
        def text(value: str) -> str:
            events.append(value)
            gc_collect()
            return value
        def choose(flag: bool, value: object, fallback: str) -> object:
            return value if flag else text(fallback)
        def reverse(flag: bool, value: object) -> object:
            return text("first") if flag else value
        def main() -> str:
            gc_set_threshold(1)
            empty = choose(False, None, "")
            full = choose(False, None, "fallback")
            kept = choose(True, 42, "not evaluated")
            first = reverse(True, None)
            missing = reverse(False, None)
            return str((isinstance(empty, str), bool(empty), isinstance(full, str),
                        bool(full), isinstance(kept, int), isinstance(first, str),
                        missing is None, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
