import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("cursor", ['map(collect, ["a", "b", "c"])',
                                     '(collect(value) for value in ["a", "b", "c"])'])
@pytest.mark.parametrize("expression, expected", [
    ("list(cursor)", '["a!", "b!", "c!"]'),
    ("tuple(cursor)", '("a!", "b!", "c!")'),
    ("set(cursor)", '{"a!", "b!", "c!"}'),
    ("dict(map(lambda value: (value, value + value), cursor))", '{"a!": "a!a!", "b!": "b!b!", "c!": "c!c!"}'),
    ("sorted(cursor)", '["a!", "b!", "c!"]'),
    ('"|".join(cursor)', '"a!|b!|c!"'),
    ('{"a!", "keep"}.union(cursor)', '{"a!", "b!", "c!", "keep"}'),
    ('{"a!", "keep"}.intersection(cursor)', '{"a!"}'),
    ('{"a!", "keep"}.difference(cursor)', '{"keep"}'),
    ('{"a!", "keep"}.symmetric_difference(cursor)', '{"b!", "c!", "keep"}'),
    ('{"a!", "b!", "c!"}.intersection(cursor, map(collect, ["b", "c"]))', '{"b!", "c!"}'),
    ("bytes(map(lambda value: len(collect(value)) + 63, [\"a\", \"b\"]))", 'b"AA"'),
])
def test_consumers_root_partial_results_across_callback_collection(expression, expected, optimize, monkeypatch, cursor):
    # Sanitizers expose dangling buffers even when the allocator has not yet
    # reused their contents. Avoid a slow external symbolizer on failure.
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def collect(value: str) -> str:
            gc_collect()
            return value + "!"

        def main() -> int:
            gc_set_threshold(1)
            cursor = {cursor}
            result = {expression}
            gc_collect()
            assert result == {expected}
            return 0
    ''', optimize=optimize, sanitizers=("address",))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("method", [
    "union", "update", "difference", "difference_update", "intersection", "intersection_update",
    "symmetric_difference", "symmetric_difference_update", "issubset", "issuperset", "isdisjoint",
])
def test_set_callbacks_observe_receiver_mutations_and_preserve_aliases(method, optimize):
    outcome = ('str(result)' if method in {"issubset", "issuperset", "isdisjoint"} else
               "''.join(map(lambda n: str(n), sorted(result)))")
    statement = f"result = values.{method}(cursor)"
    if method.endswith("update"):
        statement = f"values.{method}(cursor)\n            result = alias"
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        def change(values: set[int], events: list[int], value: int) -> int:
            events.append(value)
            if value == 2:
                values.clear()
                values.add(2)
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            values = {{1, 2, 3}}
            alias = values
            events: list[int] = []
            cursor = map(lambda n: change(values, events, n), [1, 2, 3])
            {statement}
            result_text = {outcome}
            gc_collect()
            return result_text + ":" + ''.join(map(lambda n: str(n), events))
    ''', optimize=optimize)
