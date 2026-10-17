from textwrap import dedent

from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT


def test_empty_starred_rest_allocation_is_typed_before_target_stores():
    with analyze_source('''
        def main() -> int:
            rest: list[int] = []
            first, *rest = (1,)
            return first + len(rest)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    rest: list[int] = new[local] list[int]()
                    $assignment1: tuple[int] = new[local] tuple[int](1)
                    $assignment5: int = len($assignment1)
                    branch $assignment5.[int]__lt__(1):
                        true -> if_true
                        false -> if_done
                block if_true:
                    raise ValueError(f"not enough values to unpack (expected at least 1, got {format($assignment5, '')})")
                block if_done:
                    $assignment6: int = $assignment1.[tuple__int]__getitem__(0)
                    $assignment8: list[int] = new[local] list[int]()
                    first: int = $assignment6
                    rest = $assignment8
                    return first.[int]__add__(len(rest))
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))


def test_native_unpacking_checks_and_snapshots_precede_stores():
    with analyze_source('''
        def main() -> int:
            values = [1, 2]
            left, right = values
            return left + right
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    values: list[int] = new[local] list[int](1, 2)
                    $assignment1: list[int] = values
                    $assignment5: int = len($assignment1)
                    branch $assignment5.[int]__lt__(2):
                        true -> if_true
                        false -> if_done
                block if_true:
                    raise ValueError(f"not enough values to unpack (expected 2, got {format($assignment5, '')})")
                block if_done:
                    branch $assignment5.[int]__gt__(2):
                        true -> if_true_2
                        false -> if_done_2
                block if_true_2:
                    raise ValueError(f"too many values to unpack (expected 2, got {format($assignment5, '')})")
                block if_done_2:
                    $assignment6: int = $assignment1.[list__int]__getitem__(0)
                    $assignment7: int = $assignment1.[list__int]__getitem__(1)
                    left: int = $assignment6
                    right: int = $assignment7
                    return left.[int]__add__(right)
        ''').rstrip()
        validate_program_ir(build_program_ir(analysis.entry_point))
