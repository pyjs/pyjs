import ast

import pytest

from pyjs.analysis.analyzer import JS_ENVIRONMENT, analyzed_value_type
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.objects import UnionType, same_analyzer_type
from pyjs.analysis.source import analyze_source
from pyjs.analysis.type_relations import (
    contextual_collection_type,
    is_isinstance_match,
    is_subclass,
)
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import assert_module_analysis_transpile, assert_module_transpile
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

ENVIRONMENTS = [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT]


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("expression", ["ordered(values)", "standard.sorted(values)"])
def test_imported_sorted_uses_the_selected_builtin_model(environment, expression):
    from pyjs.python.native import _sorted

    with analyze_source(f'''
        import builtins as standard
        from builtins import sorted as ordered
        def sorted(values: list[int]) -> list[int]:
            return []
        def main(values: list[int]) -> list[int]:
            return {expression}
    ''', wrap=False, environment=environment) as analysis:
        if environment is JVM_ENVIRONMENT:
            assert analysis.types == (
                "def main(values: list__int) -> list[int]:\n"
                "    block entry:\n"
                "        return load_field(new[local] Sorted__list__int_int(values), result)"
            )
            return
        target = "standard.sorted" if expression.startswith("standard.") else "sorted"
        assert analysis.types == (
            "def main(values: list__int) -> list[int]:\n"
            "    block entry:\n"
            f"        return {target}(values)"
        )
        returned = analysis.entry_point.ir.blocks[0].body[-1].value
        assert returned.func.obj.py_func is _sorted


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("member", ["WebElement", "missing", "open"])
def test_builtin_module_does_not_expose_backend_only_or_unmodeled_members(environment, member):
    with pytest.raises(CompilationError, match=f"has no attribute '{member}'"):
        with analyze_source(f'''
            import builtins as standard
            def main() -> object:
                return standard.{member}
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("scalar,nested", [("int8", "int64"), ("int64", "int8")])
def test_dynamic_literal_contexts_keep_both_analyzed_storage_contracts(environment, scalar, nested):
    with analyze_source(f'''
        from pyjs import int8, int64
        def main(values: list[{scalar} | list[{nested}]], index: object, number: int) -> None:
            values[index] = [number, 2]
    ''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        statements = ([statement for block in function.ir.blocks for statement in block.body]
                      if getattr(function, "ir", None) else function.body)
        setters = [node for statement in statements for node in ast.walk(statement)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "__setitem__"]
        assert len(setters) == 2
        sliced, item = setters
        destination = analyzed_representation(sliced.func.value).arguments[0]
        assert analyzed_representation(sliced.args[1]).arguments[0] == destination
        assert analyzed_representation(item.args[1]).arguments[0].numeric.bits == int(nested[3:])
        # Contextual copies must not stamp the original ordinary parameter.
        assert analysis.entry_point.params[2].representation is None


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("ordinary,portable", [("int", "int8"), ("float", "float32")])
def test_dynamic_mixed_scalars_keep_copied_and_source_representations(environment, ordinary, portable):
    with analyze_source(f'''
        from pyjs import {portable}
        def main(values: list[{portable} | str], index: object, rhs: {ordinary} | str) -> None:
            values[index] = rhs
    ''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        statements = ([statement for block in function.ir.blocks for statement in block.body]
                      if getattr(function, "ir", None) else function.body)
        setters = [node for statement in statements for node in ast.walk(statement)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "__setitem__"]
        assert len(setters) == 1
        setter = setters[0]
        assert analyzed_representation(setter.args[1]) == analyzed_representation(setter.func.value).arguments[0]
        assert function.params[2].representation is None


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("literal, item_fits", [("[[]]", True), ("[[], [[9]]]", False)])
def test_nested_empty_literal_retains_both_analyzed_contexts(environment, literal, item_fits):
    with analyze_source(f'''
        def main(values: list[list[list[int]]], index: object) -> None:
            values[index] = {literal}
    ''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        statements = ([statement for block in function.ir.blocks for statement in block.body]
                      if getattr(function, "ir", None) else function.body)
        setters = [node for statement in statements for node in ast.walk(statement)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "__setitem__"]
        assert len(setters) == 2
        sliced, item = setters
        destination = analyzed_value_type(sliced.func.value)
        assert same_analyzer_type(analyzed_value_type(sliced.args[1]), destination)
        # An incompatible item arm retains the original snapshot for runtime
        # rejection; it must not acquire the valid slice arm's item layout.
        expected = destination.generic_types["V"] if item_fits else destination
        assert same_analyzer_type(analyzed_value_type(item.args[1]), expected)


def test_javascript_object_tuple_index_keeps_exact_item_analysis_and_output():
    assert_module_analysis_transpile('''
        def main(values: tuple[int, ...], index: object) -> int:
            value = values[index]
            return value + 1
    ''', '''
        def main(values: tuple__int__variadic, index: object) -> int:
            value: int = $get_tuple_item(values, index)
            return value.[int]__add__!(1)
    ''', '''
        import { get_tuple_item as $get_tuple_item } from './pyjs.python.js';

        export function main(values, index) {
            var value = $get_tuple_item(values, index);
            return value + 1;
        }
    ''')


@pytest.mark.parametrize("container,result", [("tuple[int, str]", "int | str"),
                                             ("tuple[int, ...]", "int"), ("list[int]", "int")])
@pytest.mark.parametrize("explicit", [False, True])
def test_javascript_object_index_does_not_invent_first_class_slices(container, result, explicit):
    expression = "values.__getitem__(index)" if explicit else "values[index]"
    source = f'''
        def main(values: {container}, index: object) -> {result}:
            return {expression}
    '''
    if explicit and container == "list[int]":
        # The existing JS dunder model requires int; syntax has its own path.
        with pytest.raises(CompilationError, match="expects int, got object"):
            with analyze_source(source):
                pass
        return
    with analyze_source(source) as analysis:
        returned = analysis.entry_point.body[0].value
        assert same_analyzer_type(analyzed_value_type(returned), analysis.entry_point.return_type)


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
def test_iterable_conversion_prepares_refined_source_cursor_during_analysis(environment):
    with analyze_source('''
        from collections.abc import Iterable
        from pyjs import js
        @js
        def consume(values: Iterable[int | float]) -> None:
            pass
        @js
        def main() -> None:
            consume((1.5, 2.5))
    ''', wrap=False, environment=environment):
        builtins = (environment or JS_ENVIRONMENT).builtins
        item = builtins.search("float")
        # Inspect the cache, rather than instantiate the missing class in this
        # assertion. Code generation must not start retryable type analysis.
        cursors = builtins.search("Iterator").concrete_classes.values()
        assert any(cursor.generic_types["V"] is item for cursor in cursors)


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("sliced", [False, True], ids=["item", "slice"])
@pytest.mark.parametrize("explicit", [False, True], ids=["subscript", "dunder"])
@pytest.mark.parametrize("container", ["list[int8]", "tuple[int8, ...]"])
def test_builtin_getitem_overloads_keep_result_type_and_representation(environment, sliced, explicit, container):
    result_type = container if sliced else "int8"
    expression = "values.__getitem__(selected)" if explicit else "values[selected]"
    with analyze_source(f'''
        from pyjs import int8
        def main(values: {container}, selected: {"slice" if sliced else "int"}) -> {result_type}:
            return {expression}
    ''', wrap=False, environment=environment) as analysis:
        result = analysis.entry_point.body[0].value
        assert same_analyzer_type(analyzed_value_type(result), analysis.entry_point.return_type)
        assert analyzed_representation(result) == analysis.entry_point.return_representation


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("item", ['"text"', "1", "(1, 2)"])
@pytest.mark.parametrize("explicit", [False, True], ids=["subscript", "dunder"])
def test_builtin_setitem_overloads_reject_a_list_in_an_item_slot(environment, item, explicit):
    statement = "values.__setitem__(0, other)" if explicit else "values[0] = other"
    source = f'''
        from pyjs import js
        @js
        def main() -> None:
            values = [{item}]
            other = [{item}]
            {statement}
    '''
    with pytest.raises(CompilationError, match="No overload|expects"):
        with analyze_source(source, wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("explicit", [False, True], ids=["subscript", "dunder"])
@pytest.mark.parametrize("container", ["list[int8]", "tuple[int8, ...]"])
@pytest.mark.parametrize("index", ["object", "int | slice | None"])
def test_dynamic_getitem_keeps_each_result_arms_representation(environment, explicit, container, index):
    expression = "values.__getitem__(selected)" if explicit else "values[selected]"
    with analyze_source(f'''
        from pyjs import int8
        def main(values: {container}, selected: {index}) -> int8 | {container}:
            return {expression}
    ''', wrap=False, environment=environment) as analysis:
        result = analysis.entry_point.body[0].value
        assert same_analyzer_type(analyzed_value_type(result), analysis.entry_point.return_type)
        assert analyzed_representation(result) == analysis.entry_point.return_representation


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
def test_dynamic_index_does_not_erase_a_represented_lists_replacement_contract(environment):
    with pytest.raises(CompilationError, match="No overload of '__setitem__' accepts"):
        with analyze_source('''
            from pyjs import int8
            def main(values: list[int8], index: object, rhs: object) -> None:
                values[index] = rhs
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("backend", ["jvm", "wasm"])
def test_dynamic_subscripts_keep_other_native_backend_capability_diagnostics(backend):
    from pyjs.java import JVMUnsupported, transpile_jvm
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    compiler, error, diagnostic = (
        (transpile_jvm, JVMUnsupported, "union has incompatible runtime types") if backend == "jvm" else
        (transpile_webassembly, WebAssemblyUnsupported, "value type object is not implemented"))
    with pytest.raises(error, match=diagnostic):
        compiler('''
            def selected(index: object) -> int | list[int]:
                return [1, 2][index]
            def main() -> int:
                value = selected(0)
                if isinstance(value, list):
                    return len(value)
                return value
        ''')


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("explicit", [False, True], ids=["subscript", "dunder"])
@pytest.mark.parametrize("replacement", ["[3]", "[[3]]", "[]", "()", "iter([[3]])"])
def test_slice_replacement_does_not_fall_back_to_a_nested_scalar_item(environment, explicit, replacement):
    statement = (f"values.__setitem__(slice(1), {replacement})" if explicit
                 else f"values[slice(1)] = {replacement}")
    source = f'''
        def main() -> None:
            values: list[list[int]] = [[1], [2]]
            {statement}
    '''
    if replacement == "[3]":
        with pytest.raises(CompilationError, match="Slice replacement has incompatible item types"):
            with analyze_source(source, wrap=False, environment=environment):
                pass
    else:
        with analyze_source(source, wrap=False, environment=environment):
            pass


def test_native_text_bounds_retain_index_protocol_without_explicit_calls():
    with analyze_source('''
        class Bound:
            def __index__(self) -> int:
                return 1
        def main(text: str, start: Bound) -> int:
            return text.find("x", start)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {(function.cls.name, function.name)
                   for function in build_program_ir(analysis.entry_point).functions
                   if function.cls and not function.cls.container.scope.is_builtins}
        assert methods == {("Bound", "__index__")}


@pytest.mark.parametrize("statement", [
    "values[start:]", "values[start:] = [1]", "del values[start:]", "text[start:]",
])
def test_native_slice_syntax_retains_only_its_implicit_index_protocol(statement):
    with analyze_source(f'''
        class Bound:
            def __index__(self) -> int:
                return 1
            def unused(self) -> str:
                return not_reachable
        def main(values: list[int], text: str, start: Bound) -> None:
            {statement}
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {(function.cls.name, function.name)
                   for function in build_program_ir(analysis.entry_point).functions
                   if function.cls and not function.cls.container.scope.is_builtins}
        assert methods == {("Bound", "__index__")}


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("statement", ["values.extend([])", "values[1:] = []", "values[slice(1)] = []"])
def test_empty_stored_iterables_inherit_destination_type_and_representation(environment, statement):
    if environment is None and "slice(" in statement:
        pytest.skip("JavaScript has no builtin slice constructor")
    with analyze_source(f'''
        from pyjs import js, int8
        @js
        def main(values: list[int8]) -> None:
            {statement}
    ''', wrap=False, environment=environment) as analysis:
        body = ast.Module(body=analysis.entry_point.body, type_ignores=[])
        literals = [node for node in ast.walk(body) if isinstance(node, ast.List) and not node.elts]
        assert len(literals) == 1
        parameter = analysis.entry_point.params[0]
        assert same_analyzer_type(analyzed_value_type(literals[0]), parameter.annotation.obj)
        assert analyzed_representation(literals[0]) == parameter.representation


def test_empty_stored_iterables_keep_exact_javascript_lowering():
    assert_module_analysis_transpile('''
        def main(values: list[int]) -> None:
            values.extend([])
            values[1:] = []
    ''', '''
        def main(values: list__int) -> None:
            values.[list__int]extend!([])
            $assignment1: list[int] = []
            $set_list_slice(values, $assignment1, 1, None, None)
    ''', '''
        import { set_list_slice as $set_list_slice } from './pyjs.python.js';

        export function main(values) {
            (values.push(...[]), null);
            var $assignment1 = [];
            $set_list_slice(values, $assignment1, {start: 1, stop: null, step: null});
        }
    ''')


def test_native_bytes_retains_acquired_cursor_closure_but_not_unrelated_methods():
    with analyze_source('''
        class Cursor:
            def __iter__(self) -> "Cursor":
                return self
            def __next__(self) -> int:
                return 1
            def unused(self) -> str:
                return not_reachable
        class Source:
            cursor: Cursor
            def __iter__(self) -> Cursor:
                return self.cursor
            def unused(self) -> str:
                return also_not_reachable
        def main(value: Source) -> str:
            return bytes(value).hex()
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        methods = {(function.cls.name, function.name)
                   for function in build_program_ir(analysis.entry_point).functions
                   if function.cls and not function.cls.container.scope.is_builtins}
        assert methods == {("Source", "__iter__"), ("Cursor", "__iter__"), ("Cursor", "__next__")}


@pytest.mark.parametrize("interface", ["Iterable", "Iterator"])
@pytest.mark.parametrize("consumer_first", [False, True])
def test_native_view_protocol_reachability_tracks_only_actual_conversion_sources(interface, consumer_first):
    expression = "consume(Source())" if consumer_first else "consume(view)"
    setup = "" if consumer_first else f"view: {interface}[int] = Source()"
    source = f'''
        from collections.abc import Iterable, Iterator
        class Source:
            def __iter__(self) -> 'Source':
                return self
            def __next__(self) -> int:
                return 1
            def __bytes__(self) -> bytes:
                return b'converted'
            def unrelated(self) -> str:
                return unknown_body
        class Unconverted:
            def __iter__(self) -> Iterator[int]:
                return unknown_iterator
            def __bytes__(self) -> bytes:
                return unknown_conversion
        def consume(value: {interface}[int]) -> bytes:
            return bytes(value)
        def main() -> bytes:
            unused = Unconverted()
            {setup}
            return {expression}
    '''
    for _ in range(2):
        with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
            entry = analysis.entry_point
            program = build_program_ir(entry)
            methods = {(function.cls.name, function.name) for function in program.functions
                       if function.cls and not function.cls.container.scope.is_builtins}
            assert methods == {("Source", "__iter__"), ("Source", "__next__"), ("Source", "__bytes__")}
            assert {(original.name, target.generic_name) for original, target in entry.runtime_view_sources} == {
                ("Source", interface), ("Source", "Iterator")}
        assert not entry.runtime_view_sources


@pytest.mark.parametrize("expression", ["iter(Source())", "iter(iter(Source()))", "acquire(Source())"])
def test_native_acquisition_retains_each_concrete_cursor_conversion(expression):
    with analyze_source(f'''
        from collections.abc import Iterable, Iterator
        class Leaf:
            def __iter__(self) -> 'Leaf':
                return self
            def __next__(self) -> int:
                return 1
            def __bytes__(self) -> bytes:
                return b'leaf'
        class Cursor:
            def __iter__(self) -> Leaf:
                return Leaf()
            def __next__(self) -> int:
                return 2
            def __bytes__(self) -> bytes:
                return b'cursor'
        class Source:
            def __iter__(self) -> Cursor:
                return Cursor()
        def acquire(value: Iterable[int]) -> Iterator[int]:
            return iter(value)
        def main() -> bytes:
            return bytes({expression})
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        program = build_program_ir(entry)
        methods = {(function.cls.name, function.name) for function in program.functions
                   if function.cls and not function.cls.container.scope.is_builtins}
        assert methods == {("Source", "__iter__"),
                           *((name, method) for name in ("Cursor", "Leaf")
                             for method in ("__iter__", "__next__", "__bytes__"))}
        expected = {("Cursor", "Iterator"), ("Leaf", "Iterator")}
        if expression == "acquire(Source())":
            expected.add(("Source", "Iterable"))
        assert {(original.name, target.generic_name) for original, target in entry.runtime_view_sources} == expected


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("actual,expected,valid", [
    ("int, object, str", "object, int, object", True),
    ("int, int | str, str", "int | str, str, str | None", True),
    ("int, int, None", "int, object, None", False),
    ("object, int, str", "int, int, str", False),
    ("int, int, object", "int, int, str", False),
    ("int8, int8, None", "int16, int8, None", False),
    ("int8, int8, None", "int8, int16, None", False),
])
def test_generator_variance_preserves_representations(environment, actual, expected, valid):
    source = f'''
        from collections.abc import Generator
        from pyjs import js, int8, int16
        @js
        def main(value: Generator[{actual}]) -> Generator[{expected}]:
            return value
    '''
    if valid:
        with analyze_source(source, wrap=False, environment=environment) as analysis:
            assert analysis.entry_point.return_type.generic_name == "Generator"
    else:
        with pytest.raises(CompilationError, match="return|Return|representation"):
            with analyze_source(source, wrap=False, environment=environment):
                pass


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
def test_generator_yield_covariance_survives_iterator_erasure(environment):
    with analyze_source('''
        from collections.abc import Generator, Iterator
        from pyjs import js
        @js
        def main(value: Generator[int, str, None]) -> Iterator[object]:
            return value
    ''', wrap=False, environment=environment) as analysis:
        assert analysis.entry_point.return_type.generic_name == "Iterator"


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize(('source', 'target'), [
    ('Generator[int, Iterator[int], None]', 'Generator[int, Cursor, None]'),
    ('Iterable[Callable[[Iterator[int]], int]]', 'Iterable[Callable[[Cursor], object]]'),
    ('list[Callable[[Iterator[int]], int]]', 'Iterable[Callable[[Cursor], object]]'),
])
def test_interface_views_retain_structural_cursor_methods(environment, source, target):
    with analyze_source(f'''
        from collections.abc import Callable, Generator, Iterable, Iterator
        from pyjs import js
        @js
        class Cursor:
            def __iter__(self) -> "Cursor":
                return self
            def __next__(self) -> int:
                return 7
        @js
        def main(value: {source}) -> {target}:
            return value
    ''', wrap=False, environment=environment) as analysis:
        methods = {function.name for function in build_program_ir(analysis.entry_point).functions
                   if function.cls is not None and function.cls.name == "Cursor"}
        assert {"__iter__", "__next__"} <= methods


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("first,second", [
    ("int | str", "str | int"),
    ("None | int", "int | None"),
    ("list[int | str]", "list[str | int]"),
])
def test_application_generic_cache_keeps_equivalent_nominal_classes(environment, first, second):
    with analyze_source(f'''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
        @js
        def main(first: Box[{first}], second: Box[{second}]) -> int:
            return 0
    ''', wrap=False, environment=environment) as analysis:
        first, second = (parameter.annotation.obj for parameter in analysis.entry_point.params)
        assert first is second


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("wrapper", ["list[{}]", "list[list[{}]]"])
def test_generic_cache_preserves_union_order_without_changing_type_equivalence(environment, wrapper):
    first = wrapper.format("int8 | str")
    second = wrapper.format("str | int8")
    with analyze_source(f'''
        from pyjs import js, int8
        @js
        def main(first: {first}, second: {second}, again: {first}) -> int:
            return 0
    ''', wrap=False, environment=environment) as analysis:
        first, second, again = (parameter.annotation.obj for parameter in analysis.entry_point.params)
        assert first is again
        assert first is not second
        assert same_analyzer_type(first, second)
        while not isinstance(first, UnionType):
            first = next(iter(first.generic_types.values()))
            second = next(iter(second.generic_types.values()))
        assert [member.name for member in first.types] == ["int", "str"]
        assert [member.name for member in second.types] == ["str", "int"]


@pytest.mark.parametrize("environment", ENVIRONMENTS[1:], ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("module", ["typing", "collections.abc"])
@pytest.mark.parametrize("name,arguments", [
    ("Iterable", "int"), ("Iterator", "int"), ("Generator", "int, None, None"),
    ("KeysView", "str"), ("ValuesView", "int"), ("ItemsView", "str, int"),
])
def test_native_model_protocol_import_aliases(environment, module, name, arguments):
    with analyze_source(f'''
        from __future__ import annotations
        from {module} import {name} as Protocol
        def main(value: Protocol[{arguments}]) -> int:
            return 7
    ''', wrap=False, environment=environment) as analysis:
        annotation = analysis.entry_point.params[0].annotation.obj
        assert annotation.generic_name == name
        assert annotation.container.scope.is_builtins


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("source,item,valid", [
    ("list[int]", "int", True), ("list[str]", "int", False),
    ("tuple[()]", "int", True), ("list[int8]", "int8", True),
    ("list[int8]", "int", False), ("int", "int", False),
])
def test_callback_iterable_input_types_and_representations(environment, source, item, valid):
    code = f'''
        from collections.abc import Callable, Iterable
        from pyjs import js, int8
        @js
        def consume(values: Iterable[{item}]) -> int:
            return 7
        @js
        def factory() -> Callable[[{source}], int]:
            return consume
        def main() -> int:
            factory()
            return 0
    '''
    if valid:
        with analyze_source(code, wrap=False, environment=environment) as analysis:
            assert analysis.entry_point.scope.search("factory").return_type.parameter_types is not None
    else:
        with pytest.raises(CompilationError, match="return|Return|representation"):
            with analyze_source(code, wrap=False, environment=environment):
                pass


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("actual,expected,valid", [
    ("object", "int", True), ("int | str", "str", True), ("int | None", "int", True),
    ("int", "object", False), ("str", "int | str", False),
    ("int8", "int", False), ("int", "int8", False), ("int8", "int16", False),
])
def test_callback_input_variance_retains_representations(environment, actual, expected, valid):
    source = f'''
        from collections.abc import Callable
        from pyjs import js, int8, int16
        @js
        def callback(value: {actual}) -> int:
            return 7
        @js
        def factory() -> Callable[[{expected}], int]:
            return callback
        def main() -> int:
            factory()
            return 0
    '''
    if valid:
        with analyze_source(source, wrap=False, environment=environment) as analysis:
            factory = analysis.entry_point.scope.search("factory")
            assert factory.return_type.parameter_types is not None
    else:
        with pytest.raises(CompilationError, match="return|Return|representation"):
            with analyze_source(source, wrap=False, environment=environment):
                pass


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("parameters", ["int, str", "int, ..."])
@pytest.mark.parametrize("name", ["Box", "tuple"])
def test_application_tuple_annotations_have_ordinary_generic_arity(environment, parameters, name):
    message = ("not a supported type annotation" if "..." in parameters
               else "expects 1 type argument, got 2")
    with pytest.raises(CompilationError, match=message):
        with analyze_source(f'''
            from pyjs import js
            @js
            class {name}[T]:
                def __init__(self, value: T):
                    self.value = value
            @js
            def consume(value: {name}[{parameters}]) -> int:
                return 1
            def main() -> int:
                return consume({name}(1))
        ''', wrap=False, environment=environment, filename="nominal_annotation.py"):
            pass


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
def test_unresolved_nested_literals_do_not_match_non_generic_object(environment):
    with analyze_source('''
        from pyjs import js
        @js
        def consume(value: object) -> int:
            return 0
        def main() -> int:
            return consume([[]]) + consume({'a': []})
    ''', wrap=False, environment=environment) as analysis:
        object_type = analysis.entry_point.scope.search("object")
        assert contextual_collection_type(object_type, None) is None
        assert contextual_collection_type(object_type, "object") is None


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
def test_application_object_does_not_replace_implicit_bases_or_generic_bounds(environment):
    with analyze_source('''
        from builtins import object as Anything
        from pyjs import js
        @js
        class object:
            pass
        @js
        class Child(object):
            pass
        @js
        class Box[T]:
            pass
        @js
        def identity[T](value: T) -> T:
            return value
        def main(value: Child, box: Box[object]) -> Anything:
            return identity(value)
    ''', wrap=False, environment=environment) as analysis:
        scope = analysis.entry_point.scope
        app_object, anything = scope.search("object"), scope.search("Anything")
        child, box, identity = scope.search("Child"), scope.search("Box"), scope.search("identity")
        assert app_object.super is anything
        assert child.super is app_object
        assert not same_analyzer_type(app_object, anything)
        assert is_subclass(child, app_object)
        assert not is_subclass(anything, app_object)
        assert box.type_parameters["T"].super is anything
        assert identity.type_parameters["T"].super is anything


def test_numeric_names_use_nominal_javascript_checks():
    assert_module_transpile('''
        from pyjs import js
        @js
        class int:
            pass
        def main(value: int | bool) -> bool:
            return isinstance(value, int)
    ''', '''
        export class int {
        }

        export function main(value) {
            return (value instanceof int);
        }
    ''')


def test_application_object_is_an_emitted_base():
    assert_module_transpile('''
        from pyjs import js
        @js
        class object:
            pass
        @js
        class Child(object):
            pass
        def main(value: Child) -> bool:
            return isinstance(value, object)
    ''', '''
        export class object {
        }

        export class Child extends object {
        }

        export function main(value) {
            return (value instanceof object);
        }
    ''')


def test_optional_application_object_equality_uses_dynamic_dispatch():
    assert_module_transpile('''
        from builtins import object as Anything
        from pyjs import js
        @js
        class object:
            def __eq__(self, other: Anything) -> bool:
                return False
        def main(left: object | None, right: object) -> bool:
            return left == right
    ''', '''
        import { equal_value as $equal_value } from './pyjs.python.js';

        export class object {

            __eq__(other) {
                return false;
            }
        }

        export function main(left, right) {
            return $equal_value(left, right);
        }
    ''')


def test_builtin_object_check_evaluates_its_operand_once():
    assert_module_transpile('''
        from builtins import object as Anything
        from pyjs import js
        @js
        def observe(events: list[int]) -> None:
            events.append(1)
        def main(events: list[int]) -> bool:
            return isinstance(observe(events), Anything)
    ''', '''
        export function observe(events) {
            (events.push(1), null);
        }

        export function main(events) {
            return (observe(events),true);
        }
    ''')


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
def test_nominal_identity_survives_builtin_aliases_unions_and_generic_arguments(environment):
    with analyze_source('''
        from builtins import int as Integer, float as Float
        from pyjs import js
        @js
        class int:
            pass
        @js
        class float:
            pass
        @js
        class Box[T]:
            pass
        def main(a: Box[int], b: Box[Integer], c: Box[bool], pair: int | Integer) -> Integer:
            return 0
    ''', wrap=False, environment=environment) as analysis:
        scope = analysis.entry_point.scope
        app_int, app_float = scope.search("int"), scope.search("float")
        integer, floating = scope.search("Integer"), scope.search("Float")
        boolean = integer.container.scope.search("bool")
        assert not same_analyzer_type(app_int, integer)
        assert not same_analyzer_type(app_float, floating)
        assert not is_subclass(boolean, app_int)
        assert not is_subclass(integer, app_float)
        assert not is_subclass(app_int, floating)
        assert is_subclass(boolean, integer)
        assert is_subclass(integer, floating)
        assert not is_isinstance_match(integer, floating)
        a, b, c, pair = [argument.annotation.obj for argument in analysis.entry_point.params]
        assert not same_analyzer_type(a, b)
        assert not is_subclass(c, a)
        assert is_subclass(c, b)
        assert isinstance(pair, UnionType)
        assert set(pair.types) == {app_int, integer}
        assert len(UnionType(types=(a, b, a)).types) == 2


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("name, value", [("int", "True"), ("float", "3")])
def test_numeric_names_do_not_accept_builtin_arguments(environment, name, value):
    with pytest.raises(CompilationError, match="Argument 'value' to accepts expects"):
        with analyze_source(f'''
            from builtins import int as Integer
            from pyjs import js
            @js
            class {name}:
                pass
            @js
            def accepts(value: {name}) -> Integer:
                return 1
            def main() -> Integer:
                return accepts({value})
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("name", ["Box", "object", "callable"])
@pytest.mark.parametrize("argument", ["callback", "Factory", "list"])
def test_application_names_do_not_accept_opaque_function_arguments(environment, name, argument):
    with pytest.raises(CompilationError, match=f"Argument 'value' to accepts expects {name}"):
        with analyze_source(f'''
            from pyjs import js
            @js
            class {name}:
                def get(self) -> int:
                    return 1
            @js
            class Factory:
                pass
            @js
            def callback() -> int:
                return 1
            @js
            def accepts(value: {name}) -> int:
                return value.get()
            def main() -> int:
                return accepts({argument})
        ''', wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("environment", ENVIRONMENTS, ids=["js", "llvm", "jvm", "wasm"])
@pytest.mark.parametrize("name", ["Box", "dict", "list", "set", "frozenset"])
def test_unsubscripted_application_generic_isinstance_is_not_a_builtin_test(environment, name):
    with pytest.raises(CompilationError, match=f"does not support unsubscripted '{name}'"):
        with analyze_source(f'''
            from pyjs import js
            @js
            class {name}[T]:
                def __init__(self, value: T):
                    self.value = value
            def main() -> int:
                value = {name}(value=3)
                if isinstance(value, {name}):
                    return value.value
                return 0
        ''', wrap=False, environment=environment):
            pass
