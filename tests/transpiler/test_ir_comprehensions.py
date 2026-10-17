import ast
from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import (
    CollectionNew,
    Comprehension,
    IRValidationError,
    build_program_ir,
    validate_program_ir,
)
from pyjs.analysis.lifetime import LifetimeBoundary, lambda_captures
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT


def test_comprehension_cfg_and_source_binding_are_visible_and_validated():
    with analyze_source('''
        def main() -> list[int]:
            values = [1, 2]
            return [value + 1 for value in values if value > 1]
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> list[int]:
                block entry:
                    values: list[int] = new[external] list[int](1, 2)
                    return comprehension(__comprehension_source=values):
                        block entry:
                            __comprehension_result: list[int] = new[unresolved] list[int]()
                            iterator = iter(__comprehension_source)
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
                            list_append(__comprehension_result, value.[int]__add__(1))
                            jump for_next
                        block for_done:
                            return __comprehension_result
        ''').rstrip()
        entry = analysis.entry_point
        allocation, = entry.ir.lifetime.allocations
        assert allocation.boundary is LifetimeBoundary.EXTERNAL
        node = entry.ir.blocks[0].body[-1].value
        assert isinstance(node, Comprehension)
        assert lambda_captures(node.function) == {}
        program = build_program_ir(entry)
        validate_program_ir(program)
        node.function.blocks[1].body[0].body = "absent"
        with pytest.raises(IRValidationError, match="targets missing block"):
            validate_program_ir(program)


def test_comprehension_sources_are_lowered_once_and_captures_are_lexical():
    with analyze_source('''
        def main() -> list[list[int]]:
            extra = 10
            return [[extra + a + b for b in [1, 2]] for a in [3, 4]]
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        entry = analysis.entry_point
        outer = entry.ir.blocks[0].body[-1].value
        assert tuple(lambda_captures(outer.function)) == ("extra",)
        inner = next(value for value in ast.walk(outer.function) if isinstance(value, Comprehension))
        assert tuple(lambda_captures(inner.function)) == ("extra", "a")
        for value in (inner, outer):
            assert isinstance(value.source, CollectionNew)
            assert isinstance(value.source.source, ast.List)
        validate_program_ir(build_program_ir(entry))


@pytest.mark.parametrize("inner", ['["a"]', '[int8(1)]'])
def test_incompatible_reused_comprehension_targets_have_a_diagnostic(inner):
    with pytest.raises(CompilationError, match="targets cannot change type or representation"):
        with analyze_source(f'''
            from pyjs import int8

            def main() -> int:
                return len([value for value in [1] for value in {inner}])
        ''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


@pytest.mark.parametrize("loops", ["for later in later", "for later in other for other in later"])
def test_cyclic_comprehension_target_types_have_a_located_diagnostic(loops):
    with pytest.raises(CompilationError, match="cannot infer cyclic comprehension target types"):
        with analyze_source(f'''
            def main() -> int:
                later = [1]
                other = [2]
                return len([x for x in [1] {loops}])
        ''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass
