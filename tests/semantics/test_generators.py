from pyjs.testing.helpers import ad, at
from tests.backend_semantics import GENERATOR_CLEANUP_CONTRACT, GENERATOR_CONTRACT

from .helpers import assert_semantics


def test_shared_generator_contract():
    assert_semantics(GENERATOR_CONTRACT.print_source + "\nmain()\n")


def test_shared_generator_cleanup_contract():
    assert_semantics(GENERATOR_CLEANUP_CONTRACT.print_source + "\nmain()\n")


def test_generator_functions_yield_lazily_and_stop_on_bare_return():
    assert_semantics(
        """\
        from collections.abc import Iterable

        from pyjs import js

        @js
        def values(limit: int) -> Iterable[int]:
            for value in range(limit):
                if value == 3:
                    return
                yield value * 2

        @js
        class Paths:
            @staticmethod
            def dirty(values: list[str]) -> Iterable[str]:
                for value in values:
                    yield value

        generated = values(5)
        for value in generated:
            print(value)
        for value in generated:
            print(value)
        for value in Paths.dirty(["modified", "staged"]):
            print(value)
        """
    )


def test_unannotated_generator_methods_infer_their_item_type():
    at(
        """
        @js
        class Values:
            def generate(self, limit: int):
                for value in range(limit):
                    yield str(value)

        def main():
            for value in Values().generate(2):
                print(value)
        """,
        """
        class Values:

            def generate(limit: int) -> Iterator[str]:
                for value: int in range(limit):
                    yield value.[int]__str__!()

        def main() -> None:
            for value: str in Values().[Values]generate(2):
                print(value)
        """,
        """
        export class Values {

            *generate(limit) {
                const $range_start0 = +(0);
                const $range_stop1 = +(limit);
                const $range_step2 = +(1);
                if ($range_step2 === 0) throw new RangeError('range() arg 3 must not be zero');
                for (let $range_index3 = $range_start0; $range_step2 > 0 ? $range_index3 < $range_stop1 : $range_index3 > $range_stop1; $range_index3 += $range_step2) {
                    var value = $range_index3;
                    yield String(value);
                }
            }
        }

        export function main() {
            for (var value of new Values().generate(2)) {
                console.log(value);
            }
        }
        """,
    )


def test_generator_return_values_have_a_focused_diagnostic():
    ad(
        """
        from pyjs import js

        @js
        def values():
            yield 1
            return 2

        @js
        def main():
            for value in values():
                print(value)
        """,
        """
          File "generator_return.py", line 7
            return 2
            ^^^^^^^^
        pyjs.CompilationError: generator return values are not supported [PYJS2001]
        help: Use a bare return to stop the generator.
        """,
        filename="generator_return.py",
    )


def test_yield_from_has_a_focused_diagnostic():
    ad(
        """
        from pyjs import js

        @js
        def values():
            yield from [1, 2]

        @js
        def main():
            for value in values():
                print(value)
        """,
        """
          File "yield_from.py", line 6
            yield from [1, 2]
            ^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: yield from is not supported [PYJS2001]
        help: Iterate over the value and yield each item explicitly.
        """,
        filename="yield_from.py",
    )


def test_generator_yields_must_match_the_declared_item_type():
    ad(
        """
        from collections.abc import Iterable

        from pyjs import js

        @js
        def values() -> Iterable[str]:
            yield 1

        @js
        def main():
            for value in values():
                print(value)
        """,
        """
          File "generator_type.py", line 7
            def values() -> Iterable[str]:
                            ^^^^^^^^^^^^^
        pyjs.CompilationError: Generator produces Iterator[int], not Iterable[str] [PYJS1105]
        help: Change the return annotation to match the yielded values.
        """,
        filename="generator_type.py",
    )


def test_generator_expression_preserves_method_receiver_and_lazy_reads():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Counter:
            def __init__(self, value: int):
                self.value = value

            def values(self):
                return (self.value + item for item in [1, 2] if item <= self.value)

            def nested(self):
                return (sum(self.value + inner for inner in [1, 2])
                        for outer in [1, 2] if outer <= self.value)

            def pairs(self):
                return (self.value + item for outer in [1, 2]
                        for item in [self.value, outer] if item > 0)

        first = Counter(1)
        second = Counter(10)
        pending = first.values()
        first.value = 3
        for value in pending:
            print(value)
        for value in second.values():
            print(value)
        for value in first.nested():
            print(value)
        for value in first.pairs():
            print(value)
        """
    )


def test_generator_expression_in_base_constructor_arguments():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class MissingKeys(Exception):
            def __init__(self, keys: list[str]):
                super().__init__(', '.join(key.upper() for key in keys))

        @js
        class Base:
            def __init__(self, total: int, values: list[int]):
                self.total = total
                self.values = values

        @js
        class Derived(Base):
            def __init__(self, values: list[int]):
                super().__init__(sum(value * 2 for value in values),
                                 list(value + 1 for value in values))

        print(str(MissingKeys(['a', 'b'])))
        result = Derived([1, 2, 3])
        print(result.total)
        for value in result.values:
            print(value)
        """
    )
