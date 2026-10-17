from textwrap import dedent

from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT


def test_native_expansion_preserves_operands_for_runtime_binding():
    with analyze_source('''
        def collect(first: int, *, extra: int = 0) -> int:
            return first + extra

        def main(values: list[int], named: dict[str, int]) -> int:
            return collect(*values, **named)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def collect(first: int, *, extra: int=0) -> int:
                block entry:
                    return first.[int]__add__(extra)

            def main(values: list__int, named: dict__str_int) -> int:
                block entry:
                    return collect(*values, **named)
        ''').rstrip()


def test_keyword_expansion_preserves_parameter_return_and_containment_lifetimes():
    with analyze_source('''
        def choose(value: list[int]) -> list[int]:
            return value

        def relay(named: dict[str, list[int]]) -> list[int]:
            return choose(**named)

        def positional_only(value: list[int], /, **named: list[int]) -> list[int]:
            return named["value"]

        def relay_named(value: list[int], named: list[int]) -> list[int]:
            return positional_only(value, value=named)

        def retain(target: list[list[int]], value: list[int]) -> None:
            target.append(value)

        def relay_retained(target: list[list[int]], named: dict[str, list[int]]) -> None:
            retain(target, **named)

        def main() -> int:
            values = [1]
            mapping = {"value": values}
            target: list[list[int]] = []
            relay_retained(target, mapping)
            return len(relay(mapping)) + len(relay_named(values, values))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        module = analysis.entry_point.container
        assert module.search("relay").ir.lifetime.returned_parameters == frozenset({"named"})
        assert module.search("relay_named").ir.lifetime.returned_parameters == frozenset({"named"})
        assert ("target", "named") in module.search("relay_retained").ir.lifetime.parameter_containment


def test_integer_log_input_kind_survives_float_conversion():
    with analyze_source('''
        from math import log2

        def main(value: int) -> float:
            return log2(value)
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def main(value: int) -> float:
                block entry:
                    return $log2(float(value), True)
        ''').rstrip()


def test_math_coercion_is_explicit_in_analyzed_code():
    with analyze_source('''
        from math import sqrt, floor

        def main(value: int) -> float:
            return sqrt(value) + float(floor(value))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent('''\
            def sqrt(value: float, /) -> float:
                block entry:
                    branch value.[float]__lt__(0.0):
                        true -> if_true
                        false -> if_done
                block if_true:
                    raise ValueError('expected a nonnegative input, got '.[str]__add__(str(value)))
                block if_done:
                    return _calls.sqrt(value)

            def main(value: int) -> float:
                block entry:
                    return sqrt(float(value)).[float]__add__(float(int(value)))
        ''').rstrip()
