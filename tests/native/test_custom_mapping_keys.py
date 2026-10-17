from textwrap import dedent

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.semantics.helpers import run_python


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("deleted", [1, 2, 3])
def test_dict_update_same_size_callback_mutation_visits_survivors(tmp_path, optimize, deleted):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.armed = False
                self.source: dict[Key, str] = {{}}
            def __hash__(self) -> int: return 0
            def __eq__(self, other: "Key") -> bool:
                if self.armed and other.value == 2:
                    self.armed = False
                    del self.source[Key({deleted})]
                    self.source[Key(4)] = "new" * 9
                    gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            source = {{Key(1): "first" * 9, Key(2): "second" * 9, Key(3): "third" * 9}}
            anchor = Key(0)
            target = {{anchor: "anchor"}}
            anchor.source = source
            anchor.armed = True
            target.update(source)
            gc_collect()
            return str([(key.value, value) for key, value in target.items()]) + str([key.value for key in source])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_field_literals_allocate_declared_union_layouts_without_reordering(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.source: set[tuple[Key] | str] = set()
                self.pair: tuple[list[int | str]] = ([],)
            def __hash__(self) -> int:
                gc_collect()
                return self.number
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def receiver(key: Key, events: list[str]) -> Key:
            events.append('target')
            gc_collect()
            return key
        def item(key: Key, events: list[str]) -> Key:
            events.append('item')
            gc_collect()
            return key
        def number(events: list[str]) -> int:
            events.append('number')
            return 3
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            key = Key(1)
            receiver(key, events).source = {(item(key, events),)}
            key.source.add('tail')
            receiver(key, events).pair = ([number(events)],)
            key.pair[0].append('tail')
            gc_collect()
            return str((events, len(key.source), (key,) in key.source,
                        'tail' in key.source, key.pair))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation, initial, setup, value", [
    ("list[int | str]", "[]", "items = [3]", "items"),
    ("set[int | str]", "{0}", "items = {3}", "items"),
    ("dict[str, list[int | str]]", "{}", "items = [3]", "{'row': items}"),
    ("tuple[list[int | str]]", "([],)", "items = [3]", "(items,)"),
])
def test_contextual_field_literals_do_not_retype_aliased_container_storage(annotation, initial, setup, value):
    with pytest.raises(LLVMUnsupported, match="invariant|matching concrete|layout"):
        transpile_llvm(f'''
            class Holder:
                def __init__(self):
                    self.values: {annotation} = {initial}
            def main() -> int:
                holder = Holder()
                {setup}
                holder.values = {value}
                return len(holder.values)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_mutated_equal_keys_distinguish_cached_copy_from_cached_insertion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.fail = False
            def __hash__(self) -> int:
                if self.fail: raise ValueError('unexpected rehash')
                return 0
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            first, second = Key(1), Key(2)
            mapping = {first: 1, second: 2}
            members = {first, second}
            second.number = 1
            first.fail = True
            second.fail = True
            copied_mapping = mapping.copy()
            copied_set = set(members)
            from_mapping = set(mapping)
            frozen = frozenset(mapping)
            dict_keys = dict.fromkeys(mapping, 'default')
            set_keys = dict.fromkeys(members, 'default')
            empty: set[Key] = set()
            union = empty.union(mapping)
            exclusive = empty.symmetric_difference(mapping)
            empty.symmetric_difference_update(mapping)
            toggled = len(empty)
            empty.update(mapping)
            gc_collect()
            return str((len(copied_mapping), len(copied_set), len(from_mapping), len(frozen),
                        len(dict_keys), len(set_keys), len(union), len(exclusive), toggled,
                        len(empty), next(iter(from_mapping)) is first, next(iter(dict_keys)) is first))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_set_update_equality_failure_keeps_completed_insertions(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.fail = False
            def __hash__(self) -> int: return self.number % 2
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                if self.fail: raise ValueError('comparison failed')
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            key = Key(0)
            target = {key}
            source = {Key(1): 10, Key(2): 20}
            key.fail = True
            error = ''
            try:
                target.update(source)
            except ValueError as caught:
                error = str(caught)
            partial = len(target)
            key.fail = False
            gc_collect()
            target.update(source)
            return str((error, partial, len(target), Key(2) in target))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_set_union_operators_and_multioperand_updates(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.calls = 0
            def __hash__(self) -> int:
                self.calls += 1
                return self.number
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            a, b, c = Key(1), Key(2), Key(3)
            left, right = {a}, {b}
            merged = left | right
            alias = left
            left |= right
            frozen = frozenset(left).union(frozenset({c}))
            merged.update({a}, frozenset({b}), {c: 9})
            merged.update(merged)
            return str((len(left), len(merged), len(frozen), alias is left,
                        a.calls, b.calls, c.calls, c in frozen))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("source", ["mapping", "members"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_set_update_retains_key_when_equality_clears_source(tmp_path, source, optimize):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.active = False
                self.mapping: dict[Key, str] = {{}}
                self.members: set[Key] = set()
            def __hash__(self) -> int: return 0
            def __eq__(self, other: 'Key') -> bool:
                if self.active:
                    self.active = False
                    self.mapping.clear()
                    self.members.clear()
                    gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            key = Key(1)
            key.mapping = {{Key(2): 'two', Key(3): 'three'}}
            key.members = {{Key(2), Key(3)}}
            target = {{key}}
            key.active = True
            target.update(key.{source})
            gc_collect()
            return str((len(target), Key(2) in target, Key(3) in target,
                        len(key.mapping), len(key.members)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("source", ["keys", "set(keys)", "frozenset(keys)", "mapping", "mapping.keys()"])
@pytest.mark.parametrize("operation", ["update", "union"])
def test_custom_set_union_preserves_cached_source_hashes(tmp_path, source, operation):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.calls = 0
            def __hash__(self) -> int:
                self.calls += 1
                return 0
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            first, second = Key(1), Key(2)
            keys = [first, second, first]
            mapping = {{first: 'large value', second: 'not a bool'}}
            original = {{first}}
            {'result = original.union(' + source + ')' if operation == 'union' else 'original.update(' + source + '); result = original'}
            return str((len(original), len(result), first.calls, second.calls,
                        first in result, second in result))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("kind", ["int", "Key"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_set_union_skips_receiver_alias_after_earlier_operand_mutation(tmp_path, kind, optimize):
    summary = "sorted(value.number for value in result)" if kind == "Key" else "sorted(result)"
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int): self.number = number
            def __hash__(self) -> int: return self.number % 2
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def incoming(target: set[{kind}], peer: set[{kind}]) -> Iterator[{kind}]:
            target.add({kind}(99))
            peer.add({kind}(88))
            gc_collect()
            yield {kind}(2)
        def run(update: bool) -> str:
            original = {{{kind}(1)}}
            peer = {{{kind}(1)}}
            if update:
                original.update(incoming(original, peer), original, peer)
                result = original
            else:
                result = original.union(incoming(original, peer), original, peer)
            return str({summary})
        def main() -> str:
            gc_set_threshold(1)
            return run(False) + '|' + run(True)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.python.stdout == "[1, 2, 88]|[1, 2, 88, 99]"
    assert not result.native.stderr


def test_instance_fromkeys_evaluates_receiver_before_inputs(tmp_path):
    result = LLVM().assert_matches_python('''
        def receiver(events: list[str]) -> dict[str, str]:
            events.append('receiver')
            return {'old': 'ignored'}
        def keys(events: list[str]) -> list[str]:
            events.append('keys')
            return ['new']
        def default(events: list[str]) -> str:
            events.append('default')
            return 'value'
        def main() -> str:
            events: list[str] = []
            result = receiver(events).fromkeys(keys(events), default(events))
            return str((events, result))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_alias_skip_and_update_source_clear_during_equality(tmp_path, optimize):
    # Preserve the callback-driven case as well as the iterable mutation above:
    # the runtime must retain its current key when equality drops the source.
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.victim: set[Key] | None = None
                self.replace = False
            def __hash__(self) -> int: return self.value
            def __eq__(self, other: 'Key') -> bool:
                victim = self.victim
                self.victim = None
                if victim is not None:
                    victim.clear()
                    if self.replace: victim.add(Key(9))
                gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            trigger = Key(1)
            receiver = {trigger, Key(2)}
            incoming = {Key(1), Key(3)}
            trigger.victim = receiver
            trigger.replace = True
            result = receiver.union(incoming, receiver)
            gc_collect()
            before = sorted(key.value for key in receiver)
            trigger = Key(1)
            target = {trigger, Key(3)}
            source = {Key(1), Key(2)}
            trigger.victim = source
            target.update(source)
            gc_collect()
            return str((sorted(key.value for key in result), before,
                        sorted(key.value for key in target), len(source)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("source", ["keys", "set(keys)", "frozenset(keys)", "mapping", "mapping.keys()"])
def test_fromkeys_caches_mapping_hashes_but_rehashes_views_and_iterables(tmp_path, source):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int):
                self.number = number
                self.calls = 0
            def __hash__(self) -> int:
                self.calls += 1
                gc_collect()
                return self.number
        def main() -> str:
            gc_set_threshold(1)
            first, second = Key(1), Key(2)
            keys = [first, second, first]
            mapping = {{first: 1, second: 2}}
            result = dict.fromkeys({source}, 'shared' * 7)
            gc_collect()
            return str((len(result), list(result.values()), first.calls, second.calls))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("value", ["True", "42", "42.5", "'value' * 7", "maybe(True)"])
def test_cached_hash_update_preserves_each_value_storage_shape(tmp_path, value):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, number: int): self.number = number
            def __hash__(self) -> int: return 0
            def __eq__(self, other: 'Key') -> bool:
                gc_collect()
                return self.number == other.number
        def maybe(flag: bool) -> int | None:
            return 42 if flag else None
        def main() -> str:
            gc_set_threshold(1)
            source = {{Key(1): {value}}}
            target = {{Key(2): {value}}}
            target.update(source)
            return str(list(target.values()))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_set_constructors_copy_cached_hashes_without_callbacks(tmp_path):
    result = LLVM().assert_matches_python('''
        class Key:
            def __init__(self): self.calls = 0
            def __hash__(self) -> int:
                self.calls += 1
                return 1
        def main() -> str:
            key = Key()
            source = {key}
            copied = set(source)
            frozen = frozenset(source)
            thawed = set(frozen)
            return str((key.calls, len(copied), len(frozen), len(thawed), copied is source))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_key_updates_reuse_hashes_and_root_callback_snapshots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int, state: list[int]):
                self.value = value
                self.state = state
                self.source: dict[Key, str] = {}
            def __hash__(self) -> int:
                self.state[0] += 1
                return 0
            def __eq__(self, other: 'Key') -> bool:
                if self.state[1]:
                    self.state[1] = 0
                    self.source.clear()
                    gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            state = [0, 0]
            a, b, c = Key(1, state), Key(2, state), Key(3, state)
            source = {b: 'second' * 9, c: 'third' * 9}
            copied = dict(source)
            target = {a: 'first'}
            count = state[0]
            target.update(source)
            target.update(target)
            assert state[0] == count
            assert len(target) == 3 and len(copied) == 2
            a.source = {Key(4, state): 'retained' * 9}
            state[1] = 1
            error = ''
            try:
                target.update(a.source)
            except RuntimeError as caught:
                error = str(caught)
            gc_collect()
            return str((list(target.values()), len(a.source), error))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation", ["dict[Key, int]", "set[Key]", "frozenset[Key]", "dict[tuple[int, int], int]"])
def test_reference_key_host_inputs_require_initialized_native_hashes(tmp_path, annotation):
    with pytest.raises(LLVMUnsupported, match="native hash initialization"):
        LLVM().compile_library(f'''
            class Key:
                def __init__(self, value: int): self.value = value
                def __hash__(self) -> int: return self.value
            def main(values: {annotation}) -> str:
                return str(len(values))
        ''', tmp_path)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind", ["dict", "set", "frozenset"])
def test_builtin_union_key_host_inputs_initialize_value_hashes(tmp_path, optimize, kind):
    annotation = "dict[int | str, int]" if kind == "dict" else kind + "[int | str]"
    keys = [1, "1", -1, -2, "café"]
    value = dict.fromkeys(keys, 7) if kind == "dict" else set(keys) if kind == "set" else frozenset(keys)
    result = LLVM().assert_library_matches_python(f'''
        from pyjs.native import gc_collect
        def main(values: {annotation}) -> str:
            gc_collect()
            return str((len(values), 1 in values, "1" in values, -1 in values,
                        -2 in values, "café" in values, "missing" in values))
    ''', value, directory=tmp_path, entry_point="main", optimize=optimize)
    result.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_keys_use_value_hashing_and_safe_missing_key_repr(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            first = (1, 'a')
            values = {first: 10}
            assert values[(1, 'a')] == 10
            assert values.setdefault((1, 'a'), 99) == 10
            values[(2, 'b')] = 20
            copy = values.copy()
            gc_collect()
            assert copy.pop((1, 'a')) == 10 and len(values) == 2
            try:
                copy[(3, 'missing')]
            except KeyError as error:
                return str(error)
            return 'bad'
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", [
    "{Key(i, events): i for i in range(3)}",
    "{Key(i, events) for i in range(3)}",
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_comprehension_only_keys_retain_callbacks_without_later_lookup(tmp_path, expression, optimize):
    result = LLVM().assert_matches_python(f'''
        class Key:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events
            def __hash__(self) -> int:
                self.events.append(self.value)
                return self.value
        def main() -> str:
            events: list[int] = []
            values = {expression}
            return str((len(values), events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_custom_dictionary_key_hashes_and_value_equality():
    LLVM().assert_matches_python("""
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.hash_calls = 0
                self.equal_calls = 0

            def __hash__(self) -> int:
                self.hash_calls += 1
                return self.value % 2

            def __eq__(self, other: "Key") -> bool:
                self.equal_calls += 1
                return self.value == other.value

        def main() -> str:
            first = Key(1)
            second = Key(3)
            same = Key(1)
            values = {first: 10, second: 30}
            values[same] = 11
            result = (len(values), values[first], values[Key(3)],
                      values.get(Key(99), 7), Key(1) in values,
                      first.hash_calls, first.equal_calls,
                      second.hash_calls, same.hash_calls,
                      list(values)[0] is first)
            return str(result)
    """)


def test_custom_dictionary_mutations_preserve_cached_hashes():
    LLVM().assert_matches_python("""
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.calls = 0

            def __hash__(self) -> int:
                self.calls += 1
                return self.value

            def __eq__(self, other: "Key") -> bool:
                return self.value == other.value

            def __repr__(self) -> str:
                return "Key(" + str(self.value) + ")"

        def main() -> str:
            first = Key(1)
            values = {first: 10}
            original = values.setdefault(Key(1), 99)
            missing = Key(2)
            added = values.setdefault(missing, 20)
            recovered = values[first]
            removed = values.pop(Key(1))
            absent_default = values.pop(Key(3), 88)
            for index in range(3, 10):
                values[Key(index)] = index * 10
            del values[Key(5)]
            last = values.popitem()
            remaining = [(key.value, value) for key, value in values.items()]
            values.clear()
            values[Key(21)] = 210
            error = ""
            try:
                del values[Key(4)]
            except KeyError as caught:
                error = str(caught)
            return str((original, added, missing.calls, first.calls, recovered,
                        removed, absent_default, remaining, last[0].value,
                        last[1], len(values), values[Key(21)], error))
    """)


def test_dictionary_lookup_restarts_after_equality_mutates_storage():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.mapping: dict[Key, int] | None = None
                self.action = 0

            def __hash__(self) -> int:
                return 1

            def __eq__(self, other: "Key") -> bool:
                mapping = self.mapping
                action = self.action
                self.action = 0
                if mapping is not None:
                    if action == 1:
                        mapping.clear()
                    elif action == 2:
                        for index in range(10, 20):
                            mapping[Key(index)] = index * 10
                    elif action == 3:
                        del mapping[self]
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            first = Key(1)
            values = {first: 10}
            first.mapping = values
            first.action = 1
            cleared = values.get(Key(1), 99)
            values[first] = 10
            first.action = 2
            values[Key(2)] = 20
            grown = (len(values), values[Key(1)], values[Key(19)])
            first.action = 3
            deleted = values.get(Key(1), 77)
            return str((cleared, grown, deleted, len(values)))
    """)


def test_dictionary_copy_reuses_hashes_without_sharing_hash_storage():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail = False

            def __hash__(self) -> int:
                if self.fail:
                    raise ValueError("copy rehashed a key")
                return self.value

            def __eq__(self, other: "Key") -> bool:
                if self.fail:
                    raise ValueError("copy compared a key")
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            keys = [Key(index) for index in range(9)]
            values = {key: key.value * 10 for key in keys}
            for key in keys:
                key.fail = True
            copied = values.copy()
            gc_collect()
            for key in keys:
                key.fail = False
            values.pop(Key(3))
            copied.pop(Key(5))
            result = (len(values), len(copied), copied[Key(3)], values[Key(5)],
                      list(copied)[0] is keys[0])
            values.clear()
            empty = values.copy()
            empty[Key(12)] = 120
            gc_collect()
            return str((result, empty[Key(12)], copied[Key(8)]))
    """)


def test_dictionary_keys_dispatch_virtual_methods_and_normalize_hashes():
    LLVM().assert_matches_python("""
        class Key:
            def __init__(self, value: int):
                self.value = value

            def __hash__(self) -> int:
                return -2

            def __eq__(self, other: "Key") -> bool:
                return self.value == other.value

        class Special(Key):
            def __hash__(self) -> int:
                return -1

            def __eq__(self, other: Key) -> bool:
                return self.value % 10 == other.value % 10

        def main() -> str:
            first = Special(11)
            values: dict[Key, int] = {first: 10}
            values[Key(21)] = 20
            base_first: dict[Key, int] = {Key(1): 30}
            base_first[Special(11)] = 40
            return str((len(values), values[Key(31)],
                        list(values)[0] is first,
                        len(base_first), base_first[Special(21)]))
    """)


def test_dictionary_subclasses_cannot_silently_fall_back_to_identity():
    # The old implementation diagnosed this boundary. Runtime protocol
    # reachability now preserves subclass methods even when the base has none.
    LLVM().assert_matches_python("""
            class Key:
                def __init__(self, value: int):
                    self.value = value

            class Special(Key):
                def __hash__(self) -> int:
                    return self.value

                def __eq__(self, other: Key) -> bool:
                    return self.value == other.value

            def main() -> str:
                values: dict[Key, int] = {Special(1): 10}
                values[Special(1)] = 20
                return str((len(values), values.get(Special(1), 99),
                            values.get(Key(1), 99)))
    """, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_keys_check_selected_callback_arguments_and_recover(tmp_path, optimize):
    # Union callbacks reject only the selected incompatible arm. Noncolliding
    # mixed keys and later compatible comparisons remain valid.
    source = """
            class Key:
                def __init__(self, value: int):
                    self.value = value

                def __hash__(self) -> int:
                    return self.value

                def __eq__(self, other: "Key") -> bool:
                    return self.value == other.value

            def main() -> int:
                values: dict[Key | int, int] = {Key(1): 10, 2: 20}
                assert len(values) == 2
                assert values[Key(1)] == 10
                caught = False
                try:
                    values[1] = 30
                except TypeError as error:
                    assert str(error) == "__eq__ requires a compatible typed argument"
                    caught = True
                assert caught
                assert len(values) == 2 and values[Key(1)] == 10
                values[Key(1)] = 40
                assert values[Key(1)] == 40 and values[2] == 20
                return 0
    """
    oracle = source.replace('return self.value == other.value', '''if not isinstance(other, Key):
                        raise TypeError("__eq__ requires a compatible typed argument")
                    return self.value == other.value''')
    expected = run_python(dedent(oracle) + "\nassert main() == 0\n")
    actual = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert expected.returncode == actual.returncode == 0, (expected.stderr, actual.stderr)
    assert expected.stdout == actual.stdout == ""
    assert expected.stderr == actual.stderr == ""


def test_key_callback_cannot_collect_a_replaced_receiver_field():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.mapping: dict[Key, int] = {}
                self.replace = False

            def __hash__(self) -> int:
                if self.replace:
                    self.mapping = {}
                gc_collect()
                return 1

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def populate(key: Key) -> None:
            key.mapping[Key(1)] = 10

        def main() -> str:
            gc_set_threshold(1)
            key = Key(1)
            populate(key)
            key.replace = True
            found = key.mapping.get(key, 99)
            return str((found, len(key.mapping)))
    """)


def test_custom_set_keys_support_copy_removal_and_clearing():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.hash_calls = 0

            def __hash__(self) -> int:
                self.hash_calls += 1
                gc_collect()
                return 1

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

            def __repr__(self) -> str:
                return "Key(" + str(self.value) + ")"

        def main() -> str:
            gc_set_threshold(1)
            first = Key(1)
            members = set([first, Key(2), Key(1)])
            copied = members.copy()
            calls = first.hash_calls
            query = Key(2)
            members.remove(query)
            missing = Key(99)
            members.discard(missing)
            popped = members.pop()
            copied.clear()
            copied.add(Key(3))
            error = ""
            try:
                copied.remove(Key(7))
            except KeyError as caught:
                error = str(caught)
            return str((calls, query.hash_calls, missing.hash_calls,
                        popped is first, len(members), len(copied),
                        Key(3) in copied, error))
    """)


def test_empty_custom_key_containers_construct_without_hash_storage():
    LLVM().assert_matches_python("""
        class Key:
            def __hash__(self) -> int:
                raise ValueError("empty container hashed an item")

        def main() -> str:
            keys: list[Key] = []
            members = set(keys)
            values = dict.fromkeys(members, 7)
            copied = dict(values)
            frozen = frozenset(members)
            thawed = set(frozen)
            from_mapping = dict.fromkeys(copied, 9)
            from_view = dict.fromkeys(copied.keys(), 9)
            return str((len(values), len(copied), len(frozen), len(thawed),
                        len(from_mapping), len(from_view)))
    """)


@pytest.mark.parametrize("expression", [
    "dict.fromkeys([1])", "dict.fromkeys({'a': 1})", "dict.fromkeys(['a'], None)",
])
def test_none_only_fromkeys_values_have_concrete_storage(expression):
    LLVM().assert_matches_python(f"def main() -> str:\n    return repr({expression})\n")


def test_custom_dictionary_key_callbacks_collect_and_raise_safely():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_hash = False
                self.fail_equal = False

            def __hash__(self) -> int:
                gc_collect()
                if self.fail_hash:
                    raise ValueError("hash failed")
                return 1

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                if self.fail_equal:
                    raise ValueError("equality failed")
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            first = Key(1)
            values = {first: 10, Key(2): 20}
            query = Key(3)
            errors: list[str] = []
            query.fail_hash = True
            try:
                values[query] = 30
            except ValueError as caught:
                errors.append(str(caught))
            query.fail_hash = False
            first.fail_equal = True
            try:
                values.pop(query)
            except ValueError as caught:
                errors.append(str(caught))
            first.fail_equal = False
            values[query] = 30
            gc_collect()
            return str((errors, len(values), values[Key(1)],
                        values.pop(Key(3)), len(values)))
    """)
