import ast
from textwrap import dedent

import pytest

from pyjs.analysis.ir import (
    GeneratorInput,
    IRValidationError,
    Suspend,
    build_program_ir,
    validate_program_ir,
)
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.native.analysis import NATIVE_ENVIRONMENT


@pytest.mark.parametrize("receiving", [
    "received: Iterable[int] | None = yield 0; yield consume(received)",
    "yield consume((yield 0))",
])
def test_resume_input_retains_its_iterable_conversion_dependencies(receiving):
    with analyze_source(f'''
        from collections.abc import Generator, Iterable
        class Rows:
            def __iter__(self):
                yield 1
            def unused(self) -> int:
                return missing()
        def consume(received: Iterable[int] | None) -> int:
            return sum(received) if received is not None else -1
        def values() -> Generator[int, Rows, None]:
            {receiving}
        def main() -> int:
            return next(values())
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        rows = entry.container.search("Rows")
        values = entry.container.search("values")
        inputs = [node for block in values.ir.blocks for statement in block.body
                  for node in ast.walk(statement) if isinstance(node, GeneratorInput)]
        received = inputs[0]
        assert received.conversion_methods == (rows.find_attrs("__iter__"),)
        assert received.conversion_protocols == ((rows, ("__iter__",)), (rows, ("__bool__", "__len__")))
        view = NATIVE_ENVIRONMENT.builtins.search("Iterable")(NATIVE_ENVIRONMENT.builtins.search("int"))
        assert received.conversion_views == ((rows, view),)
        assert (rows, view) in entry.runtime_view_sources
        assert rows.find_attrs("__iter__") in entry.compilation_objects
        assert rows.find_attrs("unused") not in entry.compilation_objects
        validate_program_ir(build_program_ir(entry))


def test_application_cursor_item_views_retain_nested_protocols_before_emission():
    with analyze_source('''
        from collections.abc import Iterable, Iterator
        class Bag:
            def __iter__(self) -> Iterator[int]:
                yield 1
            def unused(self) -> int:
                return missing()
        class Child(Bag):
            def __iter__(self) -> Iterator[int]:
                yield 2
        class Cursor:
            def __init__(self, value: Bag):
                self.value = value
            def __iter__(self) -> Cursor:
                return self
            def __next__(self) -> Bag:
                return self.value
        def widen(value: Cursor) -> Iterator[Iterable[int]]:
            return value
        def main() -> int:
            return sum(next(widen(Cursor(Child()))))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        bag, child, cursor = (entry.container.search(name) for name in ("Bag", "Child", "Cursor"))
        builtins = NATIVE_ENVIRONMENT.builtins
        iterable = builtins.search("Iterable")(builtins.search("int"))
        iterator = builtins.search("Iterator")(iterable)
        assert entry.runtime_view_sources == {(cursor, iterator), (bag, iterable)}
        # No DependencyError is allowed when emission requests this signature.
        source = builtins.search("Iterator")(bag)
        assert tuple(source.generic_types.values()) == (bag,)
        assert {bag.find_attrs("__iter__"), child.find_attrs("__iter__"),
                cursor.find_attrs("__iter__"), cursor.find_attrs("__next__")} <= entry.compilation_objects
        assert bag.find_attrs("unused") not in entry.compilation_objects
        validate_program_ir(build_program_ir(entry))


def test_generator_resume_edges_and_retained_lifetimes_are_explicit():
    with analyze_source('''
        from collections.abc import Iterator

        def values(items: list[int]) -> Iterator[int]:
            copied = [1]
            yield items[0]
            yield copied[0]

        def main() -> int:
            return sum(values([3]))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def values(items: list__int) -> Iterator[int]:
                block entry:
                    copied: list[int] = new[external] list[int](1)
                    yield items.[list__int]__getitem__(0) -> resume
                block resume:
                    discard_resume_input()
                    yield copied.[list__int]__getitem__(0) -> resume_2
                block resume_2:
                    discard_resume_input()
                    return None

            def main() -> int:
                block entry:
                    return sum(values(new[external] list[int](3)))
        ''').rstrip()
        function = analysis.entry_point.container.search("values")
        assert function.ir.lifetime.returned_parameters == frozenset({"items"})
        assert function.ir.lifetime.external_parameters == frozenset({"items"})
        assert function.ir.lifetime.allocations[0].boundary is LifetimeBoundary.EXTERNAL
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        suspension = function.ir.blocks[0].body[-1]
        assert isinstance(suspension, Suspend)
        suspension.resume = "absent"
        with pytest.raises(IRValidationError, match="targets missing block"):
            validate_program_ir(program)
        suspension.resume = "resume"
        function.ir.blocks[1].arguments.append(ast.Name(id="invalid"))
        with pytest.raises(IRValidationError, match="cannot provide 1 arguments"):
            validate_program_ir(program)


def test_generator_field_and_index_receivers_follow_suspension():
    with analyze_source('''
        from collections.abc import Generator
        class Box:
            def __init__(self):
                self.value: int | None = None
        def values(box: Box, items: list[int | None]) -> Generator[int, int, None]:
            box.value = yield 1
            items[0] = yield 2
        def main() -> int:
            source = values(Box(), [None])
            return next(source)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            class Box:

                def __init__() -> None:
                    block entry:
                        store_field(self, value, None)
                        return None

            def values(box: Box, items: list__intUNoneType) -> Generator[int, int, None]:
                block entry:
                    yield 1 -> resume
                block resume:
                    store_field(box, value, resume_input())
                    yield 2 -> resume_2
                block resume_2:
                    $assignment2: int | None = resume_input()
                    items.[list__intUNoneType]__setitem__(0, $assignment2)
                    return None

            def main() -> int:
                block entry:
                    source: Generator[int, int, None] = values(new[external] Box(), new[external] list[int | None](None))
                    return next(source)
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_nested_yield_saves_prior_operands_in_frame_locals():
    with analyze_source('''
        from collections.abc import Generator
        def combine(left: int, right: int | None) -> int:
            return left
        def values(items: list[int]) -> Generator[int, int, None]:
            yield combine(items[0], (yield 0))
        def main() -> int:
            return next(values([1]))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def combine(left: int, right: int | None) -> int:
                block entry:
                    return left

            def values(items: list__int) -> Generator[int, int, None]:
                block entry:
                    $assignment1: int = items.[list__int]__getitem__(0)
                    yield 0 -> resume_2
                block resume_2:
                    $assignment2: int | None = resume_input()
                    yield combine($assignment1, $assignment2) -> resume
                block resume:
                    discard_resume_input()
                    return None

            def main() -> int:
                block entry:
                    return next(values(new[external] list[int](1)))
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_expanded_collection_is_retained_before_resuming_item_evaluation():
    with analyze_source('''
        from collections.abc import Generator
        def values(items: list[int]) -> Generator[int, int, None]:
            result = [*items, (yield 0)]
            yield len(result)
        def main() -> int:
            return next(values([1]))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def values(items: list__int) -> Generator[int, int, None]:
                block entry:
                    $assignment2: list[int | None] = new[external] list[int | None]()
                    $assignment3: list[int] = items
                    $assignment2.[list__intUNoneType]extend($assignment3)
                    yield 0 -> resume
                block resume:
                    $assignment4: int | None = resume_input()
                    $assignment5: int | None = $assignment4
                    list_append($assignment2, $assignment5)
                    result: list[int | None] = $assignment2
                    yield len(result) -> resume_2
                block resume_2:
                    discard_resume_input()
                    return None

            def main() -> int:
                block entry:
                    return next(values(new[external] list[int](1)))
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_suspended_fixed_tuple_expansion_keeps_independent_field_widths():
    with analyze_source('''
        from collections.abc import Generator
        from pyjs import int8, int64
        def values() -> Generator[int, int64, None]:
            fixed = (int8(1), int64(2))
            result = (*fixed, (yield 0))
            yield len(result)
        def main() -> int:
            return next(values())
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        function = next(function for function in program.functions if function.name == "values")
        result = next(statement.value for block in function.ir.blocks for statement in block.body
                      if isinstance(statement, ast.AnnAssign) and statement.target.id == "result")
        assert len(result.value_type.generic_types) == len(result.source.elts) == 3
        assert [analyzed_representation(value).numeric.bits for value in result.source.elts[:2]] == [8, 64]
        assert [value.numeric.bits for value in analyzed_representation(result.source).arguments[:2]] == [8, 64]


def test_generator_expression_shows_immediate_iterator_and_deferred_body():
    with analyze_source('''
        def main() -> int:
            return sum(value + 1 for value in [1, 2] if value > 1)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    return sum(generator(__comprehension_source=iter(new[external] list[int](1, 2))):
                        block entry:
                            iterator = bind_iterator(__comprehension_source)
                            jump for_next
                        block for_next:
                            branch_next iterator:
                                item value -> for_body
                                done -> for_done
                        block for_body:
                            branch value.[int]__gt__(1):
                                true -> filter_passed
                                false -> for_next
                        block filter_passed:
                            yield value.[int]__add__(1) -> resume
                        block resume:
                            jump for_next
                        block for_done:
                            return)
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))
