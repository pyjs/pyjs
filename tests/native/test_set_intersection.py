import pytest

from pyjs.tooling.llvm import LLVM


def test_primitive_intersection_preserves_the_selected_signed_zero():
    LLVM().assert_matches_python('''
        def main() -> str:
            small, large, equal = {-0.0}, {0.0, 2.0}, {0.0}
            return str((next(iter(small & large)), next(iter(large & small)),
                        next(iter(small & equal)),
                        next(iter(frozenset(small).intersection(large)))))
    ''', sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_intersection_stops_early_and_preserves_incoming_keys(optimize):
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
                if self.hashes > 1:
                    raise ValueError("unexpected rehash")
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def values(items: list[Key]) -> Iterator[Key]:
            for item in items:
                yield item
            raise ValueError("tail consumed")

        def main() -> str:
            gc_set_threshold(1)
            receiver = {Key(1), Key(2)}
            first = Key(1)
            second = Key(2)
            tail = Key(3)
            iterator = values([first, second, tail])
            result = receiver.intersection(iterator)
            following = next(iterator).value
            gc_collect()
            return str((sorted(key.value for key in result),
                        any(key is first for key in result),
                        any(key is second for key in result), following,
                        first.hashes, second.hashes, tail.hashes))
    """, optimize=optimize, sanitizers=("address", "undefined"))


def test_intersection_update_is_atomic_on_iterator_failure_and_keeps_hashes():
    LLVM().assert_matches_python("""
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value

            def __hash__(self) -> int:
                gc_collect()
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def failing() -> Iterator[Key]:
            yield Key(1)
            raise ValueError("interrupted")

        def main() -> str:
            gc_set_threshold(1)
            receiver = {Key(1), Key(2)}
            alias = receiver
            error = ""
            try:
                receiver.intersection_update(failing())
            except ValueError as caught:
                error = str(caught)
            before = sorted(key.value for key in receiver)
            receiver.intersection_update([Key(2)])
            gc_collect()
            contains = Key(2) in receiver
            receiver.add(Key(3))
            return str((error, before, receiver is alias, contains,
                        sorted(key.value for key in receiver)))
    """)


def test_iterable_intersection_counts_distinct_matches_and_consumes_empty_input():
    LLVM().assert_matches_python("""
        from collections.abc import Iterator

        def values(seen: list[int]) -> Iterator[int]:
            for item in (1, 1, 2, 9):
                seen.append(item)
                yield item

        def run(mode: int) -> str:
            receiver = set[int]() if mode == 0 else {1, 2}
            seen: list[int] = []
            iterator = values(seen)
            result = receiver.intersection(iterator)
            following = next(iterator, -1)
            return str((sorted(result), seen, following, sorted(receiver)))

        def main() -> str:
            seen: list[int] = []
            frozen = frozenset({1, 2})
            iterator = values(seen)
            result = frozen.intersection(iterator)
            following = next(iterator)
            return str((run(0), run(1), sorted(result), seen, following,
                        hash(result) == hash(frozen)))
    """)


def test_intersection_update_does_not_publish_matches_when_key_callbacks_fail():
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
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                if self.fail_equal:
                    raise ValueError("equality failed")
                return self.value == other.value

        def run(fail_hash: bool) -> str:
            stored = Key(2)
            receiver = {Key(1), stored, Key(3)}
            alias = receiver
            incoming = Key(2)
            incoming.fail_hash = fail_hash
            stored.fail_equal = not fail_hash
            error = ""
            try:
                receiver.intersection_update([Key(1), incoming])
            except ValueError as caught:
                error = str(caught)
            before = sorted(key.value for key in receiver)
            incoming.fail_hash = False
            stored.fail_equal = False
            gc_collect()
            receiver.intersection_update([incoming])
            receiver.add(Key(4))
            return str((error, before, receiver is alias,
                        any(key is incoming for key in receiver),
                        sorted(key.value for key in receiver)))

        def main() -> str:
            gc_set_threshold(1)
            return run(True) + "|" + run(False)
    """)


def test_concrete_intersection_reuses_hashes_and_retains_the_smaller_operand_keys():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_hash = False

            def __hash__(self) -> int:
                if self.fail_hash:
                    raise ValueError("unexpected rehash")
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            first = Key(1)
            second = Key(1)
            third = Key(1)
            small = {first}
            large = {second, Key(2)}
            equal = {third}
            frozen = frozenset(large)
            for group in (small, large, equal):
                for key in group:
                    key.fail_hash = True
            results = [next(iter(small & large)) is first,
                       next(iter(large & small)) is first,
                       next(iter(small & equal)) is third,
                       next(iter(small.intersection(frozen))) is first,
                       next(iter(frozen.intersection(small))) is first]
            alias = large
            large &= small
            results.extend([large is alias, next(iter(large)) is first])
            large.intersection_update(equal)
            results.extend([large is alias, next(iter(large)) is third])
            gc_collect()
            return str((results, len(large), len(small), len(frozen)))
    """)


def test_concrete_intersection_alias_copies_without_invoking_colliding_keys():
    LLVM().assert_matches_python("""
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail = False

            def __hash__(self) -> int:
                if self.fail:
                    raise ValueError("unexpected hash")
                return 1

            def __eq__(self, other: "Key") -> bool:
                if self.fail:
                    raise ValueError("unexpected equality")
                return self.value == other.value

        def main() -> str:
            receiver = {Key(1), Key(2)}
            alias = receiver
            for key in receiver:
                key.fail = True
            result = receiver & receiver
            named = receiver.intersection(receiver)
            receiver &= receiver
            receiver.intersection_update(receiver)
            return str((sorted(key.value for key in result),
                        sorted(key.value for key in named),
                        result is receiver, named is receiver,
                        alias is receiver, len(receiver)))
    """)


def test_concrete_intersection_roots_a_key_when_comparison_clears_its_source():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.source: set[Key] | None = None
                self.cycle = self

            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: "Key") -> bool:
                source = self.source
                if source is not None:
                    source.clear()
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            source = {Key(1), Key(2)}
            trigger = Key(1)
            target = {trigger, Key(2), Key(3)}
            trigger.source = source
            result = source & target
            gc_collect()
            return str((sorted(key.value for key in result), len(source)))
    """)


def test_concrete_intersection_preserves_subclass_comparison_priority():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events

            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: "Key") -> bool:
                self.events.append("base")
                gc_collect()
                return self.value == other.value

        class Child(Key):
            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: Key) -> bool:
                self.events.append("child")
                gc_collect()
                return self.value == other.value

        def run(larger_child: bool) -> str:
            events: list[str] = []
            base = Key(1, events)
            child = Child(1, events)
            left = {base}
            right = {child}
            if larger_child:
                right.add(Child(2, events))
            else:
                left.add(Key(2, events))
            forward = left & right
            named = left.intersection(right)
            return str((events, next(iter(forward)) is base,
                        next(iter(named)) is child))

        def main() -> str:
            gc_set_threshold(1)
            return run(True) + "|" + run(False)
    """)


def test_concrete_intersection_update_keeps_original_contents_on_key_failure():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_equal = False

            def __hash__(self) -> int:
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                if self.fail_equal:
                    raise ValueError("comparison failed")
                return self.value == other.value

        def run(named: bool) -> str:
            failing = Key(2)
            receiver = {Key(1), failing, Key(3)}
            incoming = {Key(1), Key(2)}
            alias = receiver
            failing.fail_equal = True
            error = ""
            try:
                if named:
                    receiver.intersection_update(incoming)
                else:
                    receiver &= incoming
            except ValueError as caught:
                error = str(caught)
            before = sorted(key.value for key in receiver)
            failing.fail_equal = False
            gc_collect()
            receiver &= incoming
            receiver.add(Key(4))
            return str((error, before, receiver is alias,
                        sorted(key.value for key in receiver)))

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    """)


def test_concrete_intersection_preserves_scalar_payloads_and_signed_zero_keys():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            receiver: set[int | str] = {1, "label" + str(7)}
            incoming: set[int | str] = {1, "label7", "tail"}
            result = receiver & incoming
            frozen = frozenset(incoming).intersection(receiver)
            gc_collect()
            small = {-0.0}
            large = {0.0, 2.0}
            equal = {0.0}
            return str((result == receiver, len(frozen),
                        "label7" in result, 1 in result,
                        next(iter(small & large)),
                        next(iter(large & small)),
                        next(iter(small & equal))))
    """)
