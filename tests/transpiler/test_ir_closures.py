import ast
from textwrap import dedent

import pytest

from pyjs.analysis.ir import (
    Branch,
    CollectionNew,
    Comprehension,
    FieldLoad,
    IRValidationError,
    Jump,
    Lambda,
    build_program_ir,
    validate_program_ir,
)
from pyjs.analysis.lifetime import LifetimeBoundary, lambda_captures
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT

SOURCE = '''
    from typing import Callable

    def record(events: list[int], value: int) -> int:
        events.append(value)
        return value

    def main() -> int:
        events: list[int] = []
        callback: Callable[[int], int] = lambda value: record(events, value) if value > 0 else 9
        return callback(3)
'''


def test_lambda_cfg_is_separate_visible_and_validated():
    with analyze_source(SOURCE, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def record(events: list__int, value: int) -> int:
                block entry:
                    list_append(events, value)
                    return value

            def main() -> int:
                block entry:
                    events: list[int] = new[external] list[int]()
                    callback: Callable[[int], int] = lambda value:
                        block entry:
                            branch value.[int]__gt__(0):
                                true -> conditional_true
                                false -> conditional_false
                        block conditional_true:
                            jump conditional_done(record(events, value))
                        block conditional_false:
                            jump conditional_done(9)
                        block conditional_done(conditional_done_value: int):
                            return conditional_done_value
                    return callback(3)
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert len(analysis.entry_point.ir.blocks) == 1
        assert analysis.entry_point.ir.lifetime.call_dependencies == ()


@pytest.mark.parametrize("damage, diagnostic", [
    ("missing", "targets missing block"),
    ("arity", "arguments; expected"),
    ("implicit", "cannot provide"),
])
def test_validator_checks_lambda_edges_in_their_own_scope(damage, diagnostic):
    with analyze_source(SOURCE, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        closure = next(node for node in ast.walk(entry.ir.blocks[0]) if isinstance(node, Lambda))
        branch = closure.blocks[0].body[-1]
        assert isinstance(branch, Branch)
        if damage == "missing":
            branch.true = "absent"
        elif damage == "arity":
            jump = closure.blocks[1].body[-1]
            assert isinstance(jump, Jump)
            jump.arguments.clear()
        else:
            closure.blocks[1].arguments.append(closure.blocks[-1].arguments[0])
        with pytest.raises(IRValidationError, match=diagnostic):
            validate_program_ir(build_program_ir(entry))


def test_lambda_dependencies_are_reachable_but_not_evaluated_by_parent():
    with analyze_source('''
        from typing import Callable

        class Box:
            def __init__(self, value: int):
                self.value = value

        def factory(value: int) -> Box:
            return Box(value)

        def main() -> int:
            value = Box(1)
            callback: Callable[[], list[Box]] = lambda: [factory(value.value)]
            value = Box(2)
            return callback()[0].value
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        program = build_program_ir(entry)
        validate_program_ir(program)
        assert {function.name for function in program.functions} >= {"factory", "__init__", "main"}
        allocations = entry.ir.lifetime.allocations
        assert len(allocations) == 2
        assert all(value.boundary is LifetimeBoundary.EXTERNAL for value in allocations)
        closure = next(node for node in ast.walk(entry.ir.blocks[0]) if isinstance(node, Lambda))
        assert tuple(lambda_captures(closure)) == ("value",)
        assert isinstance(closure.blocks[0].body[0].value, CollectionNew)
        fields = [node for node in ast.walk(closure) if isinstance(node, FieldLoad)]
        assert len(fields) == 1
        assert isinstance(fields[0].attribute, ast.Attribute)


def test_nested_lambda_does_not_capture_its_shadowed_parameter():
    with analyze_source('''
        from typing import Callable

        def make(offset: int) -> Callable[[int], Callable[[int], int]]:
            return lambda offset: lambda extra: offset + extra

        def main() -> int:
            return make(1)(2)(3)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        make = analysis.entry_point.container.search("make")
        outer = make.ir.blocks[0].body[0].value
        inner = outer.blocks[0].body[0].value
        assert lambda_captures(outer) == {}
        assert tuple(lambda_captures(inner)) == ("offset",)
        assert make.ir.lifetime.external_parameters == frozenset()


def test_expansion_temporaries_belong_to_lambda_not_enclosing_function():
    with analyze_source('''
        from collections.abc import Callable
        def main() -> int:
            items = [1]
            callback: Callable[[], list[int]] = lambda: [*items, 2]
            return len(callback())
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    items: list[int] = new[external] list[int](1)
                    callback: Callable[[], list[int]] = lambda :
                        block entry:
                            $assignment0: list[int] = new[unresolved] list[int]()
                            $assignment1: list[int] = items
                            $assignment0.[list__int]extend($assignment1)
                            list_append($assignment0, 2)
                            return $assignment0
                    return len(callback())
        ''').rstrip()
        entry = analysis.entry_point
        closure = next(node for node in ast.walk(entry.ir.blocks[0]) if isinstance(node, Lambda))
        assert closure.local_names == {"$assignment0", "$assignment1"}
        assert set(lambda_captures(closure)) == {"items"}
        assert set(entry.scope.names) == {"items", "callback"}
        validate_program_ir(build_program_ir(entry))


def test_lambda_comprehension_has_independent_nested_control_flow():
    with analyze_source('''
        from collections.abc import Callable
        def main() -> int:
            transform: Callable[[list[int]], list[int]] = lambda items: [value + 1 for value in items]
            return transform([1])[0]
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    transform: Callable[[list[int]], list[int]] = lambda items:
                        block entry:
                            return comprehension(__comprehension_source=items):
                                block entry:
                                    __comprehension_result: list[int] = new[unresolved] list[int]()
                                    iterator = iter(__comprehension_source)
                                    jump for_next
                                block for_next:
                                    branch_next iterator:
                                        item value -> for_body
                                        done -> for_done
                                block for_body:
                                    list_append(__comprehension_result, value.[int]__add__(1))
                                    jump for_next
                                block for_done:
                                    return __comprehension_result
                    return transform(new[external] list[int](1)).[list__int]__getitem__(0)
        ''').rstrip()
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        outer, = analysis.entry_point.ir.blocks
        inner = next(node for node in ast.walk(outer) if isinstance(node, Comprehension))
        outer.name = "outer_only"
        jump = next(node for node in ast.walk(inner.function) if isinstance(node, Jump))
        jump.target = outer.name
        with pytest.raises(IRValidationError, match="targets missing block outer_only"):
            validate_program_ir(program)
