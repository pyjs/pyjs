"""Fresh key slots widen without retyping inputs or their shared default."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import UNION_KEY_REPRESENTATION_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("numeric", ["int8", "int64"])
def test_conditional_empty_fromkeys_inherits_destination_before_join(tmp_path, optimize, numeric):
    result = LLVM().assert_matches_python(f'''
from pyjs import {numeric}
from pyjs.native import gc_collect
def build(flag: bool) -> dict[{numeric} | None, None]:
    return dict.fromkeys([]) if flag else dict.fromkeys([{numeric}(1)])
def main() -> str:
    rows: list[str] = []
    for flag in [True, False]:
        local: dict[{numeric} | None, None] = dict.fromkeys([{numeric}(1)]) if flag else dict.fromkeys(())
        absent: dict[{numeric} | None, None] = dict.fromkeys([None]) if flag else dict.fromkeys([{numeric}(1)])
        gc_collect()
        rows.append(repr((build(flag), local, absent)))
    return repr(rows)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("source", ["dict.fromkeys([int16(1)])", "named"])
def test_conditional_context_does_not_represent_existing_key_values(source):
    with pytest.raises(CompilationError, match="representation"):
        transpile_llvm(f'''
from pyjs import int8, int16
def build(flag: bool) -> dict[int8 | None, None]:
    named = dict.fromkeys([int16(1)])
    return dict.fromkeys([]) if flag else {source}
def main() -> int:
    return len(build(False))
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_keys_preserve_each_members_representation(tmp_path, optimize):
    result = LLVM().assert_matches_python(UNION_KEY_REPRESENTATION_CONTRACT.source,
        directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, UNION_KEY_REPRESENTATION_CONTRACT.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_fromkeys_converts_scalar_sources_and_keeps_default_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from math import isnan
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
def check(values: dict[int8 | None, list[str]], shared: list[str]) -> str:
    assert values[int8(127)] is shared
    values[None] = ["none"]
    gc_collect()
    return repr(values)
def main() -> str:
    gc_set_threshold(1)
    items = [int8(0), int8(127)]
    mapping = {item: "present" for item in items}
    shared = ["shared"]
    rows = [check(dict.fromkeys(items, shared), shared),
            check(dict.fromkeys(mapping, shared), shared),
            check(dict.fromkeys(set(items), shared), shared),
            check(dict.fromkeys(frozenset(items), shared), shared),
            check(dict.fromkeys(iter(items), shared), shared),
            check(dict.fromkeys((item for item in items), shared), shared),
            check(dict.fromkeys((int8(0), int8(127)), shared), shared),
            check(dict.fromkeys(mapping.keys(), shared), shared)]
    named: dict[int8 | None, list[str]] = dict.fromkeys(mapping, shared)
    mapping.clear()
    items.clear()
    shared.append("updated")
    gc_collect()
    assert named[int8(127)] is shared
    numbers: dict[int | str | None, str] = dict.fromkeys(range(3), "number")
    numbers["key"] = "string"
    numbers[None] = "absent"
    special = {float("nan"): 1, float("nan"): 2, -0.0: 3, float("inf"): 4}
    copied: dict[float | None, str] = dict.fromkeys(special, "x")
    special.clear()
    gc_collect()
    nan_count = 0
    for key in copied:
        if key is not None and isnan(key):
            nan_count += 1
    assert len(copied) == 4 and nan_count == 2
    assert copied[0.0] == "x" and copied[float("inf")] == "x"
    return repr((rows, named, numbers, copied))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_missing_key_arms_inherit_context_without_changing_defaults(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.native import gc_collect
def build() -> dict[int8 | None, int8 | None]:
    return dict.fromkeys([None])
def use(values: dict[int8 | None, int8 | None]) -> str:
    values[int8(127)] = int8(127)
    value = values[int8(127)]
    assert value is not None
    gc_collect()
    return repr((values, value + 1))
def main() -> str:
    empty: dict[int8 | None, int8 | None] = dict.fromkeys([])
    rows = [use(empty), use(build()), use(dict.fromkeys([None])),
            use(dict.fromkeys([])), use(dict.fromkeys(())), use(dict.fromkeys({}))]
    ordinary: dict[int | None, int] = dict.fromkeys([1], 2)
    ordinary[None] = 3
    return repr((rows, ordinary))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_fromkeys_acquires_iterator_after_default_and_recovers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
class Keys:
    def __init__(self, events: list[str], fail: bool):
        self.events = events
        self.fail = fail
    def __iter__(self) -> Iterator[int]:
        self.events.append("iter")
        gc_collect()
        if self.fail:
            raise ValueError("iteration")
        return iter([0, 2])
def default(events: list[str], fail: bool) -> list[str]:
    events.append("default")
    gc_collect()
    if fail:
        raise ValueError("default")
    return ["value"]
def main() -> str:
    gc_set_threshold(1)
    rows: list[str] = []
    for mode in range(4):
        events: list[str] = []
        result: dict[int | None, list[str]] = {None: ["retained"]}
        alias = result
        try:
            result = dict.fromkeys(Keys(events, mode >= 2), default(events, mode % 2 == 1))
        except ValueError as error:
            rows.append(str(error))
            assert result is alias
        rows.append(repr((events, result)))
        result = dict.fromkeys(Keys(events, False), default(events, False))
        assert result[0] is result[2]
        result[0].append("mutated")
        gc_collect()
        rows.append(repr(result))
    return repr(rows)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["arena", "gc"])
def test_fromkeys_converted_allocation_failure_preserves_sources(tmp_path, optimize, managed):
    source = '''
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining
def main() -> int:
    keys = {i: "present" for i in range(6)}
    shared = ["default"]
    stages = 1
    failure = 0
    while failure <= stages:
        result: dict[int | None, list[str]] = {None: shared}
        alias = result
        caught = False
        arm(1000 if failure == 0 else failure)
        try:
            result = dict.fromkeys(keys, shared)
        except MemoryError:
            caught = True
        if failure == 0:
            stages = 1000 - remaining()
        arm(0)
        gc_collect()
        assert stages >= 3 and caught == (failure != 0)
        assert not caught or result is alias
        assert len(keys) == 6 and shared == ["default"]
        result = dict.fromkeys(keys, shared)
        gc_collect()
        assert len(result) == 6 and None not in result
        for key in range(6):
            assert result[key] is shared
        failure += 1
    return 0
'''.replace("gc_collect()", "gc_collect()" if managed else "pass")
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("expression", ["values[int16(1)]", "int16(1) in values"])
def test_union_keys_reject_conflicting_member_representations(expression):
    with pytest.raises(CompilationError, match="representation"):
        transpile_llvm(f'''
from pyjs import int8, int16
def main() -> int:
    values: dict[int8 | None, int] = {{int8(1): 2}}
    return int({expression})
''')


@pytest.mark.parametrize("optional, message", [
    (False, "cached callback keys require matching layouts"),
    # Optional application-key storage has an earlier capability boundary.
    (True, "dictionary keys currently require bool, int, float, str, bytes, None"),
])
def test_fromkeys_does_not_rehash_widened_callback_storage(optional, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
class Key:
    def __hash__(self) -> int:
        return 0
def main() -> int:
    keys: dict[Key{' | None' if optional else ''}, int] = {{Key(): 1}}
    values: dict[Key | str{' | None' if optional else ''}, int] = dict.fromkeys(keys, 2)
    return len(values)
''')


@pytest.mark.parametrize("key_type, source", [("int | None", "[True]"),
                                             ("float | None", "[1]"),
                                             ("object", "[int8(1)]")])
def test_fromkeys_keys_require_explicit_numeric_conversion(key_type, source):
    with pytest.raises((CompilationError, LLVMUnsupported), match="explicit.*conversion"):
        transpile_llvm(f'''
from pyjs import int8
def main() -> int:
    values: dict[{key_type}, int] = dict.fromkeys({source}, 2)
    return len(values)
''')
