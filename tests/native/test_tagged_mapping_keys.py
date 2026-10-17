import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_dictionary_mutation_copy_update_and_defaults(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values: dict[int | str, str] = {1: 'one', 'one': 'word'}
            for i in range(20):
                values[i] = 'value' + str(i)
                values['key' + str(i)] = str(i)
            copied = values.copy()
            values.clear()
            gc_collect()
            values.update(copied)
            old = values.setdefault('one', 'unused')
            new = values.setdefault('new', 'added')
            removed = values.pop('key3')
            missing = values.pop('missing', 'fallback')
            del values[4]
            gc_collect()
            keys: list[int | str] = [1, 'one', 1, 'new']
            defaults = dict.fromkeys(keys, 9)
            defaults.update({2: 8, 'two': 7})
            return str((len(values), len(copied), old, new, removed, missing,
                        values[19], values['key19'], 'key3' in values, 4 in values,
                        list(defaults.items())))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_set_operations_and_cached_frozenset_hashes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            left: set[int | str] = {1, 'one', 2}
            right: set[int | str] = {'one', 3, 'three'}
            merged = left | right
            copied = merged.copy()
            merged.clear()
            merged.update(copied)
            merged.discard(2)
            merged.remove('three')
            merged.add('four')
            common = left.intersection(right)
            narrow = left.intersection({'one'})
            alias = left
            left.intersection_update(right)
            gc_collect()
            frozen = frozenset(merged)
            equal = frozenset(copied.intersection(merged).union({'four'}))
            table = {frozen: 'found'}
            return str((left is alias, left == common, narrow == common, len(common), 'one' in common,
                        len(merged), 2 in merged, 'four' in merged, left < merged,
                        merged > left, merged.isdisjoint(right), left.issubset(merged),
                        merged.isdisjoint(['absent']), merged.issuperset(['one']), left.issubset(['one']),
                        hash(frozen) == hash(equal), table[equal]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_numeric_keys_share_python_equality_and_keep_first_payload(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values: dict[int | float | str, str] = {0: 'zero', -0.0: 'negative',
                                                   1.0: 'float', 1: 'integer', '1': 'text'}
            copied = values.copy()
            gc_collect()
            values.clear()
            values.update(copied)
            return str((list(values.items()), values[0.0], values[1.0], values[1], values['1'],
                        values.pop(-0.0), len(values)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("operation", ["update", "intersection", "toggle"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_union_key_snapshot_survives_callback_clearing_source(tmp_path, operation, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, number: int):
                self.number = number
                self.source: set[tuple[Key] | str] = set()
                self.active = False
            def __hash__(self) -> int: return 1
            def __eq__(self, other: 'Key') -> bool:
                if self.active:
                    self.active = False
                    self.source.clear()
                gc_collect()
                return self.number == other.number

        def setup(key: Key) -> None:
            source: set[tuple[Key] | str] = {{(Key(1),)}}
            key.source = source

        def main() -> str:
            gc_set_threshold(1)
            key = Key({2 if operation == 'toggle' else 1})
            setup(key)
            target: set[tuple[Key] | str] = {{(key,), 'untouched'}}
            key.active = True
            {'result = target.intersection(key.source)' if operation == 'intersection' else
             'target.symmetric_difference_update(key.source); result = target' if operation == 'toggle' else
             'target.update(key.source); result = target'}
            gc_collect()
            return str((len(result), (Key(1),) in result, len(key.source)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_keys_distinguish_none_bool_and_text_with_numeric_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values: dict[bool | int | str | bytes | None, str] = {
                None: 'none', False: 'false', 0: 'zero', True: 'true',
                1: 'one', '': 'empty', b'': 'empty bytes', 'same': 'text', b'same': 'bytes'}
            copied = values.copy()
            values.clear()
            gc_collect()
            values.update(copied)
            return str((list(values.items()), values[False], values[True], values[None],
                        values.pop(None), None in values, '' in values, values[b'same']))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_missing_union_key_formats_the_actual_payload(tmp_path):
    result = LLVM().assert_matches_python('''
        def lookup(key: int | str | None) -> str:
            values: dict[int | str | None, str] = {1: 'one'}
            try:
                return values[key]
            except KeyError as error:
                return str(error)

        def main() -> str:
            return lookup(2) + '|' + lookup('missing') + '|' + lookup(None)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_optional_key_widens_into_tagged_lookup_and_iteration(tmp_path):
    result = LLVM().assert_matches_python('''
        def lookup(key: str | None) -> str:
            values: dict[int | str | None, str] = {None: 'none', 'word': 'text', 1: 'one'}
            return values[key]

        def main() -> str:
            values: set[int | str | None] = {None, 'word', 1}
            keys: list[str | None] = [None, 'word']
            result = values.intersection(keys)
            values.update(keys)
            return str((lookup(None), lookup('word'), len(result), 'word' in result, None in result))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_difference_and_symmetric_difference_keep_tagged_payloads(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            left: set[int | str | None] = {1, 'one', None, 2}
            right: set[int | str | None] = {'one', None, 'two'}
            difference = left - right
            exclusive = left ^ right
            frozen = frozenset(left).symmetric_difference(right)
            alias = left
            left -= right
            before = left == difference
            left ^= right
            gc_collect()
            self_difference = left - left
            self_exclusive = left ^ left
            left.difference_update([None, 'one'])
            left.symmetric_difference_update(['two', 'two', 'new'])
            return str((before, alias is left, 1 in difference, 2 in difference,
                        len(difference), len(exclusive), exclusive == frozen, 'two' in exclusive,
                        len(self_difference), len(self_exclusive), len(left), 'new' in left,
                        None in left, 'two' in left))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
