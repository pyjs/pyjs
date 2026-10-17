"""Allocation scenarios must fail the allocator they claim to exercise."""

import pytest

from tests.native.allocation_support import _fail_allocations


@pytest.mark.parametrize("only", [(), ("realoc",)])
def test_allocation_selection_rejects_empty_or_unknown_names(only):
    with pytest.raises(ValueError, match="known allocator"):
        _fail_allocations("", False, only=only)


def test_allocation_selection_keeps_other_calls_unmodified():
    source = "%a = call ptr @realloc(ptr null, i64 8)\n%b = call ptr @pyjs.arena.try.alloc(ptr %arena, i64 8, i64 8)"
    selected = _fail_allocations(source, False, only=("realloc",))
    # Inspect only the authored call sites, not the generated wrapper bodies.
    assert selected.splitlines()[:2] == [
        "%a = call ptr @test.realloc(ptr null, i64 8)",
        "%b = call ptr @pyjs.arena.try.alloc(ptr %arena, i64 8, i64 8)",
    ]
    default = _fail_allocations(source, False)
    assert default.splitlines()[:2] == [
        "%a = call ptr @test.realloc(ptr null, i64 8)",
        "%b = call ptr @test.pyjs.arena.try.alloc(ptr %arena, i64 8, i64 8)",
    ]
