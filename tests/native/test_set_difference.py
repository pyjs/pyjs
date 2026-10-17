import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("operation", ["left - right", "left ^ right", "left | right", "left & right",
                                         "left == right", "left.update(list(right))", "left.add(needle)"])
def test_cached_key_reuse_rejects_incompatible_nested_storage(operation):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage|identical set item types"):
        transpile_llvm(f'''
            def main() -> int:
                left = {{(1,)}}
                needle = (True,)
                right = {{needle}}
                {operation}
                return len(left)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_set_algebra_reuses_subclass_operand_hashes_and_reflected_equality(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events
                self.fail = False
            def __hash__(self) -> int:
                if self.fail: raise ValueError('hash repeated')
                return self.value
            def __eq__(self, other: 'Key') -> bool:
                self.events.append('base')
                gc_collect()
                return self.value == other.value

        class Child(Key):
            def __hash__(self) -> int:
                if self.fail: raise ValueError('hash repeated')
                return self.value
            def __eq__(self, other: Key) -> bool:
                self.events.append('child')
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            left = {Key(1, events), Key(2, events)}
            child = Child(2, events)
            right = {child}
            child.fail = True
            difference = left - right
            exclusive = left ^ right
            combined = left | right
            left -= right
            left ^= right
            gc_collect()
            return str((sorted(key.value for key in difference),
                        sorted(key.value for key in exclusive), len(combined),
                        sorted(key.value for key in left), events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_custom_set_difference_reuses_hashes_preserves_keys_and_clears_aliases():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_hash = False

            def __hash__(self) -> int:
                if self.fail_hash:
                    raise ValueError("unexpected hashing")
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            kept = Key(1)
            receiver = {kept, Key(2), Key(3)}
            other = {Key(2)}
            frozen = frozenset(receiver)
            for group in (receiver, other):
                for key in group:
                    key.fail_hash = True
            result = receiver - other
            named = frozen.difference(other)
            same = receiver - receiver
            alias = receiver
            receiver -= other
            retained = any(key is kept for key in receiver)
            receiver.difference_update(receiver)
            gc_collect()
            return str((sorted(key.value for key in result),
                        sorted(key.value for key in named), len(same),
                        retained, receiver is alias, len(receiver)))
    """)


def test_difference_streams_removals_and_still_hashes_items_after_becoming_empty():
    LLVM().assert_matches_python("""
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.hashes = 0

            def __hash__(self) -> int:
                self.hashes += 1
                gc_collect()
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def values(key: Key) -> Iterator[Key]:
            yield key
            yield key
            raise ValueError("tail failed")

        def run(update: bool) -> str:
            receiver = {Key(1), Key(2)}
            incoming = Key(2)
            result: set[Key] = set()
            error = ""
            try:
                if update:
                    receiver.difference_update([Key(1)], values(incoming))
                else:
                    result = receiver.difference([Key(1)], values(incoming))
            except ValueError as caught:
                error = str(caught)
            gc_collect()
            return str((error, sorted(key.value for key in receiver),
                        len(result), incoming.hashes))

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    """)


def test_difference_update_keeps_removals_before_comparison_failure():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail = False

            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                if self.fail:
                    raise ValueError("comparison failed")
                return self.value == other.value

        def run(named: bool) -> str:
            failing = Key(2)
            receiver = {Key(1), failing, Key(3)}
            source = {Key(1), Key(2)}
            alias = receiver
            failing.fail = True
            error = ""
            try:
                if named:
                    receiver.difference_update(source)
                else:
                    receiver -= source
            except ValueError as caught:
                error = str(caught)
            before = sorted(key.value for key in receiver)
            failing.fail = False
            gc_collect()
            receiver.difference_update(source)
            return str((error, before, receiver is alias,
                        sorted(key.value for key in receiver)))

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    """)


def test_difference_selects_python_traversal_direction_for_skewed_set_sizes():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, label: str, events: list[str]):
                self.value = value
                self.label = label
                self.events = events

            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: "Key") -> bool:
                self.events.append(self.label)
                gc_collect()
                return self.value == other.value

        def run(left_size: int, right_size: int, update: bool) -> str:
            events: list[str] = []
            left = {Key(value, "left", events) for value in range(left_size)}
            right = {Key(value, "right", events) for value in range(right_size)}
            if update:
                left.difference_update(right)
                return str((events, len(left)))
            result = left - right
            return str((events, len(result)))

        def main() -> str:
            gc_set_threshold(1)
            return "|".join((run(1, 8, True), run(1, 17, True),
                             run(1, 17, False), run(17, 1, False)))
    """)


def test_difference_dictionary_hashing_depends_on_method_and_first_operand_size():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_hash = False

            def __hash__(self) -> int:
                if self.fail_hash:
                    raise ValueError("hashing dictionary input")
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def run(mode: int) -> str:
            source_key = Key(0)
            source = {source_key: "value"}
            source_key.fail_hash = True
            receiver = {Key(value) for value in range(10 if mode == 1 else 1)}
            result: set[Key] = set()
            error = ""
            try:
                if mode == 2:
                    receiver.difference_update(source)
                elif mode == 3:
                    result = receiver.difference(source.keys())
                else:
                    result = receiver.difference(source)
            except ValueError as caught:
                error = str(caught)
            gc_collect()
            return str((error, len(receiver), len(result)))

        def main() -> str:
            gc_set_threshold(1)
            return "|".join(run(mode) for mode in range(4))
    """)


@pytest.mark.parametrize("optimize", [0, 2])
def test_difference_update_prefilter_failure_does_not_publish_removals(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail = False

            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                if self.fail:
                    raise ValueError("prefilter failed")
                return self.value == other.value

        def run(named: bool) -> str:
            receiver = {Key(0), Key(1)}
            failing = Key(1)
            source = {Key(value) for value in range(40) if value != 1}
            source.add(failing)
            failing.fail = True
            error = ""
            try:
                if named:
                    receiver.difference_update(source)
                else:
                    receiver -= source
            except ValueError as caught:
                error = str(caught)
            before = sorted(key.value for key in receiver)
            failing.fail = False
            gc_collect()
            receiver.difference_update(source)
            return str((error, before, len(receiver)))

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
