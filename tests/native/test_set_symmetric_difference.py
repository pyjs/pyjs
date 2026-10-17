import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_symmetric_difference_reuses_hashes_keeps_keys_and_clears_aliases(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
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
            incoming = Key(3)
            receiver = {kept, Key(2)}
            source = {Key(2), incoming}
            for group in (receiver, source):
                for key in group:
                    key.fail_hash = True
            result = receiver ^ source
            same = receiver ^ receiver
            frozen = frozenset(receiver).symmetric_difference(source)
            alias = receiver
            receiver ^= source
            identities = (any(key is kept for key in result),
                          any(key is incoming for key in result))
            before = sorted(key.value for key in receiver)
            receiver.symmetric_difference_update(receiver)
            source ^= source
            gc_collect()
            return str((sorted(key.value for key in result),
                        sorted(key.value for key in frozen), identities,
                        before, receiver is alias, len(receiver), len(source), len(same)))
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_symmetric_difference_probes_again_before_adding_and_uses_argument_first():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, label: str, events: list[str]):
                self.value = value
                self.label = label
                self.events = events

            def __hash__(self) -> int:
                return 0

            def __eq__(self, other: "Key") -> bool:
                self.events.append(self.label)
                gc_collect()
                return self.value == other.value

        def run(update: bool) -> str:
            events: list[str] = []
            receiver = {Key(1, "receiver", events)}
            source = {Key(2, "argument", events)}
            if update:
                receiver.symmetric_difference_update(source)
            else:
                result = receiver ^ source
                if len(result) != 2:
                    return "wrong result"
            return str(events)

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    """)


def test_symmetric_difference_keeps_partial_updates_on_key_comparison_failure():
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

        def run(mode: int) -> str:
            receiver_key = Key(2)
            source_key = Key(2)
            receiver = {Key(1), receiver_key, Key(3)}
            source = {Key(1), source_key, Key(4)}
            receiver_key.fail = True
            source_key.fail = True
            error = ""
            result: set[Key] = set()
            try:
                if mode == 0:
                    result = receiver ^ source
                elif mode == 1:
                    receiver ^= source
                else:
                    receiver.symmetric_difference_update(source)
            except ValueError as caught:
                error = str(caught)
            before = sorted(key.value for key in receiver)
            receiver_key.fail = False
            source_key.fail = False
            gc_collect()
            receiver.symmetric_difference_update(source)
            return str((error, before, len(result),
                        sorted(key.value for key in receiver)))

        def main() -> str:
            gc_set_threshold(1)
            return "|".join(run(mode) for mode in range(3))
    """)


def test_symmetric_difference_materializes_iterables_before_toggling_receiver():
    LLVM().assert_matches_python("""
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def incoming(receiver: set[int], fail: bool) -> Iterator[int]:
            receiver.clear()
            receiver.add(3)
            gc_collect()
            yield 2
            yield 2
            if fail:
                raise ValueError("iterator failed")

        def run(update: bool, fail: bool) -> str:
            receiver = {1}
            result: set[int] = set()
            error = ""
            try:
                if update:
                    receiver.symmetric_difference_update(incoming(receiver, fail))
                else:
                    result = receiver.symmetric_difference(incoming(receiver, fail))
            except ValueError as caught:
                error = str(caught)
            gc_collect()
            return str((error, sorted(receiver), sorted(result)))

        def main() -> str:
            gc_set_threshold(1)
            return "|".join((run(False, False), run(True, False),
                             run(False, True), run(True, True)))
    """)


def test_symmetric_difference_dictionary_inputs_keep_hashes_but_key_views_rehash():
    LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_hash = False

            def __hash__(self) -> int:
                if self.fail_hash:
                    raise ValueError("key view hashing")
                return self.value

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return self.value == other.value

        def run(mode: int) -> str:
            key = Key(2)
            source = {key: "unused"}
            key.fail_hash = True
            receiver = {Key(1), Key(2)}
            result: set[Key] = set()
            error = ""
            try:
                if mode == 0:
                    result = receiver.symmetric_difference(source)
                elif mode == 1:
                    receiver.symmetric_difference_update(source)
                else:
                    receiver.symmetric_difference_update(source.keys())
            except ValueError as caught:
                error = str(caught)
            gc_collect()
            return str((error, sorted(key.value for key in receiver),
                        sorted(key.value for key in result)))

        def main() -> str:
            gc_set_threshold(1)
            return "|".join(run(mode) for mode in range(3))
    """)


@pytest.mark.parametrize("optimize", [0, 2])
def test_symmetric_difference_retains_consumed_key_when_insertion_clears_source(tmp_path, optimize):
    result = LLVM().assert_matches_python("""
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, source: set["Key"]):
                self.value = value
                self.source = source
                self.comparisons = 0

            def __hash__(self) -> int:
                return 0

            def __eq__(self, other: "Key") -> bool:
                self.comparisons += 1
                if self.comparisons == 2:
                    self.source.clear()
                gc_collect()
                return self.value == other.value

        def run(named: bool) -> str:
            source = {Key(2, set())}
            stored = Key(1, source)
            receiver = {stored}
            if named:
                receiver.symmetric_difference_update(source)
            else:
                receiver ^= source
            gc_collect()
            return str((sorted(key.value for key in receiver),
                        len(source), stored.comparisons))

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    """, directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
