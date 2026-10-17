"""None is a Python value in storage, not an LLVM void operand."""

import ast

import pytest

from pyjs.native.llvm import FunctionEmitter, ModuleState
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize(("source", "expected"), [
    ("None", "ptr"), ("NoneType", "ptr"),
    ("int | None", "{ i1, i64 }"), ("None | float", "{ i1, double }"),
    ("bool | NoneType", "{ i1, i1 }"), ("str | None", "ptr"),
])
def test_raw_optional_annotations_distinguish_none_from_pointer_storage(source, expected):
    emitter = FunctionEmitter(ModuleState("main", "executable", False))
    assert emitter.annotation(ast.parse(source, mode="eval").body) == expected


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_collection_values_and_void_calls(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def empty(value: None = None) -> None:
            gc_collect()
            return value

        def apply(callback: Callable[[None], None]) -> None:
            callback(None)

        class Box:
            value: None
            def __init__(self):
                self.value = None

        def main() -> str:
            gc_set_threshold(1)
            values: list[None] = [None, empty()]
            values.append(None)
            values[0] = empty()
            mapping = dict.fromkeys(['a', 'b'])
            mapping['c'] = None
            assert mapping.get('missing') is None
            assert mapping.get('a', None) is None
            assert mapping.setdefault('d') is None
            assert mapping.setdefault('a', None) is None
            assert mapping.pop('absent', None) is None
            copied = dict(mapping)
            pair = (None, 3, None)
            apply(empty)
            box = Box()
            box.value = empty()
            return str((values, copied, pair, values.pop(), mapping.pop('a'),
                        box.value is None, pair[0] is None))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_storage_optional_and_erased_consumers(optimize):
    result = LLVM().assert_matches_python('''
        import json
        def inspect(value: int | None, missing: None) -> bool:
            return value == missing
        def erase(value: object) -> bool:
            return value is None
        def main() -> str:
            values = [None, None]
            mapping = dict.fromkeys([1, 2], None)
            return str((inspect(0, values[0]), inspect(None, values[0]),
                        erase(values[0]), None in values, values.count(None),
                        list(mapping.values()) == values, json.dumps(values)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_default_values_reuse_cached_custom_hashes(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.fail = False
            def __hash__(self) -> int:
                if self.fail: raise ValueError('rehash')
                return 0
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def main() -> str:
            first, second = Key(1), Key(2)
            members = {first, second}
            first.fail = True
            second.fail = True
            values = dict.fromkeys(members)
            copied = dict.fromkeys(values, None)
            third = Key(3)
            copied.setdefault(third)
            missing = copied.get(Key(99))
            absent = copied.pop(Key(99), None)
            return str((len(values), len(copied), list(values.values()), missing, absent,
                        next(iter(values)) is next(iter(members))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_iterators_keys_and_callback_results(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import repeat, chain, tee, zip_longest, groupby
        from functools import reduce

        def items() -> Iterator[None]:
            yield None
            yield None

        def widen(value: int | None) -> str:
            return str(value)

        def main() -> str:
            members: set[None] = {None}
            mapping = {None: None}
            mapping[None] = None
            members.add(None)
            first, second = tee(items())
            groups: list[tuple[None, list[int]]] = []
            for key, group in groupby([1, 2, 3], lambda value: None):
                groups.append((key, list(group)))
            empty: list[None] = []
            return str((list(first), list(second), list(repeat(None, 2)),
                        list(map(lambda value: None, [1, 2])),
                        list(zip([1], [None])), list(iter([(1, None)])),
                        list(chain([None], [None])), list(zip_longest([None], [None, None])),
                        None in members, mapping[None] is None, len(members),
                        members | {None}, members - {None}, members ^ {None}, groups,
                        list(map(widen, [None])), next(iter(empty), None),
                        next(iter([None]), 7), next(iter(empty), 7),
                        list(iter(lambda: None, None)),
                        reduce(lambda left, right: None, [None, None], None)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_host_none_values_are_checked_and_survive_promotion(tmp_path, optimize):
    library = LLVM().compile_library('''
        from pyjs.native import gc_collect
        def render(value: None, values: list[None], mapping: dict[None, None],
                   pair: tuple[int, None]) -> str:
            values.append(None)
            gc_collect()
            return str((value, values, mapping, pair))
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        for _ in range(2):
            source = [None]
            assert library.render(None, source, {None: None}, (2, None)) == "(None, [None, None], {None: None}, (2, None))"
            assert source == [None]
        with pytest.raises(TypeError, match="must be None"):
            library.render(0, [None], {None: None}, (2, None))
        with pytest.raises(TypeError, match="must be None"):
            library.render(None, [0], {None: None}, (2, None))
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_control_flow_defaults_closures_and_sequence_order(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect

        def capture(value: None) -> Callable[[], None]:
            return lambda: value

        def default(values: list[None] = [None]) -> int:
            values.append(None)
            return len(values)

        def pack(first: None, *rest: None, **named: None) -> str:
            return str((first, rest, named))

        def wrapped(events: list[str]) -> None:
            try:
                events.append('before')
                return events.append('result')
            finally:
                events.append('finally')

        def main() -> str:
            events: list[str] = []
            value = wrapped(events)
            callback = capture(value)
            gc_collect()
            values = [callback(), None]
            return str((value, callback(), events, values,
                        [None] < [None, None], [None] == [None],
                        None is values[0] is None, None == value == None,
                        value or callback(), value and callback(),
                        default(), default(), any(values), all(values),
                        pack(*values, **{'key': None})))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
