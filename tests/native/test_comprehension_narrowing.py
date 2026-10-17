import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_filters_narrow_later_conditions_sources_and_results(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import int8
from pyjs.native import gc_collect, gc_set_threshold
class Row:
    def __init__(self, label: str | None):
        self.label = label
def accept(value: int8, events: list[int8]) -> bool:
    events.append(value)
    gc_collect()
    return value != 0
def main() -> str:
    gc_set_threshold(1)
    value = "outer"
    values: list[int8 | None] = [None, int8(127), int8(0), int8(-128)]
    events: list[int8] = []
    selected = [value + 1 for value in values if value is not None if accept(value, events)]
    unique = {value + 1 for value in values if not (value is None)}
    mapped = {value: value + 1 for value in values if value is not None}
    lazy = (value + 1 for value in values if value is not None if accept(value, events))
    before = repr(events)
    captured = list(lazy)
    mapping: dict[int8 | None, str] = {None: "none", int8(127): "value"}
    keys = sorted(key for key in mapping if key is not None)
    rows: list[list[int8] | None] = [None, [int8(127), int8(0)], [int8(-128)]]
    nested = [value + 1 for row in rows if row is not None for value in row]
    shadowed = [value for value in values if value is not None for value in [None, value]]
    objects = [Row(None), Row("ready"), Row("")]
    labels = [row.label.upper() for row in objects if row.label is not None if row.label]
    rebound = [row.label.upper() for row in objects if row.label is not None
               for row in [Row(None), Row(row.label)] if row.label is not None]
    gc_collect()
    return repr((value, selected, sorted(unique), mapped, before, captured,
                 events, keys, nested, shadowed, labels, rebound))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
