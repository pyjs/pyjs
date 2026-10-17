import pytest

from pyjs.testing.helpers import ad, at
from tests.backend_semantics import (
    APPLICATION_ROUNDING_CONTRACT,
    ASSERT_BOOLEAN_FLOW_CONTRACT,
    ASSERT_CAPTURE_CONTRACT,
    ASSERT_FAILURE_CONTRACT,
    ASSERT_NARROWING_CONTRACT,
    CALLABLE_VALUE_CONTRACT,
    CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT,
    COLLECTION_NAME_CONTRACT,
    COMPREHENSION_CONTRACT,
    CUSTOM_ARITHMETIC_CONTRACT,
    EAGER_COLLECTION_CONTRACT,
    EVALUATION_ORDER_CONTRACT,
    FIELD_ASSIGNMENT_CONTRACT,
    GENERIC_OPERATOR_CONTRACT,
    INHERITED_FIELD_ASSIGNMENT_CONTRACT,
    ITERATOR_CALLBACK_CONTRACT,
    LAMBDA_CLOSURE_CONTRACT,
    LAZY_ITERATOR_CONTRACT,
    LITERAL_FIELD_ASSIGNMENT_CONTRACT,
    LITERAL_SEQUENCE_REFLECTION_CONTRACT,
    MAPPING_ASSIGNMENT_CONTRACT,
    MEMBERSHIP_ORDER_CONTRACT,
    NESTED_CONDITIONAL_CONTRACT,
    NUMERIC_NAME_CONTRACT,
    REPRESENTED_ROUNDING_CONTRACT,
    SCALAR_NUMERIC_CONTRACT,
    SEQUENCE_REFLECTION_CONTRACT,
    STRUCTURAL_OPERATOR_CONTRACT,
    TUPLE_ITERABLE_CONTRACT,
    UNION_REFLECTED_ARITHMETIC_CONTRACT,
    nominal_constructor_contract,
    nominal_object_contract,
    nominal_truth_contract,
    nominal_union_comparison_contract,
    scalar_namesake_sort_contract,
)

from .helpers import assert_semantics, run_python


def test_chained_callable_results_keep_virtual_methods_in_comprehensions():
    assert_semantics('''
from collections.abc import Callable
from pyjs import js
@js
class Base:
    def name(self) -> str:
        return "base"
@js
class Child(Base):
    def name(self) -> str:
        return "child"
@js
def make() -> Base:
    return Child()
@js
class Factory:
    def get(self) -> Callable[[], Base]:
        return make
@js
def main() -> None:
    values = [Factory()]
    print("|".join([value.get()().name() for value in values]))
    print("|".join(value.get()().name() for value in values))
main()
''')


def test_generic_constructor_positional_only_names_are_keyword_pack_entries():
    assert_semantics('''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: int = 1, /, **named: T):
                self.value = value
                self.named = named
            def get(self) -> T:
                return self.named["value"]
        @js
        def main() -> None:
            box = Box(value="keyword")
            print(box.value, box.get().upper())
            base = {"first": 1}
            merged = dict(base, word="value")
            print(merged["first"], merged["word"])
            pairs = dict([("first", [1, 2])], word="value")
            print(isinstance(pairs["first"], list), isinstance(pairs["word"], str))
            mixed_pairs = dict((("first", [1, 2]), ("word", "value")), last="tail")
            print(isinstance(mixed_pairs["first"], list), isinstance(mixed_pairs["word"], str))
            named = dict(values=7, fields=8)
            print(named["values"], named["fields"])
        main()
    ''')


def test_bounded_text_search_contract():
    from tests.backend_semantics import BOUNDED_TEXT_SEARCH_CONTRACT
    assert_semantics(BOUNDED_TEXT_SEARCH_CONTRACT.print_source + "\nmain()\n")


def test_bytes_construction_keeps_the_javascript_builtin_boundary():
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.javascript.source import compile_source
    from tests.backend_semantics import BYTES_CONSTRUCTION_CONTRACT
    with pytest.raises(CompilationError, match="Name 'bytes' is not defined"):
        with compile_source(BYTES_CONSTRUCTION_CONTRACT.source):
            pass


def test_slice_values_keep_the_javascript_builtin_boundary():
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.javascript.source import compile_source
    from tests.backend_semantics import SLICE_VALUE_CONTRACT
    with pytest.raises(CompilationError, match="Name 'slice' is not defined"):
        with compile_source(SLICE_VALUE_CONTRACT.source):
            pass


@pytest.mark.parametrize("contract", [COLLECTION_NAME_CONTRACT, TUPLE_ITERABLE_CONTRACT, NUMERIC_NAME_CONTRACT])
def test_application_collection_names(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


@pytest.mark.parametrize("name", ["int", "float", "bool", "str", "bytes"])
def test_scalar_namesake_sorting_uses_application_comparisons(name):
    assert_semantics(scalar_namesake_sort_contract(name).print_source + "\nmain()\n")


@pytest.mark.parametrize("name", ["int", "float", "bool", "str", "bytes", "list", "tuple", "dict", "set", "frozenset", "range", "object"])
def test_erased_and_searched_records_keep_nominal_identity(name):
    assert_semantics(nominal_object_contract(name).print_source + "\nmain()\n")


@pytest.mark.parametrize("name", ["Base", "object"])
@pytest.mark.parametrize("optional", [False, True])
def test_application_object_comparison_across_union_arms(name, optional):
    contract = nominal_union_comparison_contract(name, optional=optional)
    assert_semantics(contract.print_source + "\nmain()\n")


@pytest.mark.parametrize("name", ["Box", "dict", "list", "set", "frozenset", "tuple"])
def test_nominal_generic_constructor_keeps_its_own_signature(name):
    assert_semantics(nominal_constructor_contract(name).print_source + "\nmain()\n")


@pytest.mark.parametrize("name", ["Box", "bool"])
def test_nominal_bool_uses_authored_truth_conversion(name):
    assert_semantics(nominal_truth_contract(name).print_source + "\nmain()\n")


def test_builtin_object_check_is_universal_but_application_object_is_nominal():
    assert_semantics('''
        from builtins import object as Anything
        from pyjs import js
        @js
        class object:
            pass
        @js
        def observe(events: list[int]) -> None:
            events.append(1)
        @js
        def main():
            events: list[int] = []
            print(isinstance(observe(events), Anything), len(events))
            print(isinstance(1, Anything), isinstance(None, Anything))
            print(isinstance(object(), Anything), isinstance(object(), object))
            print(isinstance(1, object), isinstance(None, object))
        main()
    ''')


@pytest.mark.parametrize("name", ["tuple", "dict"])
def test_application_collection_name_keeps_its_iteration_protocol(name):
    assert_semantics(f'''
        from collections.abc import Iterator
        from pyjs import js
        @js
        class {name}:
            def __iter__(self) -> Iterator[int]:
                return iter([3, 4])
        @js
        def main():
            values = [value for value in {name}()]
            print(len(values), values[0], values[1])
            ordered = sorted({name}(), key=lambda value: -value)
            print(ordered[0], ordered[1])
        main()
    ''')


@pytest.mark.parametrize("contract", [CUSTOM_ARITHMETIC_CONTRACT, UNION_REFLECTED_ARITHMETIC_CONTRACT,
                                     SEQUENCE_REFLECTION_CONTRACT, LITERAL_SEQUENCE_REFLECTION_CONTRACT,
                                     STRUCTURAL_OPERATOR_CONTRACT, GENERIC_OPERATOR_CONTRACT],
                         ids=["concrete", "union-reflected", "sequence-reflected", "literal-sequence", "structural", "generic"])
def test_shared_custom_arithmetic_protocols(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


def test_declaration_function_namespace_resolves_static_members():
    assert_semantics('''
        from pyjs import js

        @js.inline("{value} + 1")
        def transform(value: int) -> int:
            return value + 1

        @js.inline("{value} * 2")
        def twice(value: int) -> int:
            return value * 2

        transform.twice = twice

        @js
        def main():
            print(transform(3), transform.twice(3))

        main()
    ''')


def test_shared_callable_inputs():
    from tests.backend_semantics import CALLABLE_INPUT_CONTRACT
    assert_semantics(CALLABLE_INPUT_CONTRACT.print_source + "\nmain()\n")


def test_shared_callable_defaults():
    from tests.backend_semantics import CALLABLE_DEFAULT_CONTRACT
    assert_semantics(CALLABLE_DEFAULT_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("expected", ["Callable[[int], int] | object", "object | Callable[[int], int]"])
def test_opaque_union_callbacks_through_named_local_and_parameter_calls(expected):
    assert_semantics(f'''
        from pyjs import js
        from collections.abc import Callable
        @js
        def text(value: str) -> str:
            return value
        @js
        def accept(value: {expected}) -> int:
            return 42
        @js
        def indirect(fn: Callable[[{expected}], int]) -> int:
            return fn(text)
        @js
        def main():
            fn: Callable[[{expected}], int] = accept
            print(accept(text), indirect(accept), fn(text))
        main()
    ''')


def test_shared_callable_iterables():
    from tests.backend_semantics import CALLABLE_ITERABLE_CONTRACT
    assert_semantics(CALLABLE_ITERABLE_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("expression", [
    "sum(values)", "sum(list(values))", "sum([x for x in values])",
    "sum({x for x in values})", "sum({x: x * 10 for x in values})",
    "sum(x for x in values)", "sum([x + y for x in values for y in values])",
    "next(iter(values))", "next(values.__iter__())",
])
def test_abstract_iterable_mapping_consumers(expression):
    assert_semantics(f'''
        from collections.abc import Iterable
        from pyjs import js
        @js
        def produce() -> Iterable[int]:
            print("produce")
            return {{3: 30, 4: 40}}
        @js
        def consume(values: Iterable[int]) -> int:
            return {expression}
        @js
        def main():
            print(consume(produce()))
        main()
    ''')


@pytest.mark.parametrize("source, concrete", [("[]", "list[int]"), ("[1]", "list[int]"),
                                             ("{}", "dict[int, int]"), ("{1: 2}", "dict[int, int]")])
def test_abstract_iterable_truth_keeps_source(source, concrete):
    assert_semantics(f'''
        from collections.abc import Callable, Iterable
        from pyjs import js
        @js
        def produce() -> Iterable[int]:
            result: {concrete} = {source}
            return result
        @js
        def consume(value: Iterable[int], original: {concrete}):
            print(bool(value), 1 if value else 0, not value, value is original)
        @js
        def main():
            value = produce()
            print(bool(value), 1 if value else 0, not value)
            original: {concrete} = {source}
            consume(original, original)
            consume(value=original, original=original)
            callback: Callable[[Iterable[int], {concrete}], None] = consume
            callback(original, original)
        main()
    ''')


def test_abstract_iterable_application_truth_and_iteration_stay_reachable():
    assert_semantics('''
        from collections.abc import Callable, Iterable, Iterator
        from pyjs import js
        @js
        class Rows:
            def __bool__(self) -> bool:
                print("truth")
                return False
            def __iter__(self) -> Iterator[int]:
                print("iterate")
                return iter([3, 4])
        @js
        def produce() -> Iterable[int]:
            return Rows()
        @js
        def consume(value: Iterable[int]) -> int:
            print(bool(value), 1 if value else 0)
            return sum(value)
        @js
        def callback() -> Callable[[Rows], int]:
            return consume
        @js
        def main():
            print(consume(produce()), callback()(Rows()))
        main()
    ''')


@pytest.mark.parametrize("concrete", ["dict[str, int]", "Row"])
@pytest.mark.parametrize("abstract", [False, True])
@pytest.mark.parametrize("body", [
    "print(str(sorted(set(values))))", "print(str(sorted({*values})))",
    "print(str([*values]))", "print(str(list((*values,))))", "print(*values)",
    "join(*values)", "print('a' in values, 'z' not in values)",
])
def test_mapping_iterable_consumers_select_keys(concrete, abstract, body):
    assert_semantics(f'''
        from collections.abc import Iterable
        from typing import TypedDict
        from pyjs import js
        class Row(TypedDict):
            a: int
            b: int
        @js
        def join(left: str, right: str):
            print(left + right)
        @js
        def consume(values: {"Iterable[str]" if abstract else concrete}):
            {body}
            print(str([item for item in values]))
        @js
        def main():
            value: {concrete} = {{'a': 30, 'b': 40}}
            consume(value)
        main()
    ''')


def test_math_distance_consumes_mapping_keys_through_iterable():
    assert_semantics('''
        import math
        from collections.abc import Iterable
        from pyjs import js
        @js
        def distance(left: Iterable[float], right: Iterable[float]) -> float:
            return math.dist(left, right)
        @js
        def main():
            left: dict[float, int] = {1.0: 30, 2.0: 40}
            right: dict[float, int] = {4.0: 50, 6.0: 60}
            print(distance(left, right) == 5.0)
        main()
    ''')


def test_mapping_union_spread_evaluates_source_once():
    assert_semantics('''
        from pyjs import js
        @js
        def source(mapping: bool) -> dict[str, int] | list[str]:
            print("source")
            return {"a": 1, "b": 2} if mapping else ["a", "b"]
        @js
        def main():
            print(str([*source(True)]), str([*source(False)]))
        main()
    ''')


@pytest.mark.parametrize("abstract", [False, True])
def test_native_constructor_consumes_mapping_keys(abstract):
    annotation = "Iterable[str]" if abstract else "dict[str, int]"
    assert_semantics(f'''
        from collections.abc import Iterable
        from pyjs import js
        @js.native
        class Set:
            def __init__(self, values: Iterable[str]):
                self.values = set(values)
            def has(self, value: str) -> bool:
                return value in self.values
        @js
        def consume(values: {annotation}):
            first = Set(values)
            second = Set(values)
            print(first.has('a'), second.has('b'))
            print(str(list(values)))
        @js
        def main():
            consume({{'a': 1, 'b': 2}})
        main()
    ''')


@pytest.mark.parametrize("expression", [
    "Set(left if flag else right)",
    "Set(*pack(left if flag else right))",
    "Set(*(), left if flag else right)",
    "Set(*(left if flag else right,), *())",
])
def test_native_host_acquisition_preserves_expression_and_expansion(expression):
    assert_semantics(f'''
        from collections.abc import Iterable
        from pyjs import js
        @js.native
        class Set:
            def __init__(self, values: Iterable[str]):
                self.values = set(values)
            def has(self, value: str) -> bool:
                return value in self.values
        @js
        def pack(values: dict[str, int]) -> tuple[dict[str, int]]:
            print('pack')
            return (values,)
        @js
        def check(flag: bool):
            left = {{'a': 1}}
            right = {{'b': 2}}
            result = {expression}
            print(result.has('a'), result.has('b'))
            print(str(list(left)), str(list(right)))
        @js
        def main():
            check(True)
            check(False)
        main()
    ''')


@pytest.mark.parametrize("source_type", ["Iterable[str]", "dict[str, int]", "list[str]"])
@pytest.mark.parametrize("expression", ["Set(values)", "Set(*(values,))"])
def test_native_host_optional_iterable_preserves_absence(source_type, expression):
    present = "{'a': 1}" if source_type.startswith("dict") else "['a']"
    assert_semantics(f'''
        from collections.abc import Iterable
        from pyjs import js
        @js.native
        class Set:
            def __init__(self, values: Iterable[str] | None = None):
                self.values = set() if values is None else set(values)
            def has(self, value: str) -> bool:
                return value in self.values
        @js
        def check(values: {source_type} | None):
            result = {expression}
            print(result.has('a'))
        @js
        def main():
            check(None)
            check({present})
            print(Set(*()).has('a'))
        main()
    ''')


def test_native_host_expansion_binds_multiple_parameters_after_evaluation():
    from pyjs.javascript.source import compile_source
    from pyjs.tooling.node import Node

    source = '''
        from collections.abc import Iterable
        from pyjs import js
        @js.native
        class Host:
            def combine(self, left: Iterable[str], separator: str, right: Iterable[str]) -> str:
                return ''.join(left) + separator + ''.join(right)
        @js
        def receiver() -> Host:
            print('receiver')
            return Host()
        @js
        def pack(key: str) -> tuple[dict[str, int]]:
            print(key)
            return ({key: 1},)
        @js
        def separator() -> str:
            print('separator')
            return ':'
        @js
        def main():
            print(receiver().combine(*pack('a'), separator(), *pack('b')))
        main()
    '''
    # A small real JS host implementation lets the test cover a method with
    # multiple Iterable parameters without requiring a browser/network API.
    with compile_source(source) as compilation:
        javascript = '''
            globalThis.Host = class {
                combine(left, separator, right) {
                    return [...left].join('') + separator + [...right].join('');
                }
            };
        ''' + compilation.javascript + '\n__pyjsEntry__.main();'
    expected = run_python(source)
    actual = Node().run_javascript(javascript)
    assert expected.returncode == actual.returncode == 0
    assert expected.stderr == actual.stderr == ''
    assert expected.stdout == actual.stdout == 'receiver\na\nseparator\nb\na:b\n'


@pytest.mark.parametrize("body", [
    "print(Set(await get()).has('a'))",
    "print(Set(*(await get(),)).has('a'))",
    "print(str([*await get()]))",
    "print(str(list(await get())))",
    "print(str(sorted(set(await get()))))",
    "print(str([key for key in await get()]))",
    "print(str(sorted({key for key in await get()})))",
    "print(str({key: 1 for key in await get()}))",
    "print(str([key for key in await get() for repeat in range(1)]))",
    "for key in await get(): print(key)",
    "print((await get()).get('a'))",
])
def test_awaited_mapping_acquisition_parenthesizes_the_resolved_value(body):
    assert_semantics(f'''
        import asyncio
        from collections.abc import Iterable
        from pyjs import js
        @js.native
        class Set:
            def __init__(self, values: Iterable[str]):
                self.values = set(values)
            def has(self, value: str) -> bool:
                return value in self.values
        @js
        async def get() -> dict[str, int]:
            print('get')
            return {{'a': 1}}
        @js
        async def main():
            {body}
        asyncio.run(main())
    ''')


@pytest.mark.parametrize("method", ["keys", "values", "items"])
def test_application_mapping_view_names_still_acquire_python_iterables(method):
    assert_semantics(f'''
        from collections.abc import Iterable
        from pyjs import js
        @js
        class Names:
            def {method}(self) -> Iterable[str]:
                return {{'a': 1, 'b': 2}}
        @js
        def main():
            print(str([name for name in Names().{method}()]))
        main()
    ''')


@pytest.mark.parametrize("method", ["keys", "values"])
@pytest.mark.parametrize("application_first", [False, True])
def test_mixed_union_mapping_views_require_runtime_acquisition(method, application_first):
    members = ["dict[str, str]", "Names"]
    if application_first:
        members.reverse()
    assert_semantics(f'''
        from pyjs import js
        @js
        class Names:
            def {method}(self) -> dict[str, int]:
                print('application')
                return {{'z': 1}}
        @js
        def show(source: {" | ".join(members)}):
            for item in source.{method}():
                print(item)
            print(str([item for item in source.{method}()]))
            print(str([*source.{method}()]))
            view = source.{method}
            alias = view
            for item in alias():
                print(item)
            print(str([item for item in view()]))
            print(str([*view()]))
            callbacks = [view]
            print(str([*callbacks[0]()]))
        @js
        def main():
            show({{'a': 'x'}})
            show(Names())
            for source in [{{'b': 'y'}}, Names()]:
                print(str([item for item in source.{method}()]))
        main()
    ''')


def test_extracted_union_callback_preserves_result_type_and_representation():
    from tests.backend_semantics import UNION_CALLBACK_RESULT_CONTRACT
    assert_semantics(UNION_CALLBACK_RESULT_CONTRACT.print_source + "\nmain()\n")


def test_direct_union_call_preserves_result_type_and_representation():
    from tests.backend_semantics import DIRECT_UNION_RESULT_CONTRACT
    assert_semantics(DIRECT_UNION_RESULT_CONTRACT.print_source + "\nmain()\n")


def test_generic_union_orders_keep_item_representations_in_one_compilation():
    from tests.backend_semantics import GENERIC_UNION_ORDER_CONTRACT
    assert_semantics(GENERIC_UNION_ORDER_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("expression", ["callback()", "source.value()", "(source.value)()"])
@pytest.mark.parametrize("members", ["Narrow | TextResult", "TextResult | Narrow"])
def test_async_union_call_preserves_awaited_result(expression, members):
    opposite = " | ".join(reversed(members.split(" | ")))
    assert_semantics(f'''
        import asyncio
        from pyjs import js, int8
        @js
        class Narrow:
            async def value(self) -> int8:
                return int8(127)
        @js
        class TextResult:
            async def value(self) -> str:
                return 'text'
        @js
        async def show(source: {members}):
            callback = source.value
            result = await {expression}
            if isinstance(result, int):
                print(result + 1)
            else:
                print(result)
        @js
        async def other(source: {opposite}):
            callback = source.value
            result = await {expression}
            if isinstance(result, int):
                print(result + 1)
            else:
                print(result)
        @js
        async def main():
            await show(Narrow())
            await show(TextResult())
            await other(Narrow())
            await other(TextResult())
        asyncio.run(main())
    ''')


def test_shared_callable_values():
    assert_semantics(CALLABLE_VALUE_CONTRACT.print_source + "\nmain()\n")


def test_generic_forwarded_callbacks_keep_numeric_representations():
    assert_semantics('''
        from collections.abc import Callable
        from pyjs import int8, js

        @js
        def narrow(value: int8) -> int8:
            return value + int8(1)

        @js
        def identity[T](value: T) -> T:
            return value

        @js
        def accept[T](callback: Callable[..., T]) -> int:
            return 11

        @js
        def invoke[T](callback: Callable[[T], T], value: T) -> T:
            return callback(value)

        @js
        def main() -> None:
            callback: Callable[[int8], int8] = narrow
            forwarded = identity(callback)
            print(accept(callback=forwarded))
            print(invoke(callback=forwarded, value=int8(127)))

        main()
    ''')


@pytest.mark.parametrize("contract", [COMPREHENSION_CONTRACT, ITERATOR_CALLBACK_CONTRACT],
                         ids=["comprehensions", "iterator-callbacks"])
def test_shared_comprehensions_and_callback_iterators(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


def test_shared_lambda_closures():
    assert_semantics(LAMBDA_CLOSURE_CONTRACT.print_source + "\nmain()\n")


def test_shared_nested_conditional_order():
    assert_semantics(NESTED_CONDITIONAL_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("reverse", [False, True])
def test_static_array_sort_key_preserves_portable_arithmetic(reverse):
    assert_semantics(f'''
        from pyjs import js, StaticArray, int8

        @js
        def key(value: int8) -> int8:
            return value + 1

        @js
        def main():
            values = StaticArray[int8, 2]([1, 127])
            expected = sorted(values, key=key, reverse={reverse})
            values.sort(key=key, reverse={reverse})
            assert values[0] == expected[0] and values[1] == expected[1]
            print(int(values[0]), int(values[1]))

        main()
    ''')


def test_empty_tuple_does_not_erase_generic_item_representation():
    assert_semantics('''
        from collections.abc import Iterable
        from pyjs import js, int8, float32

        @js
        def choose[T](values: Iterable[T], initial: T) -> T:
            for value in values:
                return value
            return initial

        @js
        def main():
            print(choose((), int8(127)) + int8(1))
            print(choose((), float32(1.5)) + float32(2.0))
            print(choose(initial=int8(127), values=()) + int8(1))
            print(len(list(())), len(set(())))
            for value in iter(()):
                print("unreachable")

        main()
    ''')


def test_eager_collection_contract():
    assert_semantics(EAGER_COLLECTION_CONTRACT.print_source + "\nmain()\n")


def test_lazy_iterator_contract():
    assert_semantics(LAZY_ITERATOR_CONTRACT.print_source + "\nmain()\n")


def test_shared_evaluation_order_contract():
    assert_semantics(EVALUATION_ORDER_CONTRACT.print_source + "\nmain()\n")


def test_shared_scalar_numeric_contract():
    assert_semantics(SCALAR_NUMERIC_CONTRACT.print_source + "\nmain()\n")


def test_shared_represented_rounding_contract():
    assert_semantics(REPRESENTED_ROUNDING_CONTRACT.print_source + "\nmain()\n")


def test_shared_application_rounding_contract():
    assert_semantics(APPLICATION_ROUNDING_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("contract", [ASSERT_NARROWING_CONTRACT, ASSERT_FAILURE_CONTRACT, ASSERT_CAPTURE_CONTRACT, ASSERT_BOOLEAN_FLOW_CONTRACT])
def test_shared_assert_narrowing_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


def test_shared_membership_order_contract():
    assert_semantics(MEMBERSHIP_ORDER_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("contract", [FIELD_ASSIGNMENT_CONTRACT, LITERAL_FIELD_ASSIGNMENT_CONTRACT,
                                     INHERITED_FIELD_ASSIGNMENT_CONTRACT, CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT],
                         ids=["field", "literal_field", "inherited_field", "class_declared_field"])
def test_shared_field_assignment_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


def test_shared_mapping_assignment_contract():
    assert_semantics(MAPPING_ASSIGNMENT_CONTRACT.print_source + "\nmain()\n")


def test_augmented_property_calls_receiver_getter_rhs_and_setter_once():
    assert_semantics("""
        from pyjs import js

        @js
        class Counter:
            def __init__(self, events: list[int]):
                self.events = events
                self.value = 5

            @property
            def count(self) -> int:
                self.events.append(2)
                return self.value

            @count.setter
            def count(self, value: int) -> None:
                self.events.append(4)
                self.value = value

        @js
        def target(counter: Counter) -> Counter:
            counter.events.append(1)
            return counter

        @js
        def replacement(counter: Counter) -> int:
            counter.events.append(3)
            return 8

        events: list[int] = []
        counter = Counter(events)
        target(counter).count += replacement(counter)
        for event in events:
            print(event)
        print(counter.value)
    """)


def test_slice_assignment_captures_bounds_in_python_order():
    assert_semantics("""
        from pyjs import js

        @js
        def target(events: list[str], values: list[int]) -> list[int]:
            events.append("target")
            return values

        @js
        def bound(events: list[str], value: int) -> int:
            events.append("bound" + str(value))
            return value

        @js
        def replacement(events: list[str]) -> list[int]:
            events.append("replacement")
            return [8]

        events: list[str] = []
        values = [1, 2, 3]
        target(events, values)[bound(events, 0):bound(events, 1)] = replacement(events)
        target(events, values)[bound(events, 0):bound(events, 1):bound(events, 1)] += replacement(events)
        print("|".join(events))
        for value in values:
            print(value)
    """)


def test_typing_cast_refines_static_types_without_changing_values():
    assert_semantics(
        """\
        from pyjs import js
        from typing import cast

        @js
        def label(value: object) -> str:
            text = cast(str, value)
            return text.lower()

        print(label("READY"))
        """
    )


def test_string_upper_matches_python():
    assert_semantics(
        """\
        print("PyJS 0.0.3".upper())
        """
    )


def test_immediately_invoked_lambdas_match_python():
    assert_semantics(
        """\
        print((lambda: 3)())
        print((lambda value: 4)(2))
        """
    )


def test_string_title_matches_python_word_boundaries():
    assert_semantics(
        """\
        print("sample primitive".title())
        print("they're BILL'S".title())
        print("42meaning-of_life".title())
        print("".title())
        """
    )


def test_inline_calls_preserve_bound_method_receivers():
    assert_semantics(
        """\
        from collections.abc import Callable
        from pyjs import js

        @js.inline("{callback}")
        def keep(
            callback: Callable[[int], str],
        ) -> Callable[[int], str]:
            return callback

        @js
        class Formatter:
            def __init__(self, prefix: str):
                self.prefix = prefix

            def label(self, value: int) -> str:
                return self.prefix + str(value)

        formatter = Formatter("item-")
        positional = keep(formatter.label)
        keyword = keep(callback=formatter.label)
        print(positional(1), keyword(2))
        """
    )


def test_conditional_function_values_match_python_semantics():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def increment(value: int) -> int:
            return value + 1

        @js
        def double(value: int) -> int:
            return value * 2

        print((increment if True else double)(3))
        print((increment if False else double)(3))
        """
    )


def test_javascript_reserved_identifiers_preserve_python_semantics():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def default(static: int, package: int = 1) -> int:
            delete = static + package
            return delete

        print(default(2, package=3))
        """
    )


def test_for_and_while_else_follow_break_semantics():
    assert_semantics(
        """\
        for value in [1, 2]:
            if value == 3:
                break
        else:
            print("for complete")

        for value in [1, 2]:
            if value == 2:
                break
        else:
            print("unreachable")

        count = 0
        while count < 2:
            count += 1
        else:
            print("while complete")

        while True:
            break
        else:
            print("unreachable")

        for outer in [1]:
            for inner in [1]:
                break
        else:
            print("outer complete")
        """
    )


def test_inline_function_uses_same_semantics_when_called_or_passed_as_value():
    assert_semantics(
        """\
        from pyjs import js

        @js.inline("({value} * {value})")
        def square(value: int) -> int:
            return value * value

        @square.value
        def square(value: int) -> int:
            return value * value

        @js
        def apply(callback: callable, value: int) -> object:
            return callback(value)

        print(square(3), apply(square, 4))
        """
    )


def test_builtin_uses_same_semantics_when_called_or_passed_as_value():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def apply(callback: callable, value: object) -> object:
            return callback(value)

        numbers = [1, 2, 3]
        print(len(numbers), apply(len, numbers))
        print(abs(-4), apply(abs, -4))
        """
    )


def test_builtin_values_dispatch_custom_dunders_and_plain_object_length():
    assert_semantics(
        """\
        from typing import TypedDict

        from pyjs import js

        class SizedRecord(TypedDict):
            length: int
            count: int

        @js
        class Box:
            def __init__(self, name: str, size: int):
                self.name = name
                self.size = size

            def __len__(self) -> int:
                return self.size

        @js
        class Distance:
            def __init__(self, name: str, magnitude: int):
                self.name = name
                self.magnitude = magnitude

            def __abs__(self) -> int:
                return self.magnitude

        @js
        def apply(callback: callable, value: object) -> object:
            return callback(value)

        length: callable = len
        absolute: callable = abs
        boxes = [Box("large", 10), Box("small", 2)]
        distances = [Distance("far", 5), Distance("near", 2)]
        record = SizedRecord(length=99, count=1)
        print(min(boxes, key=len).name, apply(length, boxes[1]))
        print(min(distances, key=abs).name, apply(absolute, distances[1]))
        print(len(record), apply(length, record))
        """
    )


def test_getattr_resolves_typed_fields_methods_and_static_defaults():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Item:
            def __init__(self, name: str):
                self.name = name

            def label(self) -> str:
                return self.name + "!"

        @js
        class SpecialItem(Item):
            def label(self) -> str:
                return self.name + "?"

        @js
        def fallback() -> str:
            print("evaluated")
            return "fallback"

        @js
        def special_item() -> Item:
            return SpecialItem("special")

        item = Item("test")
        print(getattr(item, "name"))
        print(getattr(item, "label")())
        print(getattr(item, "missing", "fallback"))
        print(getattr(item, "name", fallback()))
        print(getattr(item, "label", fallback())())
        print(getattr(item, "missing", fallback()))
        print(getattr(special_item(), "label", fallback())())
        """
    )


def test_getattr_preserves_types_and_emits_direct_access():
    at(
        """
        from pyjs import js

        @js
        class Item:
            def __init__(self, name: str):
                self.name = name

        def main():
            item = Item("test")
            name = getattr(item, "name")
            missing = getattr(item, "missing", 3)
        """,
        """
        class Item:

            def __init__(name: str) -> None:
                self.name = name

        def main() -> None:
            item: Item = Item('test')
            name: str = item.name
            missing: int = getattr(item, 'missing', 3)
        """,
        """
        export class Item {

            constructor(name) {
                this.name = name;
            }
        }

        export function main() {
            var item = new Item('test');
            var name = item.name;
            var missing = ((obj,name,fallback)=>{if(!(name in Object(obj)))return fallback;const value=obj[name];return typeof value==='function'?value.bind(obj):value;})(item,'missing',3);
        }
        """,
    )


def test_getattr_requires_a_literal_attribute_name():
    ad(
        """\
        from pyjs import js

        @js
        class Item:
            def __init__(self):
                self.name = "test"

        def main():
            field = "name"
            value = getattr(Item(), field)
        """,
        """
          File "dynamic_getattr.py", line 10
            value = getattr(Item(), field)
                                    ^^^^^
        pyjs.CompilationError: getattr() requires a string literal attribute name [PYJS1104]
        help: Use direct typed attribute access or branch on the name before calling getattr().
        """,
        filename="dynamic_getattr.py",
    )


def test_typed_recursive_functions_use_their_declared_return_type():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def factorial(value: int) -> int:
            if value <= 1:
                return 1
            return value * factorial(value - 1)

        print(factorial(6))
        """
    )


def test_typed_recursion_has_normal_javascript_calls():
    at(
        """\
        @js
        def factorial(value: int) -> int:
            if value <= 1:
                return 1
            return value * factorial(value - 1)

        def main():
            result = factorial(6)
        """,
        """
        def factorial(value: int) -> int:
            if value.[int]__le__!(1):
                return 1
            return value.[int]__mul__!(factorial(value.[int]__sub__!(1)))

        def main() -> None:
            result: int = factorial(6)
        """,
        """
        export function factorial(value) {
            if (value <= 1) {
                return 1;
            }
            return value * factorial(value - 1);
        }

        export function main() {
            var result = factorial(6);
        }
        """,
    )


def test_mutually_recursive_functions_use_declared_return_types():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def even(value: int) -> bool:
            if value == 0:
                return True
            return odd(value - 1)

        @js
        def odd(value: int) -> bool:
            if value == 0:
                return False
            return even(value - 1)

        print(even(8))
        print(odd(8))
        """
    )


def test_unannotated_direct_recursion_has_a_focused_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        def factorial(value: int):
            return 1 if value <= 1 else value * factorial(value - 1)

        def main():
            factorial(4)
        """,
        """
          File "direct_recursion.py", line 5
            return 1 if value <= 1 else value * factorial(value - 1)
                                                ^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Return type of recursive function 'factorial' cannot be inferred [PYJS1101]
        help: Add an explicit return annotation.
        """,
        filename="direct_recursion.py",
    )


def test_unannotated_mutual_recursion_requires_return_annotations():
    ad(
        """\
        from pyjs import js

        @js
        def even(value: int):
            return value == 0 or odd(value - 1)

        @js
        def odd(value: int):
            return value != 0 and even(value - 1)

        def main():
            even(4)
        """,
        """
          File "mutual_recursion.py", line 4
            def even(value: int):
                ^^^^
        pyjs.CompilationError: Types in dependency cycle even -> odd -> even cannot be inferred [PYJS1101]
        help: Add explicit annotations to values shared by the functions in the cycle.
        """,
        filename="mutual_recursion.py",
    )


def test_unannotated_recursive_method_has_a_focused_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        class Counter:
            def count(self, value: int):
                return 0 if value == 0 else 1 + self.count(value - 1)

        def main():
            Counter().count(4)
        """,
        """
          File "recursive_method.py", line 6
            return 0 if value == 0 else 1 + self.count(value - 1)
                                            ^^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Return type of recursive function 'count' cannot be inferred [PYJS1101]
        help: Add an explicit return annotation.
        """,
        filename="recursive_method.py",
    )


def test_recursive_generic_function_uses_its_declared_type():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def first[T](values: list[T], index: int) -> T:
            if index == 0:
                return values[0]
            return first(values, index - 1)

        print(first(["zero", "one"], 1))
        """
    )


def test_explicit_string_annotations_resolve_like_normal_annotations():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Item:
            def __init__(self, value: int):
                self.value = value

        @js
        def identity(value: "Item") -> "Item":
            return value

        print(identity(Item(42)).value)
        """
    )


def test_python_314_deferred_annotations_support_unquoted_forward_references():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def identity(value: Item) -> Item:
            return value

        @js
        class Item:
            def __init__(self, value: int):
                self.value = value

        print(identity(Item(42)).value)
        """
    )


def test_optional_values_narrow_after_loop_control_guards():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def collect(values: list[int | None], stop: bool) -> list[int]:
            result: list[int] = []
            for value in values:
                if value is None:
                    if stop:
                        break
                    continue
                result.append(value + 1)
            return result

        skipped = collect([1, None, 2], False)
        stopped = collect([1, None, 2], True)
        print(len(skipped), skipped[0], skipped[1])
        print(len(stopped), stopped[0])
        """
    )


def test_keyword_call_shapes_match_python_semantics():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def summarize(
            first: int,
            second: int = 1,
            /,
            *labels: str,
            doubled: bool = False,
            **values: int,
        ) -> int:
            result = first + second + len(labels) + values.get("extra", 0)
            return result * 2 if doubled else result

        @js
        def capture(value: int = 1, /, **named: int) -> int:
            return value + named.get("value", 0)

        print(summarize(3, 2, "a", "b", doubled=True, extra=4))
        print(capture(2), capture(value=3))
        """
    )
