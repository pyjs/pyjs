import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_range_hash_follows_sequence_equality_without_len_overflow(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def same(left: range, right: range) -> bool:
            return left == right and hash(left) == right.__hash__()
        def main() -> str:
            gc_set_threshold(1)
            empty = range(3, 2)
            single = range(7, 8)
            ascending = range(-5, 8, 3)
            descending = range(7, -6, -3)
            wide = range(-9223372036854775808, 9223372036854775807)
            before = wide.__hash__()
            gc_collect()
            return str((same(empty, range(-10, 20, -5)),
                        same(single, range(7, 100, 99)),
                        same(ascending, range(-5, 9, 3)),
                        same(descending, range(7, -8, -3)),
                        same(wide, range(-9223372036854775808, 9223372036854775807)),
                        before == hash(wide),
                        hash(range(1, 4)) == hash((3, 1, 1)),
                        hash(empty) == hash((0, None, None)),
                        hash(single) == hash((1, 7, None))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_hash_keeps_none_bool_and_zero_step_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            values = [slice(None), slice(1), slice(1, 8), slice(True, 8, False),
                      slice(-9223372036854775808, 9223372036854775807, -1)]
            output: list[str] = []
            for value in values:
                before = value.__hash__()
                gc_collect()
                copy = slice(value.start, value.stop, value.step)
                output.append(str(before == hash(copy)))
            output.append(str(hash(slice(True, 8, False)) == hash(slice(1, 8, 0))))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_token_views_and_notimplemented_keep_reference_hashes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import div
        def main() -> str:
            gc_set_threshold(1)
            node = div('text')
            first = node.classList
            second = node.classList
            before = first.__hash__()
            singleton = NotImplemented.__hash__()
            first.add('active')
            gc_collect()
            return str((before == hash(first), first is not second,
                        first.contains('active'), second.contains('active'),
                        singleton == hash(NotImplemented)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_callable_hash_follows_original_code_and_context_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect, gc_set_threshold
        class Counter:
            __hash__ = None
            def __init__(self, start: int):
                self.start = start
            def add(self, value: int) -> int:
                return self.start + value
        def identity(value: int) -> int:
            return value
        def widen(value: Callable[[int], int]) -> Callable[[int], int | bool]:
            return value
        def closure(value: int) -> Callable[[int], int]:
            return lambda extra: value + extra
        def main() -> str:
            gc_set_threshold(1)
            counter = Counter(4)
            first = counter.add
            second = counter.add
            view = widen(first)
            captured = closure(5)
            bound = partial(identity, 8)
            function = identity
            before = (function.__hash__(), first.__hash__(), captured.__hash__(), bound.__hash__())
            gc_collect()
            after = (hash(identity), hash(second), hash(captured), hash(bound))
            return str((before == after, first == second, first is not second,
                        hash(view) == hash(first), view(3), captured(2), bound()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_hashable_value_members_support_tuple_key_lookup_across_gc(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import div
        class Counter:
            __hash__ = None
            def value(self) -> int:
                return 3
        def identity(value: int) -> int:
            return value
        def closure(value: int) -> Callable[[int], int]:
            return lambda extra: value + extra
        def main() -> str:
            gc_set_threshold(1)
            counter = Counter()
            captured = closure(4)
            bound = partial(identity, 9)
            node = div('text')
            view = node.classList
            functions: dict[tuple[Callable[[int], int], int], str] = {}
            functions[(captured, 1)] = 'closure'
            functions[(identity, 2)] = 'function'
            ranges = {(range(0, 10, 3), 'r'): 'range',
                      (range(-9223372036854775808, 9223372036854775807), 'w'): 'wide'}
            slices = {(slice(None), 0): 'none', (slice(0), 0): 'zero', (slice(False), 1): 'false'}
            methods = {(counter.value, 0): 'method'}
            partials = {(bound, 0): 'partial'}
            views = {(view, 0): 'view'}
            singleton = {(NotImplemented, 0): 'singleton'}
            members = {(range(0, 10, 3), 1)}
            view.add('active')
            gc_collect()
            output = [functions.get((captured, 1), '-'), functions.get((identity, 2), '-'),
                      functions.get((closure(4), 1), '-'), ranges.get((range(0, 12, 3), 'r'), '-'),
                      ranges.get((range(0, 13, 3), 'r'), '-'),
                      ranges.get((range(-9223372036854775808, 9223372036854775807, 1), 'w'), '-'),
                      slices.get((slice(None, None, None), 0), '-'), slices.get((slice(0), 0), '-'),
                      slices.get((slice(0), 1), '-'), str(len(slices)),
                      methods.get((counter.value, 0), '-'), methods.get((Counter().value, 0), '-'),
                      partials.get((bound, 0), '-'), partials.get((partial(identity, 9), 0), '-'),
                      views.get((view, 0), '-'), views.get((node.classList, 0), '-'),
                      singleton[(NotImplemented, 0)], str((range(0, 12, 3), 1) in members)]
            members.remove((range(0, 11, 3), 1))
            output.append(str(len(members)))
            return '|'.join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
