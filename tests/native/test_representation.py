"""Observable repr/stringification, including callbacks and storage lifetimes."""

import ast

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


def check(source, optimize):
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("name", ["Bag", "object"])
@pytest.mark.parametrize("override_str", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_application_object_keeps_authored_and_inherited_formatting(name, override_str, optimize):
    string_method = '''
            def __str__(self) -> str:
                gc_collect()
                return 'string:' + self.label
    ''' if override_str else ""
    check(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class {name}:
            def __init__(self, label: str):
                self.label = label
            def __repr__(self) -> str:
                gc_collect()
                return 'repr:' + self.label
            {string_method}
        class Child({name}):
            pass
        def main() -> str:
            gc_set_threshold(1)
            values: list[{name}] = [{name}('base'), Child('child')]
            return repr(values) + str(values[0]) + repr(values[1]) + f'{{values[1]}}'
    ''', optimize)


def test_repr_cannot_return_an_application_class_named_str():
    with pytest.raises(LLVMUnsupported, match="representation methods must return str"):
        transpile_llvm('''
            from builtins import str as Text
            class str:
                pass
            class Record:
                def __repr__(self) -> str:
                    return str()
            def main() -> Text:
                return repr(Record())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_application_str_uses_authored_method(optimize):
    check('''
        from builtins import str as Text
        from pyjs.native import gc_collect, gc_set_threshold
        class str:
            def __init__(self, rank: int):
                self.rank = rank
            def __str__(self) -> Text:
                gc_collect()
                return 'S' + Text(self.rank)
        def pick(flag: bool) -> str | None:
            return str(1) if flag else None
        def main() -> Text:
            gc_set_threshold(1)
            return (f'{pick(True)}:{pick(False)}' + '|'
                    + Text(pick(True)) + ':' + Text(pick(False)) + '|'
                    + pick(True).__str__() + ':' + pick(False).__str__())
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["dict[str, int]", "dict[str, float]", "list[dict[str, int]]"])
@pytest.mark.parametrize("generator", [False, True])
def test_mapping_formatting_without_any_mapping_construction(optimize, annotation, generator):
    # Keep each fixture construction-free: an unrelated dictionary allocation
    # would select the missing runtime and hide this dependency regression.
    producer = (f'''
        def values() -> Generator[int, None, {annotation} | None]:
            yield 1

        def result() -> {annotation} | None:
            source = values()
            next(source)
            return source.close()
    ''' if generator else f'''
        def result() -> {annotation} | None:
            return None
    ''')
    check(f'''
        from collections.abc import Generator
        {producer}
        def describe(value: {annotation} | None) -> str:
            print(value)
            return repr(value) + str(value) + ascii(value) + format(value) + f"{{value!r}}:{{value!s}}:{{value!a}}"

        def main() -> str:
            return describe(result())
    ''', optimize)


def test_sequence_formatting_does_not_pull_in_mapping_runtime():
    output = transpile_llvm('''
        def main() -> str:
            return repr([1, 2])
    ''')
    # The full module includes thousands of runtime lines; check only the
    # dependency boundary rather than freezing unrelated generated helpers.
    assert "@pyjs.dict.repr.index" not in output


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_and_nested_representations(optimize):
    check(r'''
        from pyjs import int8, uint32, float32

        def optional(value: str | None) -> str:
            return repr(value)

        def main() -> str:
            strings = ["", "quote'", 'both\'"', "\n\r\t\b\f\x00\x7f", "é中😀", "\u200b\u2028\u00a0"]
            integers: list[int] = []
            values: dict[str, list[int]] = {"x": [1, 2], "y": []}
            return (repr(strings) + str(values) + repr(integers) + repr(("one",))
                    + repr((True, 2.5, b"\x00\xff'", -1))
                    + repr(range(1, 8, 2)) + repr(range(0))
                    + repr(int8(128)) + repr(uint32(-1)) + repr(float32(1.5))
                    + optional("quoted") + optional(None))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_user_methods_virtual_dispatch_and_fstrings(optimize):
    check('''
        class Base:
            def __repr__(self) -> str:
                return "base"

        class Child(Base):
            def __repr__(self) -> str:
                return "child"

            def __str__(self) -> str:
                return "display"

        def describe(value: Base) -> str:
            return repr(value) + str(value)

        def main() -> str:
            value = Child()
            return str(value) + repr(value) + describe(value) + repr([value]) + f"{value!r}|{value!s}"
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_list_callback_cycles_mutation_and_collection(optimize):
    check('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self):
                self.items: list[Item] = []
                self.clear = False

            def __repr__(self) -> str:
                if self.clear:
                    self.items.clear()
                gc_collect()
                return "item(" + repr(self.items) + ")"

        def main() -> str:
            gc_set_threshold(1)
            value = Item()
            value.items.append(value)
            result = repr(value.items)
            value.clear = True
            return result + repr(value.items) + repr(value.items)
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_errors_restore_formatting_scopes(optimize):
    check('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self):
                self.fail = True

            def __repr__(self) -> str:
                gc_collect()
                if self.fail:
                    raise ValueError("representation")
                return "good"

        def main() -> str:
            gc_set_threshold(1)
            value = Item()
            items = [value]
            result = ""
            for _ in range(5):
                try:
                    result += repr(items)
                except ValueError as error:
                    result += str(error)
            value.fail = False
            return result + repr(items)
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_representations_follow_logical_insertions(optimize):
    check('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, name: str, mode: int):
                self.name = name
                self.mode = mode
                self.mapping: dict[str, Item] = {}

            def __repr__(self) -> str:
                mode = self.mode
                self.mode = 0
                if mode == 1:
                    del self.mapping["a"]
                elif mode == 2:
                    self.mapping.clear()
                    self.mapping["x"] = Item("x", 0)
                    self.mapping["y"] = Item("y", 0)
                elif mode == 3:
                    self.mapping.popitem()
                    self.mapping["x"] = Item("x", 0)
                elif mode == 4:
                    self.mapping["b"] = Item("new", 0)
                    self.mapping["x"] = Item("added", 0)
                gc_collect()
                return self.name

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for mode in range(1, 5):
                first = Item("first", mode)
                mapping = {"a": first, "b": Item("second", 0), "c": Item("third", 0)}
                first.mapping = mapping
                result += repr(mapping) + "|" + repr(mapping)
            return result
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_views_snapshot_before_callbacks_and_sets(optimize):
    check('''
        from pyjs.native import gc_collect

        class Item:
            def __init__(self, name: str):
                self.name = name
                self.mapping: dict[str, Item] = {}

            def __repr__(self) -> str:
                self.mapping.clear()
                gc_collect()
                return self.name

        def main() -> str:
            value = Item("first")
            mapping = {"a": value, "b": Item("second")}
            value.mapping = mapping
            result = repr(mapping.keys()) + repr(mapping.items())
            mapping["x"] = value
            result += repr(mapping.values())
            empty: set[int] = set()
            return result + repr(empty) + repr({3})
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_container_detachment_and_fstring_temporaries(optimize):
    check('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self):
                self.outer: list[list[Item]] = []

            def __repr__(self) -> str:
                self.outer.clear()
                gc_collect()
                return "survived"

        def main() -> str:
            gc_set_threshold(1)
            item = Item()
            item.outer = [[item, item]]
            first = repr(item.outer)
            return f"{first + 'new'}:{item!r}:{first + 'last'}"
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_user_repr_is_catchable_and_does_not_poison_later_calls(optimize):
    # Recursion depth and message depend on CPython's call frames. Compare
    # the visible category and recovery, not a backend-specific stack depth.
    check('''
        class Loop:
            def __repr__(self) -> str:
                return repr(self)

        def main() -> str:
            result = ""
            for _ in range(2):
                try:
                    result += repr(Loop())
                except RecursionError:
                    result += "caught"
            return result + repr([1, 2])
    ''', optimize)


@pytest.mark.parametrize("expression", ["repr([])", "repr({})", "repr(())", "str([])", "repr(b'x')", "repr(1)",
                                        "b'x'.__repr__()", "[1].__str__()", "'x'.__repr__()"])
def test_small_standalone_representations(expression):
    check("def main() -> str:\n    return " + expression, 2)


def test_set_representation_preserves_members_without_promising_hash_order():
    result = LLVM().run_source('def main() -> str:\n    return repr({"z", "a", "é", "😀"})')
    assert result.returncode == 0 and result.stderr == ""
    assert ast.literal_eval(result.stdout) == {"z", "a", "é", "😀"}


@pytest.mark.parametrize("expression", ["repr(int)", "repr([int])", "repr({'x': int})"])
def test_representation_class_values_have_located_diagnostics(expression):
    with pytest.raises(LLVMUnsupported, match="class objects.*at line"):
        transpile_llvm("def main() -> str:\n    return " + expression)


@pytest.mark.parametrize("body, diagnostic", [
    ("kind = Item\n    print(kind)", "class objects"),
    ("kind = Item\n    str(kind)", "class objects"),
    ("kind = Item\n    repr(kind)", "class objects"),
    ("kind = Item\n    json.dumps(kind)", "class objects"),
    ("print([Item][0])", "class objects"),
    ("print([kind for kind in [Item]])", "class objects"),
])
def test_indirect_class_values_do_not_create_late_analysis_dependencies(body, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic + ".*at line"):
        transpile_llvm("import json\nclass Item: pass\ndef main() -> int:\n    " + body + "\n    return 0")


def test_ascii_fstring_conversion_is_not_silently_ignored():
    check('def main() -> str:\n    return f"{\'é\'!a}"', 2)


@pytest.mark.parametrize("expression", ["repr([None])", "str({'x': None})", 'f"{[None]}"', "format([None])"])
def test_none_only_collection_formatting(expression):
    check("def main() -> str:\n    return " + expression, 2)


@pytest.mark.parametrize("result_type, result", [("int", "1"), ("str | None", "None")])
def test_formatting_method_result_requires_str(result_type, result):
    with pytest.raises(LLVMUnsupported, match="representation methods must return str.*at line"):
        transpile_llvm(f"class Item:\n    def __repr__(self) -> {result_type}:\n        return {result}\n"
                       "def main() -> str:\n    return repr(Item())")


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_repr_does_not_call_str_override(optimize):
    check('''
        class Item:
            def __str__(self) -> str: return "display"
        def main() -> str:
            value = Item()
            return str((str(value) == "display", "Item object at 0x" in repr(value),
                        "display" not in repr(value)))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_base_formatting_reaches_subclass_repr(optimize):
    check('''
        class Base:
            pass
        class Child(Base):
            def __repr__(self) -> str:
                return "child"
        def describe(value: Base) -> str:
            return repr(value)
        def main() -> str:
            return describe(Child())
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_default_object_repr_has_runtime_name_stable_identity_and_nested_support(optimize):
    check('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base: pass
        class Child(Base): pass
        def render(value: Base) -> str: return repr(value)
        def erased(value: object) -> str: return repr(value)
        def main() -> str:
            gc_set_threshold(1)
            base = Base()
            child = Child()
            first = repr(base)
            gc_collect()
            child_text = render(child)
            nested = repr([base, child])
            return str(("Base object at 0x" in first, first.endswith(">"),
                        str(base) == first, base.__repr__() == first,
                        "Child object at 0x" in child_text, child_text != first,
                        erased(child) == child_text, first in nested, child_text in nested))
    ''', optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_str_delegates_to_runtime_repr_from_super(optimize):
    check('''
        class Item:
            def __repr__(self) -> str:
                return "item"
            def __str__(self) -> str:
                return super().__str__()
        class Child(Item):
            def __repr__(self) -> str:
                return "child"
        def main() -> str:
            return str(Item()) + str(Child())
    ''', optimize)


def test_repr_does_not_reach_unused_str_method():
    check('''
        class Item:
            def __repr__(self) -> str:
                return "item"

            def __str__(self) -> str:
                return open("not-a-native-operation").read()

        def main() -> str:
            return repr([Item()])
    ''', 2)


@pytest.mark.parametrize("expression", ["repr(Child()) + str(Child())", "str(Child())"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_super_formatting_keeps_static_dispatch(expression, optimize):
    check(f'''
        class Base:
            def __repr__(self) -> str:
                return "base"

        class Child(Base):
            def __repr__(self) -> str:
                return "child:" + super().__repr__()

            def __str__(self) -> str:
                return "display:" + super().__str__()

        def main() -> str:
            return {expression}
    ''', optimize)


@pytest.mark.parametrize("base", ["object", "Base"])
@pytest.mark.parametrize("receiver", ["super()", "alias", "(super() if True else alias)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_super_str_alone_retains_runtime_repr(base, receiver, optimize):
    check(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Child({base}):
            def __repr__(self) -> str:
                gc_collect()
                return "child"
            def __str__(self) -> str:
                parent = super()
                alias = parent
                return "display:" + {receiver}.__str__()
        class Grandchild(Child):
            def __repr__(self) -> str:
                gc_collect()
                return "grandchild"
        def describe(value: Child) -> str:
            return str(value)
        def main() -> str:
            gc_set_threshold(1)
            return describe(Child()) + describe(Grandchild())
    ''', optimize)


@pytest.mark.parametrize("base", ["object", "Base"])
def test_default_super_repr_has_a_located_diagnostic(base):
    with pytest.raises(LLVMUnsupported, match="explicit object.__repr__ requires default object formatting") as caught:
        transpile_llvm(f'''
            class Base:
                pass
            class Child({base}):
                def __repr__(self) -> str:
                    return "child:" + super().__repr__()[:1]
            def main() -> str:
                return repr(Child())
        ''')
    assert ast.unparse(caught.value.node) == "super().__repr__()"


def test_optional_str_reaches_only_the_selected_method():
    check('''
        class Item:
            def __str__(self) -> str:
                return "display"

            def __repr__(self) -> str:
                return open("unused").read()

        def describe(value: Item | None) -> str:
            return str(value)

        def main() -> str:
            return describe(Item()) + describe(None)
    ''', 2)


@pytest.mark.parametrize("optimize", [0, 2])
def test_formatting_methods_bind_defaults_of_actual_target(optimize):
    check('''
        class Base:
            def __repr__(self, indent: int = 1) -> str:
                return " " * indent + "base"

        class Child(Base):
            def __str__(self, *, prefix: str = "child:") -> str:
                return prefix + super().__repr__()

        def describe(value: Base) -> str:
            return str(value) + repr(value) + f"{value}|{value!r}"

        def main() -> str:
            value = Child()
            return (describe(value) + value.__str__() + value.__str__(prefix="explicit:")
                    + value.__repr__() + value.__repr__(2))
    ''', optimize)


@pytest.mark.parametrize("expression", ['f"{value!r}"', 'f"{value}"', 'f"{[value]}"'])
def test_unsupported_fstring_keeps_source_location(expression):
    # Native LLVM diagnostics use the analyzed function's local line numbers.
    with pytest.raises(LLVMUnsupported, match="representation methods must return str.*at line 3"):
        transpile_llvm("class Item:\n    def __repr__(self) -> int: return 1\n"
                       "def main() -> str:\n    value = Item()\n    return " + expression)


def test_renderer_library_formats_python_inputs_repeatedly(tmp_path):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect, gc_set_threshold

        def render(values: list[str | None]) -> str:
            gc_set_threshold(1)
            result = repr(values)
            gc_collect()
            return result
    ''', tmp_path, entry_point="render")
    results = []
    for index in range(12):
        values = ["é😀'\\\"" * (index * 30), None, str(index)]
        results.append(library.render(values))
        assert results[-1] == repr(values)
    assert results[0] == "['', None, '0']"


@pytest.mark.parametrize("optimize", [0, 2])
def test_representation_allocation_failure_and_recovery(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            for attempt in range(1, 100):
                values: dict[str, list[str]] = {"x": ["é" * 100, "quoted'"], "y": []}
                arm(attempt)
                complete = False
                try:
                    result = repr(values)
                    arm(0)
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                recovered = repr(values)
                assert recovered.startswith("{'x': ['") and recovered.endswith("'y': []}")
                if complete:
                    assert result == recovered and failures > 0
                    return 0
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)
