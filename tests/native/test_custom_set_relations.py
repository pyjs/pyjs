import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("container", ["set", "frozenset"])
def test_callback_key_relations_without_construction(tmp_path, optimize, container):
    result = LLVM().assert_matches_python(f'''
        def compare(left: {container}[tuple[int, int]] | None,
                    right: {container}[tuple[int, int]] | None) -> int:
            if left is None or right is None:
                return 0
            return 0 if left.issubset(right) and left.issuperset(right) and not left.isdisjoint(right) else 1

        def main() -> int:
            return compare(None, None)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_subset_and_intersection_hash_once_and_stop_after_distinct_matches(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.hashes = 0
            def __hash__(self) -> int:
                self.hashes += 1
                gc_collect()
                if self.hashes > 1: raise ValueError('rehashed incoming key')
                return self.number
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def run(subset: bool) -> str:
            receiver = {Key(1), Key(2)}
            first, duplicate, second, tail = Key(1), Key(1), Key(2), Key(9)
            values = iter([first, duplicate, second, tail])
            if subset:
                matched = receiver.issubset(values)
            else:
                common = receiver.intersection(values)
                matched = len(common) == 2 and any(key is first for key in common)
            gc_collect()
            return str((matched, next(values) is tail, first.hashes, duplicate.hashes,
                        second.hashes, tail.hashes))
        def main() -> str:
            gc_set_threshold(1)
            return run(False) + '|' + run(True)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_empty_local_identity_key_containers_need_no_constructor_or_method(tmp_path):
    result = LLVM().assert_matches_python('''
        class Key:
            pass
        def main() -> int:
            values: dict[Key, int] = {}
            keys: list[frozenset[Key]] = []
            nested = dict.fromkeys(keys, 7)
            return len(values) + len(nested)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation", ["frozenset[Key]", "frozenset[frozenset[Key]]", "tuple[frozenset[Key], int]"])
def test_empty_nested_keys_reach_comparison_dependencies_without_constructors(tmp_path, annotation):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __hash__(self) -> int: return 1
            def __eq__(self, other: 'Key') -> bool: return True
        def main() -> int:
            keys: list[{annotation}] = []
            values = dict.fromkeys(keys, 7)
            return len(values)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_hash_uses_captured_member_hashes_without_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.fail = False
            def __hash__(self) -> int:
                if self.fail: raise ValueError('unexpected hash')
                return self.number
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            a, b = Key(1), Key(1)
            first, second = frozenset([a]), frozenset([b])
            nested = frozenset([first])
            a.fail = True
            b.fail = True
            before = hash(first)
            mapping = {first: 10}
            gc_collect()
            a.number = 7
            b.number = 7
            empty: frozenset[Key] = frozenset()
            return str((hash(first) == before, hash(first) == hash(second),
                        mapping[second], hash(nested) == hash(nested),
                        hash(empty) == hash(frozenset[Key]())))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_cached_reference_set_relations_and_nested_frozenset_keys(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int, hashes: list[int]):
                self.number = number
                self.hashes = hashes
            def __hash__(self) -> int:
                self.hashes.append(self.number)
                return self.number
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            hashes: list[int] = []
            empty: set[Key] = set()
            one = {Key(1, hashes)}
            same = {Key(1, hashes)}
            two = {Key(1, hashes), Key(2, hashes)}
            distinct = {Key(3, hashes)}
            frozen = frozenset(two)
            hashes.clear()
            answers: list[bool] = []
            for left in [empty, one, same, two, distinct]:
                for right in [empty, one, same, two, distinct]:
                    answers.extend([left == right, left != right, left < right,
                                    left <= right, left > right, left >= right,
                                    left.issubset(right), left.issuperset(right),
                                    left.isdisjoint(right)])
            answers.extend([one < frozen, frozen >= same, one.issubset(frozen),
                            frozen.isdisjoint(distinct)])
            # Relations consume stored hashes, including mixed set/frozenset.
            before = len(hashes)
            mapping = {frozenset(one): 10}
            gc_collect()
            return str((answers, before, mapping[frozenset(same)]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("operation", ["left <= right", "left == right", "left.isdisjoint(right)"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_set_relation_retains_current_key_across_source_clear(tmp_path, operation, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.active = False
                self.source: set[Key] = set()
            def __hash__(self) -> int: return self.number
            def __eq__(self, other: 'Key') -> bool:
                if self.active:
                    self.active = False
                    self.source.clear()
                    gc_collect()
                return self.number == other.number
        def arm(source: set[Key], target: set[Key]) -> None:
            for key in source:
                key.source = target
                key.active = True
        def main() -> str:
            gc_set_threshold(1)
            left, right = {{Key(1)}}, {{Key(1)}}
            # No separate local retains either key during the comparison.
            arm(left, right)
            arm(right, left)
            matched = {operation}
            gc_collect()
            return str((matched, len(left), len(right)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_set_relation_size_guards_precede_raising_callbacks_and_allow_retry(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.fail = False
            def __hash__(self) -> int: return self.number
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                if self.fail: raise ValueError('comparison failed')
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            key = Key(1)
            left, same, larger = {key}, {Key(1)}, {Key(1), Key(2)}
            key.fail = True
            guarded = (same < left, same > left, larger <= left,
                       larger == left, larger != left, left.isdisjoint(left))
            error = ''
            try:
                matched = same == left
            except ValueError as caught:
                error = str(caught)
            key.fail = False
            gc_collect()
            return str((guarded, error, same == left))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
