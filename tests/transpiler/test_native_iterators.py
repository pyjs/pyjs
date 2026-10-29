import ast
from collections.abc import Generator, Iterator
from textwrap import dedent

import pytest

from pyjs import int8, int64
from pyjs.analysis.analyzer import JS_ENVIRONMENT, iterable_protocol
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.analysis.type_relations import inherited_sequence_slot
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("name", ["Iterator", "Generator"])
def test_application_cursor_names_are_not_abstract_iterator_contracts(environment, name):
    with analyze_source(f'''
        class {name}:
            def __iter__(self) -> "{name}":
                return self
            def __next__(self) -> int:
                raise StopIteration()
        def main() -> int:
            result = 0
            for value in {name}():
                result += value
            return result
    ''', wrap=False, environment=environment) as analysis:
        assert analysis.entry_point.return_type is environment.builtins.search("int")
        cls = analysis.entry_point.container.search(name)
        assert cls.find_attrs("__next__") in analysis.entry_point.compilation_objects


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
@pytest.mark.parametrize("import_line, annotation", [
    ("from collections.abc import Awaitable", "Awaitable[str]"),
    ("from typing import Awaitable as Pending", "Pending[str]"),
    ("import collections.abc as abc", "abc.Awaitable[str]"),
])
def test_awaitable_in_callback_field_uses_the_backend_declaration(environment, import_line, annotation):
    with analyze_source(f'''
        {import_line}
        from collections.abc import Callable
        from pyjs import js
        type Callback = Callable[[int], {annotation}]
        @js
        class Holder:
            callback: Callback
        @js
        def main() -> Holder:
            return Holder()
    ''', wrap=False, environment=environment) as analysis:
        callback = analysis.entry_point.return_type._self.attrs["callback"].type
        assert callback.parameter_types == (environment.builtins.scope.names["int"],)
        awaitable = callback.return_type
        assert awaitable.generic_name == "Awaitable"
        assert awaitable.container.scope.is_builtins
        assert tuple(awaitable.generic_types.values()) == (environment.builtins.scope.names["str"],)


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_generic_iterator_calls_retain_independent_inferred_contracts(environment):
    with analyze_source('''
        from collections.abc import Iterator
        from pyjs import int8, js
        @js
        def keep[T](value: Iterator[T]) -> Iterator[T]: return value
        @js
        def main() -> int:
            narrow = keep(iter([int8(127)]))
            text = keep(iter(["s"]))
            return int(next(narrow)) + len(next(text))
    ''', wrap=False, environment=environment) as analysis:
        calls = [node for statement in analysis.entry_point.body for node in ast.walk(statement)
                 if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "keep"]
        parameter = analysis.entry_point.container.search("keep").type_parameters["T"]
        assert [call.type_bindings[parameter].name for call in calls] == ["int", "str"]
        assert [call.representation_bindings[parameter] for call in calls] == [annotation_representation(int8), None]
        assert calls[0].type_bindings is not calls[1].type_bindings
        assert calls[0].representation_bindings is not calls[1].representation_bindings


def test_generator_expression_ir_binds_outer_iterator_and_acquires_inner():
    with analyze_source('''
        def main() -> int:
            values = (x + y for x in [1, 2] for y in [3, 4])
            return sum(values)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    values: Generator[int, None, None] = generator(__comprehension_source=iter(new[external] list[int](1, 2))):
                        block entry:
                            iterator = bind_iterator(__comprehension_source)
                            jump for_next
                        block for_next:
                            branch_next iterator:
                                item x -> for_body
                                done -> for_done
                        block for_body:
                            iterator_2 = iter(new[unresolved] list[int](3, 4))
                            jump for_next_2
                        block for_next_2:
                            branch_next iterator_2:
                                item y -> for_body_2
                                done -> for_done_2
                        block for_body_2:
                            yield x.[int]__add__(y) -> resume
                        block resume:
                            jump for_next_2
                        block for_done_2:
                            jump for_next
                        block for_done:
                            return
                    return sum(values)
        ''').rstrip()


@pytest.mark.parametrize("backend", ["llvm", "javascript"])
def test_next_list_diagnostic_infers_item_not_container(backend):
    options = {"environment": NATIVE_ENVIRONMENT} if backend == "llvm" else {}
    with pytest.raises(CompilationError) as caught:
        with analyze_source('''
            values = [1, 2]
            next(values)
        ''', **options):
            pass
    assert "expects Iterator[int], got list[int]" in str(caught.value)


def test_javascript_does_not_infer_python_cursor_as_host_native_iterator():
    with pytest.raises(CompilationError, match="not iterable"):
        with analyze_source('''
            from typing import Self
            from pyjs import js

            @js
            class Cursor:
                def __iter__(self) -> Self:
                    return self

                def __next__(self) -> int:
                    return 1

            @js
            def main() -> int:
                for value in Cursor():
                    return value
                return 0
        ''', wrap=False):
            pass


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "webassembly"])
def test_list_pop_preserves_nested_iterator_representation(environment):
    with analyze_source('''
        from typing import Iterator
        from pyjs import int8

        def main() -> int:
            rows: list[Iterator[int8]] = [iter([int8(127)])]
            cursor = rows.pop()
            item = next(cursor, int8(-1))
            return int(item)
    ''', wrap=False, environment=environment) as analysis:
        scope = analysis.entry_point.scope
        assert scope.search("cursor").representation == annotation_representation(Iterator[int8])
        assert scope.search("item").representation == annotation_representation(int8)


def test_represented_pop_keeps_webassembly_capability_diagnostic():
    from pyjs.webassembly.transpiler import WebAssemblyUnsupported, transpile_webassembly

    with pytest.raises(WebAssemblyUnsupported, match="pop"):
        transpile_webassembly('''
            from pyjs import int8
            def main() -> int:
                value = [int8(127)].pop()
                return int(value + 1)
        ''')


@pytest.mark.parametrize("storage", ["return [Cursor()]", "value = Cursor(); return [value]"])
def test_custom_cursor_interface_storage_retains_methods(storage):
    with analyze_source(f'''
        from typing import Self
        from collections.abc import Iterator
        from pyjs import int8

        class Cursor:
            def __iter__(self) -> Self:
                return self

            def __next__(self) -> int8:
                return int8(127)

        def boxed() -> list[Iterator[int8]]:
            {storage}

        def main() -> int:
            rows = boxed()
            cursor = rows.pop()
            return int(next(cursor))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        cursor = analysis.entry_point.container.search("Cursor")
        for name in ("__iter__", "__next__"):
            assert cursor.find_attrs(name) in analysis.entry_point.compilation_objects
        assert analysis.entry_point.scope.search("cursor").representation == annotation_representation(Iterator[int8])


@pytest.mark.parametrize("item", ["int", "int16"])
@pytest.mark.parametrize("storage", ["return cursor", "return [cursor]"])
def test_custom_cursor_interface_rejects_representation_change(item, storage):
    annotation = f"Iterator[{item}]" if storage == "return cursor" else f"list[Iterator[{item}]]"
    with pytest.raises(CompilationError, match="Custom iterator items use an incompatible representation"):
        with analyze_source(f'''
            from typing import Self
            from collections.abc import Iterator
            from pyjs import int8, int16

            class Cursor:
                def __iter__(self) -> Self:
                    return self

                def __next__(self) -> int8:
                    return int8(127)

            def boxed(cursor: Cursor) -> {annotation}:
                {storage}

            def main() -> int:
                boxed(Cursor())
                return 0
        ''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


@pytest.mark.parametrize("item", ["int", "int16"])
@pytest.mark.parametrize("storage, expression, empty", [
    ("list", "values.append(cursor)", "[]"),
    ("list", "values.insert(0, cursor)", "[]"),
    ("list", "values[0] = cursor", "[]"),
    ("dict", 'values["cursor"] = cursor', "{}"),
])
def test_cursor_mutations_validate_receiver_item_representation(item, storage, expression, empty):
    annotation = f"list[Iterator[{item}]]" if storage == "list" else f"dict[str, Iterator[{item}]]"
    with pytest.raises(CompilationError, match="Custom iterator items use an incompatible representation"):
        with analyze_source(f'''
            from typing import Self
            from collections.abc import Iterator
            from pyjs import int8, int16

            class Cursor:
                def __iter__(self) -> Self:
                    return self
                def __next__(self) -> int8:
                    return int8(127)

            def update(values: {annotation}, cursor: Cursor) -> None:
                {expression}

            def main() -> int:
                update({empty}, Cursor())
                return 0
        ''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "webassembly"])
def test_native_mapping_views_retain_item_metadata(environment):
    with analyze_source('''
        from pyjs import int8, int64

        def main() -> int:
            mapping = {int8(127): int64(40)}
            keys = mapping.keys()
            values = mapping.values()
            items = mapping.items()
            return int(next(iter(keys))) + int(next(iter(values))) + int(next(iter(items))[0])
    ''', wrap=False, environment=environment) as analysis:
        scope = analysis.entry_point.scope
        assert scope.search("keys").representation.item_representation == annotation_representation(int8)
        assert scope.search("values").representation.item_representation == annotation_representation(int64)
        items = scope.search("items")
        # ItemsView stores K/V contracts; its iterator yields the tuple of them.
        assert items.representation.arguments == (annotation_representation(int8), annotation_representation(int64))
        assert iterable_protocol(items.cls, items.representation).item_representation == annotation_representation(tuple[int8, int64])


def test_imported_iterator_annotation_and_returned_cursor():
    with analyze_source('''
        from collections.abc import Iterator as Cursor

        def take(values: Cursor[int]) -> int:
            return next(values, -1)

        def main() -> int:
            return take(iter([1, 2]))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def take(values: Iterator__int) -> int:
                block entry:
                    return next(values, -1)

            def main() -> int:
                block entry:
                    return take(iter(new[local] list[int](1, 2)))
        ''').rstrip()


def test_enumerate_keywords_keep_source_evaluation_order():
    with analyze_source('''
        def main() -> int:
            rows = enumerate(start=3, iterable=[7])
            return next(rows)[0]
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    rows: Iterator[tuple[int, int]] = enumerate(start=3, iterable=new[local] list[int](7))
                    return next(rows).[tuple__int_int]__getitem__(0)
        ''').rstrip()


@pytest.mark.parametrize("expression", ["range(Index())", "range(1, Index(), Index())",
    "enumerate([1], Index())", "enumerate(start=Index(), iterable=[1])",
    "batched([1], Index())", "batched(n=Index(), iterable=[1])",
    "repeat(1, Index())", "repeat(times=Index(), object=1)",
    "islice([1], Index())", "islice([1], Index(), Index(), Index())",
    "[1, 2, 3][Index()]", "(1, 2, 3)[Index()]", "'abc'[Index()]", "b'abc'[Index()]",
    "range(3)[Index()]", "[1].pop(Index())", "[1].insert(Index(), 2)",
    "[1].__setitem__(Index(), 2)", "[1].__delitem__(Index())",
    "[1].index(1, Index(), Index())", "(1,).index(1, Index(), Index())",
    "'x' * Index()", "Index() * b'x'", "[1] * Index()", "Index() * (1,)",
    "[1].__imul__(Index())"])
def test_native_index_consumers_retain_implicit_index_callbacks(expression):
    with analyze_source(f'''
        from itertools import batched, repeat, islice
        class Index:
            def __index__(self) -> int:
                return 2
        def main():
            return {expression}
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        # Only the protocol dependency is relevant; builtin declaration and
        # iterator scaffolding would obscure this exact reachability assertion.
        assert {(fn.cls.name, fn.name) for fn in program.functions if fn.cls
                and not fn.cls.container.scope.is_builtins} == {("Index", "__index__")}


@pytest.mark.parametrize("statement", ["values = values * Count()", "values *= Count()"])
def test_guaranteed_numeric_reflection_does_not_retain_repeat_index(statement):
    with analyze_source(f'''
        class Count:
            def __rmul__(self, values: list[int]) -> list[int]:
                return [42]
            def __index__(self) -> int:
                return len(0)
        def main() -> list[int]:
            values = [1]
            {statement}
            return values
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        # Exact protocol set: rendering allocation scaffolding would obscure
        # whether the unreachable index body was pulled into this program.
        assert {(fn.cls.name, fn.name) for fn in program.functions if fn.cls
                and not fn.cls.container.scope.is_builtins} == {("Count", "__rmul__")}


@pytest.mark.parametrize("declaration", ["pass",
    "def multiply(self, other: object) -> int:\n        return 42\n    __mul__ = multiply", "__mul__ = None",
    "def __mul__(self, other: object) -> int:\n        return 42"])
def test_sequence_slot_classifier_stops_at_application_declarations(declaration):
    # Shared analysis supports this hierarchy; native emission separately
    # rejects builtin-container subclasses. Test slot ownership, not new layouts.
    with analyze_source(f'''
class Text(str):
    {declaration}
def main() -> Text:
    return Text('x')
''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        method = inherited_sequence_slot(analysis.entry_point.return_type, "__mul__")
        expected = NATIVE_ENVIRONMENT.builtins.search("str").find_attrs("__mul__")
        assert method is (expected if declaration == "pass" else None)


@pytest.mark.parametrize("backend", ["jvm", "webassembly"])
def test_custom_sequence_index_keeps_other_backend_capability_diagnostic(backend):
    from pyjs.java.transpiler import JVMUnsupported, transpile_jvm
    from pyjs.webassembly.transpiler import WebAssemblyUnsupported, transpile_webassembly

    transpile, error, message = ((transpile_jvm, JVMUnsupported, "unsupported JVM scalar operation __getitem__")
        if backend == "jvm" else
        (transpile_webassembly, WebAssemblyUnsupported, "WebAssembly numeric conversion is not implemented"))
    with pytest.raises(error, match=message):
        transpile('''
            class Index:
                def __index__(self) -> int:
                    return 0
            def main() -> int:
                return [42][Index()]
        ''')


def test_generator_erasure_preserves_yield_representation_without_relabeling_source():
    with analyze_source('''
        from collections.abc import Generator, Iterator
        from pyjs import int8

        def values() -> Generator[int8, None, None]:
            yield int8(127)

        def main() -> int:
            source = values()
            erased: Iterator[int8] = source
            item = next(erased)
            source.close()
            return int(item)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def values() -> Generator[int, None, None]:
                block entry:
                    yield int(127) -> resume
                block resume:
                    discard_resume_input()
                    return None

            def main() -> int:
                block entry:
                    source: Generator[int, None, None] = values()
                    erased: Iterator[int] = source
                    item: int = next(erased)
                    source.[Generator__int_NoneType_NoneType]close()
                    return int(item)
        ''').rstrip()
        scope = analysis.entry_point.scope
        # Inspect all three wire components, not the abbreviated host alias.
        expected = annotation_representation(Generator[int8, None, None])  # noqa: UP043
        assert scope.search("source").representation == expected
        assert scope.search("erased").representation == annotation_representation(Iterator[int8])
        assert scope.search("item").representation == annotation_representation(int8)


def test_generator_send_and_resume_keep_independent_numeric_representations():
    with analyze_source('''
        from collections.abc import Generator
        from pyjs import int8, int64

        def values() -> Generator[int8, int64, None]:
            received: int64 | None = yield int8(1)
            if received is not None:
                yield int8(received)

        def main() -> int:
            source = values()
            next(source)
            item = source.send(int64(3))
            source.close()
            return int(item)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def values() -> Generator[int, int, None]:
                block entry:
                    yield int(1) -> resume
                block resume:
                    received: int | None = resume_input()
                    branch received.[object]__is_not__(None):
                        true -> if_true
                        false -> if_done
                block if_true:
                    yield int(received) -> resume_2
                block resume_2:
                    discard_resume_input()
                    jump if_done
                block if_done:
                    return None

            def main() -> int:
                block entry:
                    source: Generator[int, int, None] = values()
                    next(source)
                    item: int = source.[Generator__int_int_NoneType]send(int(3))
                    source.[Generator__int_int_NoneType]close()
                    return int(item)
        ''').rstrip()
        scope = analysis.entry_point.scope
        expected = annotation_representation(Generator[int8, int64, None])  # noqa: UP043
        assert scope.search("source").representation == expected
        assert scope.search("item").representation == annotation_representation(int8)
        function = analysis.entry_point.container.search("values")
        assert function.send_representation == annotation_representation(int64)
        assert function.scope.search("received").representation == annotation_representation(int64 | None)


@pytest.mark.parametrize("declared", [False, True])
def test_generator_completion_keeps_representation_and_returned_parameter_lifetime(declared):
    source = '''
        from collections.abc import Generator
        from pyjs import int8, int64
        def values(items: list[int8]) -> Generator[int8, int64 | None, list[int8]]:
            received: int64 | None = yield int8(1)
            return items
        def main() -> int:
            source = values([int8(3)])
            completion = source.close()
            return 0
    '''
    if not declared:
        source = source.replace(" -> Generator[int8, int64 | None, list[int8]]", "")
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def values(items: list__int) -> Generator[int, int | None, list[int]]:
                block entry:
                    yield int(1) -> resume
                block resume:
                    received: int | None = resume_input()
                    return items

            def main() -> int:
                block entry:
                    source: Generator[int, int | None, list[int]] = values(new[external] list[int](int(3)))
                    completion: list[int] | None = source.[Generator__int_intUNoneType_list__int]close()
                    return 0
        ''').rstrip()
        scope = analysis.entry_point.scope
        expected = annotation_representation(Generator[int8, int64 | None, list[int8]])  # noqa: UP043
        assert scope.search("source").representation == expected
        assert scope.search("completion").representation == annotation_representation(list[int8] | None)
        function = analysis.entry_point.container.search("values")
        assert function.ir.lifetime.returned_parameters == frozenset({"items"})
        assert function.ir.lifetime.external_parameters == frozenset({"items"})


def test_generator_throw_result_keeps_portable_yield_representation():
    with analyze_source('''
        from pyjs import int8
        def values():
            yield int8(1)
        def main() -> int:
            source = values()
            item = source.throw(ValueError)
            return int(item)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def values() -> Generator[int, None, None]:
                block entry:
                    yield int(1) -> resume
                block resume:
                    discard_resume_input()
                    return None

            def main() -> int:
                block entry:
                    source: Generator[int, None, None] = values()
                    item: int = source.[Generator__int_NoneType_NoneType]throw(ValueError)
                    return int(item)
        ''').rstrip()
        assert analysis.entry_point.scope.search("item").representation == annotation_representation(int8)


@pytest.mark.parametrize("annotation, first, second, caller, message", [
    ("Generator[int, int, None]", "first: str = yield 1", "yield 2", "next(values())", "Cannot assign int"),
    ("Generator[int, int, None]", "yield 1", "yield 2", "values().send('wrong')", "expects int.*got str"),
    ("Generator[int, int8, None]", "yield 1", "yield 2", "values().send(int16(3))", "different fixed-width"),
    ("Generator[int, list[int8], None]", "yield 1", "yield 2", "values().send([int16(3)])", "different fixed-width"),
    ("Generator[int, int8, None]", "first: int16 | None = yield 1", "yield 2", "next(values())", "different fixed-width"),
    ("Generator[int, int8, None]", "first: object = yield 1", "yield 2", "next(values())", "cannot erase represented scalar"),
    ("Generator[int, int8, None]", "yield 1", "yield 2", "cast(Generator[int, int16, None], values())", "cannot change a value's runtime representation"),
    ("", "first: int | None = yield 1", "second: str | None = yield 2", "next(values())", "incompatible value types"),
    ("", "first: int8 | None = yield 1", "second: int16 | None = yield 2", "next(values())", "incompatible value types"),
])
def test_generator_input_type_and_representation_boundaries(annotation, first, second, caller, message):
    result = " -> " + annotation if annotation else ""
    with pytest.raises(CompilationError, match=message):
        with analyze_source(f'''
            from collections.abc import Generator
            from typing import cast
            from pyjs import int8, int16

            def values(){result}:
                {first}
                {second}

            def main() -> int:
                {caller}
                return 0
        ''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass
