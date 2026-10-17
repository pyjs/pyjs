from pyjs.testing.helpers import ad, at


def test_basic_for_loop():
    at(
        """
        def main():
            l = ["a", "b", "c"]
            for i in l:
                x = i
        """,
        """
        def main() -> None:
            l: list[str] = ['a', 'b', 'c']
            for i: str in l:
                x: str = i
        """,
        """
        export function main() {
            var l = ['a', 'b', 'c'];
            for (var i of l) {
                var x = i;
            }
        }
        """
    )
    at(
        """
        @js
        def foo():
            return ["a", "b", "c"]
        def main():
            for i in foo():
                x = i
        """,
        """
        def foo() -> list[str]:
            return ['a', 'b', 'c']

        def main() -> None:
            for i: str in foo():
                x: str = i
        """,
        """
        export function foo() {
            return ['a', 'b', 'c'];
        }

        export function main() {
            for (var i of foo()) {
                var x = i;
            }
        }
        """
    )


def test_nested_tuple_loop_target_preserves_item_types():
    at(
        """
        def main():
            values = [(1, (2, 3)), (4, (5, 6))]
            for index, (left, right) in values:
                print(index, left, right)
        """,
        """
        def main() -> None:
            values: list[tuple[int, tuple[int, int]]] = [(1, (2, 3)), (4, (5, 6))]
            for index: int, (left: int, right: int) in values:
                print(index, left, right)
        """,
        """
        export function main() {
            var values = [[1, [2, 3]], [4, [5, 6]]];
            for (var [index, [left, right]] of values) {
                console.log(index, left, right);
            }
        }
        """,
    )


def test_loop_unpacking_reports_static_arity_mismatch():
    ad(
        """\
        def main():
            values = [(1, 2, 3)]
            for left, right in values:
                print(left, right)
        """,
        """
          File "loop_arity.py", line 3
            for left, right in values:
                ^^^^^^^^^^^
        pyjs.CompilationError: cannot unpack 3 values into 2 loop targets [PYJS1103]
        help: Use one target for each statically known tuple value.
        """,
        filename="loop_arity.py",
    )


def test_loop_requires_a_typed_iterable_protocol():
    ad(
        """\
        from pyjs import js

        @js
        class MissingIterator:
            pass

        def main():
            for value in MissingIterator():
                print(value)
        """,
        """
          File "missing_iterator.py", line 8
            for value in MissingIterator():
                         ^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Type 'MissingIterator' is not iterable [PYJS1104]
        help: Define a client-side __iter__(self) -> Iterator[T] method or iterate over a supported collection.
        """,
        filename="missing_iterator.py",
    )


def test_loop_rejects_an_iter_method_with_the_wrong_return_protocol():
    ad(
        """\
        from pyjs import js

        @js
        class WrongIterator:
            def __iter__(self) -> list[int]: ...

        def main():
            for value in WrongIterator():
                print(value)
        """,
        """
          File "wrong_iterator.py", line 8
            for value in WrongIterator():
                         ^^^^^^^^^^^^^^^
        pyjs.CompilationError: Type 'WrongIterator' is not iterable [PYJS1104]
        help: Define a client-side __iter__(self) -> Iterator[T] method or iterate over a supported collection.
        """,
        filename="wrong_iterator.py",
    )


def test_iterable_arguments_check_structural_item_types():
    ad(
        """\
        from collections.abc import Iterable

        from pyjs import js

        @js
        def consume(values: Iterable[int]) -> None:
            pass

        def main():
            consume(iter(["wrong"]))
        """,
        """
          File "iterable_item_type.py", line 10
            consume(iter(["wrong"]))
                    ^^^^^^^^^^^^^^^
        pyjs.CompilationError: Argument 'values' to consume expects Iterable[int], got Iterator[str] [PYJS1104]
        help: Pass a value compatible with Iterable[int].
        """,
        filename="iterable_item_type.py",
    )


def test_break_in_for_loop_nested_in_while_loop():
    at(
        """
        def main():
            entries = ["passed", "failed"]
            while True:
                for entry in entries:
                    if entry == "passed":
                        break
                break
        """,
        """
        def main() -> None:
            entries: list[str] = ['passed', 'failed']
            while True:
                for entry: str in entries:
                    if entry.[object]__eq__!('passed'):
                        break
                break
        """,
        """
        export function main() {
            var entries = ['passed', 'failed'];
            while (true) {
                for (var entry of entries) {
                    if (entry === 'passed') {
                        break
                    }
                }
                break
            }
        }
        """
    )


def test_loop_else_runs_only_when_the_loop_does_not_break():
    at(
        """
        def main():
            for value in [1, 2]:
                if value == 2:
                    break
            else:
                print("for complete")
            while False:
                print("unreachable")
            else:
                print("while complete")
        """,
        """
        def main() -> None:
            for value: int in [1, 2]:
                if value.[int]__eq__!(2):
                    break
            else:
                print('for complete')
            while False:
                print('unreachable')
            else:
                print('while complete')
        """,
        """
        export function main() {
            let $loop_completed0 = true;
            for (var value of [1, 2]) {
                if (value == 2) {
                    $loop_completed0 = false;
                    break
                }
            }
            if ($loop_completed0) {
                console.log('for complete');
            }
            while (false) {
                console.log('unreachable');
            }
            console.log('while complete');
        }
        """,
    )


def test_continue_in_while_loop():
    at(
        """
        def main():
            value = 0
            while value < 3:
                value += 1
                if value == 2:
                    continue
                print(value)
        """,
        """
        def main() -> None:
            value: int = 0
            while value.[int]__lt__!(3):
                value = value.[int]__add__!(1)
                if value.[int]__eq__!(2):
                    continue
                print(value)
        """,
        """
        export function main() {
            var value = 0;
            while (value < 3) {
                value = value + 1;
                if (value == 2) {
                    continue
                }
                console.log(value);
            }
        }
        """,
    )


def test_while_condition_uses_python_collection_truthiness():
    at(
        """
        @js
        def consume(values: list[int]):
            while values:
                print(values.pop())

        def main():
            consume([1, 2])
        """,
        """
        def consume(values: list__int) -> None:
            while values.[list__int]__bool__!():
                print($pop_list_item(values))

        def main() -> None:
            consume([1, 2])
        """,
        """
        import { pop_list_item as $pop_list_item } from './pyjs.python.js';

        export function consume(values) {
            while (values.length) {
                console.log($pop_list_item(values));
            }
        }

        export function main() {
            consume([1, 2]);
        }
        """,
    )


def test_destructuring_tuples_for_loop():
    at(
        """
        def main():
            l = [("a", 1, ["a"]), ("b", 2, ["b"]), ("c", 3, ["c"])]
            for a, b, c in l:
                x = a
                y = b
                for d in c:
                    zz = d
                z = c
        """,
        """
        def main() -> None:
            l: list[tuple[str, int, list[str]]] = [('a', 1, ['a']), ('b', 2, ['b']), ('c', 3, ['c'])]
            for a: str, b: int, c: list[str] in l:
                x: str = a
                y: int = b
                for d: str in c:
                    zz: str = d
                z: list[str] = c
        """,
        """
        export function main() {
            var l = [['a', 1, ['a']], ['b', 2, ['b']], ['c', 3, ['c']]];
            for (var [a, b, c] of l) {
                var x = a;
                var y = b;
                for (var d of c) {
                    var zz = d;
                }
                var z = c;
            }
        }
        """
    )


def test_destructuring_dict_for_loop():
    at(
        """
        def main():
            l = {"a": {"aa": 1}}
            for a, b in l.items():
                x = a
                y = b
                for d in b.keys():
                    key = d
                for c in b.values():
                    value = c
        """,
        """
        def main() -> None:
            l: dict[str, dict[str, int]] = {'a': {'aa': 1}}
            for a: str, b: dict[str, int] in l.[dict__str_dict__str_int]items!():
                x: str = a
                y: dict[str, int] = b
                for d: str in b.[dict__str_int]keys():
                    key: str = d
                for c: int in b.[dict__str_int]values():
                    value: int = c
        """,
        """
        export function main() {
            var l = new Map([['a', new Map([['aa', 1]])]]);
            for (var [a, b] of l.entries()) {
                var x = a;
                var y = b;
                for (var d of b.keys()) {
                    var key = d;
                }
                for (var c of b.values()) {
                    var value = c;
                }
            }
        }
        """
    )
