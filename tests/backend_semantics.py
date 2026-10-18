"""Named semantic contracts shared by every general-purpose backend."""

import struct
from dataclasses import dataclass
from textwrap import dedent, indent

UNPACK_TARGET_SOURCE = dedent('''
    from pyjs import js

    @js
    class Panel:
        def __init__(self):
            self.left = -1
            self.right = -1

    @js
    def owner(panel: Panel, values: list[int], events: list[int], fail: bool) -> Panel:
        events.append(len(events) + 1)
        values[-1] = 99
        if fail and len(events) == 2:
            raise ValueError("target failed")
        return panel

    @js
    def run() -> str:
        result: list[str] = []
        for size in [1, 2, 3]:
            for fail in [False, True]:
                values = list(range(size))
                events: list[int] = []
                panel = Panel()
                error_message = "ok"
                try:
                    owner(panel, values, events, fail).left, owner(panel, values, events, fail).right = values
                except ValueError as error:
                    error_message = str(error)
                result.append(str((panel.left, panel.right, events, error_message)))
        nested = [2]
        events: list[int] = []
        panel = Panel()
        owner(panel, nested, events, False).left, (panel.right,) = (1, nested)
        result.append(str((panel.left, panel.right, events)))
        fresh, panel.left = (3, 4)
        result.append(str((fresh, panel.left)))
        for size in [0, 1, 2]:
            nested = list(range(size))
            panel = Panel()
            try:
                panel.left, (panel.right,) = (7, nested)
            except ValueError:
                result.append(str((panel.left, panel.right)))
            else:
                result.append(str((panel.left, panel.right)))
        values = [1, 2, 3, 4]
        events = []
        owner(panel, values, events, False).left, *middle, panel.right = values
        result.append(str((panel.left, middle, panel.right, events)))
        return "|".join(result)

    def main() -> str:
        return run()
''')

CLIENT_IMPLEMENTATIONS_SOURCE = '''
from functools import partial
from pyjs import js

@js
def plain() -> int:
    return 17

@plain.client
def plain() -> int:
    return 29

@js
def add_one(value: int) -> int:
    return value + 1

@js
def selected_partial() -> int:
    return 37

selected_partial.client(partial(add_one, 40))

@js
class Choice:
    @js
    def read(self) -> int:
        return 53

    @read.client
    def read(self) -> int:
        return 67

@js
def main() -> int:
    return plain() + selected_partial() + Choice().read()
'''

POSTPONED_DATACLASS_CONTRACT = '''
from __future__ import annotations
from dataclasses import dataclass
from pyjs import js

@js
@dataclass(frozen=True, slots=True)
class Item:
    value: int

@js
@dataclass(frozen=True, slots=True)
class Group:
    item: Item

@js
def main() -> int:
    return Group(Item(42)).item.value
'''


@dataclass(frozen=True)
class BackendContract:
    source: str
    print_source: str
    checks: tuple[tuple[str, str], ...]

    def failure(self, result):
        if result == 0:
            return "contract passed"
        if 1 <= result <= len(self.checks):
            return f"contract check {result} failed: {self.checks[result - 1][0]}"
        return f"contract terminated with unexpected result {result}"


def _contract(imports, function_name, setup, checks, *, integer_type="int"):
    if len(checks) > 255:
        raise ValueError("backend contracts cannot exceed 255 checks")
    body = []
    if setup:
        body.append(indent(dedent(setup).strip(), "    "))
    for index, (name, failure) in enumerate(checks, 1):
        failure = dedent(failure).strip()
        body.append(f"    # {name}")
        if "\n" in failure:
            body.extend(
                (
                    "    if (",
                    indent(failure, "        "),
                    "    ):",
                )
            )
        else:
            body.append(f"    if {failure}:")
        body.append(f"        return {index}")
    body.append("    return 0")
    function_source = (
        dedent(imports).strip()
        + "\n\n\n@js\n"
        + f"def {function_name}() -> {integer_type}:\n"
        + "\n".join(body)
        + "\n"
    )
    return BackendContract(
        source=function_source
        + f"\n\ndef main() -> {integer_type}:\n    return {function_name}()\n",
        print_source=function_source
        + f"\n\ndef main() -> None:\n    print({function_name}())\n",
        checks=checks,
    )


SEQUENCE_CONSTRUCTOR_REPRESENTATION_CONTRACT = _contract(
    '''
    from pyjs import js, int8, int64

    @js
    class ConstructorSource:
        def __init__(self, value: int):
            self.value = value

    @js
    def constructor_parameter(value: int) -> int:
        copied = list[int8]((value, 1))
        if value + len(copied) != 129 or copied[0] != 127:
            return 1
        return 0

    @js
    def ordinary_constructor_value() -> int:
        return 127

    @js
    def empty_constructor_source(events: list[str]) -> tuple[()]:
        events.append("empty")
        return ()
    ''',
    "sequence_constructor_representations",
    '''
    source = [int8(127)]
    plain = list[int8](source)
    nullable = list[int8 | None](source)
    variable = tuple[int8, ...](source)
    optional = tuple[int8 | None, ...](source)
    fixed_small = tuple[int8](source)
    fixed_source = (int8(127), int64(9007199254740993))
    fixed = tuple[int8, int64](fixed_source)
    empty = list[int8]()
    empty.append(int8(127))
    cursor = iter(source)
    from_cursor = list[int8 | None](cursor)
    literal_list = list[int8]((127, 1))
    literal_nullable = list[int8 | None]((127, None))
    literal_tuple = tuple[int8, ...]((127, 1))
    literal_fixed = tuple[int8, int8]((127, 1))
    literal_mixed = tuple[int8, int64]((127, 9007199254740993))
    literal_set = set[int8]((127, 1, 127))
    source[0] = int8(3)
    nullable.append(None)
    first = nullable[0]
    second = optional[0]
    third = from_cursor[0]
    ordinary = 127
    owner = ConstructorSource(127)
    named_list = list[int8]([ordinary, owner.value, ordinary_constructor_value()])
    named_tuple = tuple[int8, int8]((ordinary, owner.value))
    annotated: list[int8] = [ordinary, owner.value]
    matching_spread = list[int8]((*plain, int8(1)))
    fresh_spread = list[int8]((*(127, 2), 1))
    nested_spread = tuple[int8, ...]((0, *[*(127, 2), 1]))
    empty_spread = list[int8]([*(), 127])
    empty_source = ()
    empty_alias = empty_source
    alias_spread = list[int8]((*empty_alias, 127))
    trailing_alias = tuple[int8, ...]((127, *empty_alias))
    represented_alias = list[int8]((*empty_alias, int8(127)))
    events: list[str] = []
    returned_empty = list[int8]((*empty_constructor_source(events), 127))
    ''',
    (("list arithmetic domain", "plain[0] + 1 != -128"),
     ("optional list domain", "first is None or first + 1 != -128"),
     ("variadic tuple domain", "variable[0] + 1 != -128"),
     ("optional tuple domain", "second is None or second + 1 != -128"),
     ("fixed tuple narrow domain", "fixed[0] + 1 != -128"),
     ("fixed tuple wide domain", "fixed[1] + 1 != int64(9007199254740994)"),
     ("fixed homogeneous tuple domain", "fixed_small[0] + 1 != -128"),
     ("empty constructor domain", "empty[0] + 1 != -128"),
     ("iterator source domain", "third is None or third + 1 != -128"),
     ("source alias unchanged", "source[0] != 3 or len(source) != 1"),
     ("copied nullable storage", "nullable[1] is not None or len(optional) != 1"),
     ("tuple literal list arity", "len(literal_list) != 2 or literal_list[1] != 1"),
     ("tuple literal optional positions", "len(literal_nullable) != 2 or literal_nullable[1] is not None"),
     ("tuple literal variable arity", "len(literal_tuple) != 2 or literal_tuple[1] != 1"),
     ("tuple literal fixed arity", "len(literal_fixed) != 2 or literal_fixed[1] != 1"),
     ("tuple literal heterogeneous positions", "len(literal_mixed) != 2 or literal_mixed[1] != 9007199254740993"),
     ("tuple literal set items", "len(literal_set) != 2 or 1 not in literal_set"),
     ("source variable stays ordinary", "ordinary + 1 != 128"),
     ("source field stays ordinary", "owner.value + 1 != 128"),
     ("source call stays ordinary", "ordinary_constructor_value() + 1 != 128"),
     ("parameter conversion is local", "constructor_parameter(127) != 0"),
     ("new slots preserve values", "named_list[0] != 127 or named_list[1] != 127 or named_list[2] != 127"),
     ("tuple slots preserve values", "named_tuple[0] != 127 or named_tuple[1] != 127"),
     ("annotated slots preserve values", "annotated[0] != 127 or annotated[1] != 127"),
     ("matching represented spread", "len(matching_spread) != 2 or matching_spread[0] + 1 != -128"),
     ("fresh spread normalization", "len(fresh_spread) != 3 or fresh_spread[0] != 127"),
     ("nested spread normalization", "len(nested_spread) != 4 or nested_spread[1] != 127"),
     ("empty spread normalization", "len(empty_spread) != 1 or empty_spread[0] != 127"),
     ("empty tuple alias normalization", "len(alias_spread) != 1 or alias_spread[0] != 127"),
     ("trailing empty alias normalization", "len(trailing_alias) != 1 or trailing_alias[0] != 127"),
     ("represented empty alias normalization", "len(represented_alias) != 1 or represented_alias[0] + 1 != -128"),
     ("empty source evaluated once", "len(returned_empty) != 1 or returned_empty[0] != 127 or events != ['empty']")),
)


# Python's ordinary generic aliases do not coerce these inputs. This compiled
# storage contract compares against explicit portable constructors, not an
# untyped CPython execution of the generic aliases themselves.
SEQUENCE_STORAGE_COERCION_CONTRACT = _contract(
    '''
    from pyjs import js, int8, float32

    @js
    def converted_storage(value: int, real: float) -> int:
        narrow = list[int8]((value,))
        rounded = list[float32]([real])
        fixed = tuple[int8, float32]((*(value, real),))
        from_list = tuple[int8, float32]([value, real])
        represented_source = (int8(value), float32(real))
        from_alias = tuple[int8, float32]((*represented_source,))
        if value + 1 != 201 or real + 1.0 != 16777218.0:
            return 1
        if int(narrow[0]) != int(int8(value)):
            return 2
        if float(rounded[0]) != float(float32(real)):
            return 3
        if int(fixed[0]) != int(int8(value)) or int(fixed[0] + 0) != int(fixed[0]):
            return 4
        if float(fixed[1]) != float(float32(real)):
            return 5
        if int(from_list[0]) != int(fixed[0]) or float(from_list[1]) != float(fixed[1]):
            return 6
        if int(from_alias[0]) != int(fixed[0]) or float(from_alias[1]) != float(fixed[1]):
            return 7
        return 0
    ''',
    "sequence_storage_coercion",
    "",
    (("copied slots normalize without changing sources", "converted_storage(200, 16777217.0) != 0"),),
)


UNION_STORAGE_COERCION_CONTRACT = _contract(
    '''
    from pyjs import js, int8, float32

    @js
    class UnionStorage:
        def __init__(self):
            self.value: int8 | str | None = None

    @js
    def union_copy(value: int | str | None) -> int8 | str | None:
        return value

    @js
    def union_read(value: int8 | str | None) -> str:
        if value is None:
            return "none"
        if isinstance(value, str):
            return "str:" + value
        return str(int(value)) + ":" + str(int(value + 0))

    @js
    def union_source(value: int | str | None, events: list[str]) -> int | str | None:
        events.append("source")
        return value

    @js
    def check_union_storage(value: int | str | None) -> int:
        if value is None:
            expected = "none"
        elif isinstance(value, str):
            expected = "str:" + value
        else:
            expected = str(int(int8(value))) + ":" + str(int(int8(value)))
        events: list[str] = []
        slot: int8 | str | None = union_source(value, events)
        owner = UnionStorage()
        owner.value = value
        literal: list[int8 | str | None] = [value]
        copied = list[int8 | str | None]((union_source(value, events),))
        fixed = tuple[int8 | str | None, str]((value, "tail"))
        if (union_read(slot) != expected or union_read(owner.value) != expected
                or union_read(literal[0]) != expected or union_read(copied[0]) != expected
                or union_read(fixed[0]) != expected or union_read(union_copy(value)) != expected
                or union_read(value) != expected):
            return 1
        if events != ["source", "source"]:
            return 2
        if value is not None and not isinstance(value, str) and value + 1 != 301:
            return 3
        return 0

    @js
    def check_union_float(value: float | None) -> bool:
        narrowed: float32 | None = value
        copied = list[float32 | None]([value])
        item = copied[0]
        if value is None:
            return narrowed is None and item is None
        return (narrowed is not None and item is not None
                and float(narrowed) == float(float32(value))
                and float(item) == float(float32(value)) and value + 1.0 == 16777218.0)

    @js
    def check_union_bool(value: None | int | bool) -> bool:
        narrowed: int8 | bool | None = value
        if isinstance(value, bool):
            return isinstance(narrowed, bool) and narrowed is value
        if value is None:
            return narrowed is None
        return narrowed is not None and int(narrowed) == int(int8(value))

    @js
    def check_union_reference(value: int | list[int] | None) -> bool:
        narrowed: int8 | list[int] | None = value
        if isinstance(value, list):
            return narrowed is value
        if value is None:
            return narrowed is None
        return (narrowed is not None and not isinstance(narrowed, list)
                and int(narrowed) == int(int8(value)))
    ''',
    "union_storage_coercion",
    "",
    (("numeric union member narrows without relabeling source", "check_union_storage(300) != 0"),
     ("None remains None at every storage boundary", "check_union_storage(None) != 0"),
     ("text member stays text", "check_union_storage('q') != 0"),
     ("numeric-looking text stays text", "check_union_storage('12') != 0"),
     ("optional float conversion", "not check_union_float(16777217.0)"),
     ("optional float None", "not check_union_float(None)"),
     ("Boolean arm is not narrowed as int", "not check_union_bool(True) or not check_union_bool(False)"),
     ("numeric/None arms beside bool", "not check_union_bool(300) or not check_union_bool(None)"),
     ("generic reference identity", "not check_union_reference([1, 2])"),
     ("numeric/None arms beside references", "not check_union_reference(300) or not check_union_reference(None)")),
)


REPRESENTED_EXTREMA_DEFAULT_CONTRACT = _contract(
    '''
    from pyjs import js, int8, int64

    @js
    def rank8(value: int8 | None) -> int:
        return -1 if value is None else 1

    @js
    def rank64(value: int64 | None) -> int:
        return -1 if value is None else 1
    ''',
    "represented_extrema_defaults",
    '''
    narrow: list[int8 | None] = []
    wide: list[int64 | None] = []
    low8 = min(narrow, key=rank8, default=int8(127))
    high8 = max(narrow, key=rank8, default=int8(127))
    low64 = min(wide, key=rank64, default=int64(9007199254740993))
    high64 = max(wide, key=rank64, default=int64(9007199254740993))
    narrow.append(None)
    narrow.append(int8(5))
    wide.append(None)
    wide.append(int64(5))
    ''',
    (("minimum narrow default", "low8 is None or low8 + 1 != -128"),
     ("maximum narrow default", "high8 is None or high8 + 1 != -128"),
     ("minimum wide default", "low64 is None or low64 + 1 != int64(9007199254740994)"),
     ("maximum wide default", "high64 is None or high64 + 1 != int64(9007199254740994)"),
     ("nonempty narrow minimum", "min(narrow, key=rank8, default=int8(7)) is not None"),
     ("nonempty narrow maximum", "max(narrow, key=rank8, default=int8(7)) != 5"),
     ("nonempty wide minimum", "min(wide, key=rank64, default=int64(7)) is not None"),
     ("nonempty wide maximum", "max(wide, key=rank64, default=int64(7)) != 5")),
)


TUPLE_ITERATOR_DEFAULT_CONTRACT = _contract(
    "from pyjs import js, int8, int64",
    "tuple_iterator_defaults",
    '''
    rows: list[tuple[int8, ...]] = [(int8(127), int8(3))]
    fallback = (int8(127), int8(2))
    cursor = iter(rows)
    present = next(cursor, fallback)
    absent = next(cursor, fallback)
    empty = ()
    no_items = next(cursor, empty)
    fixed_rows = [(int64(9007199254740993), int64(4))]
    variable_default: tuple[int64, ...] = (int64(9007199254740995),)
    fixed_cursor = iter(fixed_rows)
    fixed_present = next(fixed_cursor, variable_default)
    fixed_absent = next(fixed_cursor, variable_default)
    ''',
    (("present identity", "present is not rows[0]"),
     ("default identity", "absent is not fallback"),
     ("empty default identity", "no_items is not empty or len(no_items) != 0"),
     ("narrow item representation", "present[0] + 1 != -128 or absent[0] + 1 != -128"),
     ("fixed item identity", "fixed_present is not fixed_rows[0]"),
     ("variable default identity", "fixed_absent is not variable_default"),
     ("wide item representation", "fixed_present[0] + 1 != int64(9007199254740994)"),
     ("wide default representation", "fixed_absent[0] + 1 != int64(9007199254740996)")),
)


ITERABLE_LITERAL_CONTEXT_CONTRACT = _contract(
    '''
from collections.abc import Iterable
from pyjs import int8, js

@js
def count_nested(values: Iterable[list[list[int]]]) -> int:
    count = 0
    for group in values:
        count += 10 * len(group)
        for row in group:
            for value in row:
                count += value
    return count

@js
def nested_rows() -> Iterable[list[list[int]]]:
    return [[], [[]], [[9]]]

@js
def record(events: list[int], value: int) -> int:
    events.append(value)
    return value

@js
def fill_small(values: Iterable[list[list[int8]]]) -> bool:
    for group in values:
        for row in group:
            row.append(int8(127))
            if row[-1] + 1 != -128:
                return False
    return True
    ''',
    "iterable_literal_context",
    '''
    events: list[int] = []
    borrowed: list[list[int]] = [[7]]
    first = count_nested([[], [[]], [[record(events, 9)]], borrowed])
    second = count_nested(([], [[]], [[record(events, 8)]], borrowed))
    empty = count_nested([]) + count_nested(())
    context: Iterable[list[list[int]]] = [[], [[]], [[6]]]
    small = [[int8(1)]]
    small_list = fill_small([[], [[]], [[int8(2)]], small])
    small_tuple = fill_small(([], [[]], [[int8(3)]]))
    receiver: list[list[int8]] = []
    receiver.extend([[], [int8(3)]])
    receiver.extend([[int8(3)], []])
    receiver.extend(([], [int8(3)]))
    receiver.extend(([int8(3)], []))
    receiver.extend([[], []])
    receiver_small = fill_small([receiver])
    deep_receiver: list[list[list[int8]]] = []
    deep_receiver.extend([[], [[]], [[int8(3)]]])
    deep_receiver.extend(([], [[]], [[int8(4)]]))
    deep_receiver_small = fill_small(deep_receiver)
    ''',
    (("receiver context and sibling representations", "len(receiver) != 10 or not receiver_small"),
     ("receiver context through empty-only descendants", "len(deep_receiver) != 6 or not deep_receiver_small"),
     ("fresh list context", "first != 46"),
     ("fresh tuple context", "second != 45"),
     ("empty iterable context", "empty != 0"),
     ("return context", "count_nested(nested_rows()) != 29"),
     ("annotated context", "count_nested(context) != 26"),
     ("borrowed storage unchanged", "len(borrowed) != 1 or borrowed[0][0] != 7"),
     ("callbacks once in order", "len(events) != 2 or events[0] != 9 or events[1] != 8"),
     ("nested portable arithmetic", "not small_list or not small_tuple"),
     ("borrowed represented identity", "len(small[0]) != 2 or small[0][1] + 1 != -128")),
)


EMPTY_LITERAL_SIBLING_CONTRACT = _contract(
    "from pyjs import js, int8, int64",
    "empty_literal_siblings",
    '''
    small = [[], [int8(1)], []]
    wide = [[int64(9007199254740993)], []]
    small[0].append(int8(127))
    wide[1].append(int64(9007199254740995))
    ''',
    (("empty sibling retains int8", "small[0][0] + 1 != -128"),
     ("empty sibling retains int64", "wide[1][0] + 1 != int64(9007199254740996)"),
     ("siblings remain independent", "len(small[2]) != 0 or small[1][0] != 1"),
     ("original wide value stays exact", "wide[0][0] != int64(9007199254740993)")),
)


_SEQUENCE_REFLECTION_METHODS = '''
    from pyjs import js
    @js
    class Multiplier:
        def __mul__(self, other: str) -> int:
            return 43
        def __rmul__(self, other: str) -> int:
            return 42
    '''

SEQUENCE_REFLECTION_CONTRACT = _contract(
    _SEQUENCE_REFLECTION_METHODS,
    "sequence_reflection",
    "",
    (("numeric reflection precedes sequence repeat", "'text' * Multiplier() != 42"),
     ("numeric forward precedes sequence repeat", "Multiplier() * 'text' != 43")),
)

LITERAL_SEQUENCE_REFLECTION_CONTRACT = _contract(
    _SEQUENCE_REFLECTION_METHODS + '''
    from typing import Literal
    @js
    def refined(value: Literal['text']) -> int:
        return value * Multiplier()
    ''',
    "literal_sequence_reflection",
    "",
    (("literal receiver retains numeric priority", "refined('text') != 42"),),
)


SLICE_VALUE_CONTRACT = _contract(
    'from pyjs import js',
    "slice_values",
    '''
    selected = slice(None, None, -1)
    values = [0, 1, 2, 3]
    copied = values[selected]
    values[slice(1, 3)] = [8]
    del values[slice(None, None, 2)]
    ''',
    (("field presence", "selected.start is not None or selected.stop is not None or selected.step != -1"),
     ("normalization", "selected.indices(4) != (3, -1, -1)"),
     ("read", "copied != [3, 2, 1, 0]"),
     ("write/delete", "values != [8]"),
     ("boolean bound identity", 'repr(slice(True)) != "slice(None, True, None)"'),
     ("value equality", "slice(True) != slice(1)")),
)


BYTES_CONSTRUCTION_CONTRACT = _contract(
    'from pyjs import js',
    "bytes_construction",
    'mapping = {0: 255, 1: 128}',
    (("range", 'bytes(range(4)) != b"\\x00\\x01\\x02\\x03"'),
     ("fixed tuple", 'bytes((0, 128, 255)) != b"\\x00\\x80\\xff"'),
     ("bool items", 'bytes([False, True]) != b"\\x00\\x01"'),
     ("mixed bool/int tuple", 'bytes((True, 255, False)) != b"\\x01\\xff\\x00"'),
     ("mapping keys", 'bytes(mapping) != b"\\x00\\x01" or bytes(mapping.keys()) != b"\\x00\\x01"'),
     ("mapping values", 'bytes(mapping.values()) != b"\\xff\\x80"'),
     ("set items", 'sorted(bytes({0, 255})) != [0, 255]'),
     ("empty tuple", 'bytes(()) != b""'),
     ("empty range", 'bytes(range(0)) != b""'),
     ("zero fill", 'bytes(3) != b"\\x00\\x00\\x00"'),
     ("boolean counts", 'bytes(False) != b"" or bytes(True) != b"\\x00"')),
)


BOUNDED_TEXT_SEARCH_CONTRACT = _contract(
    'from pyjs import js',
    "bounded_text_search",
    '''
    value = "aé😀é"
    prefixes = tuple(["missing", "é"])
    ''',
    (("tuple prefix", 'not value.startswith(prefixes, 1, 3)'),
     ("tuple suffix", 'not value.endswith(("missing", "😀"), 0, -1)'),
     ("empty tuple", 'value.startswith(()) or value.endswith(())'),
     ("oversized empty prefix", 'value.startswith(("",), 100)'),
     ("negative bounded prefix", 'not value.startswith(("é", ""), -1)'),
     ("find bounds", 'value.find("é", 2) != 3 or value.rfind("é", 0, -1) != 1'),
     ("empty count bounds", 'value.count("", 1, -1) != 3')),
)


RECURSIVE_TREE_CONTRACT = _contract(
    '''
    from pyjs import js
    type Tree = int | list[Tree]

    @js
    def tree_total(value: Tree) -> int:
        if isinstance(value, int):
            return int(value)
        total = 0
        for item in value:
            total += tree_total(item)
        return total
    ''',
    "recursive_trees",
    '''
    child: Tree = [1, 2]
    root: Tree = [child, [3, child]]
    before = tree_total(root)
    if isinstance(child, list):
        child.append(5)
    ''',
    (("recursive traversal", "before != 9"),
     ("shared child mutation", "tree_total(root) != 19"),
     ("empty recursive container", "tree_total([]) != 0")),
)


RECURSIVE_EQUALITY_CONTRACT = _contract(
    '''
    from pyjs import js
    type Tree = int | str | list[Tree] | dict[str, Tree] | None

    @js
    def matches(a: Tree, b: Tree, expected: bool) -> bool:
        return ((a == b) == expected and (a != b) != expected
                and (a in [b]) == expected and (a not in [b]) != expected)

    @js
    def matches_none(a: Tree, expected: bool) -> bool:
        # Keep the literal None operand distinct from a tagged Tree argument.
        return ((a == None) == expected and (a != None) != expected
                and (None == a) == expected and (None != a) != expected)
    ''',
    "recursive_equality",
    '''
    left: Tree = [1, [2, 'three'], {'four': [None, 5]}]
    right: Tree = [1, [2, 'three'], {'four': [None, 5]}]
    different: Tree = [1, [2, 'three'], {'four': [None, 6]}]
    ''',
    (("equal independent graphs", "not matches(left, right, True)"),
     ("different nested member", "not matches(left, different, False)"),
     ("same graph", "not matches(left, left, True)"),
     ("none", "not matches(None, None, True)"),
     ("graph and none", "not matches(left, None, False) or not matches(None, left, False)"),
     ("literal none operands", "not matches_none(None, True) or not matches_none(left, False) or not matches_none(3, False)"),
     ("equal leaves", "not matches(3, 3, True) or not matches('three', 'three', True)"),
     ("different leaf kinds", "not matches('three', 3, False)")),
)


RECURSIVE_OPTIONAL_CONTRACT = _contract(
    '''
    from pyjs import js
    type Nest = list[Nest | None]
    type Link = tuple[int, Link | None]

    @js
    def push(head: Link | None, value: int) -> Link:
        return (value, head)
    ''',
    "recursive_optionals",
    '''
    root: Nest = [None]
    root.append(root)
    link = push(push(None, 2), 1)
    values: dict[str, Link] = {"first": link}
    found = values.get("first", link)
    missing = values.setdefault("second", link)
    same = False
    if isinstance(root, list):
        same = root[1] is root
    ''',
    (("optional cycle construction", "len(root) != 2 or not same"),
     ("optional tuple generic lookup", "len(found) != 2 or found is not link"),
     ("optional tuple insertion identity", "missing is not link or len(values) != 2")),
)


RECURSIVE_UNION_CONTRACT = _contract(
    '''
    from pyjs import js
    type Container = dict[str, Value] | list[Value]
    type Value = Container | int | str | None

    @js
    def width(value: Container) -> int:
        if isinstance(value, list):
            return len(value)
        return len(value)

    @js
    def size(value: Value) -> int:
        if value is None:
            return 0
        if isinstance(value, int):
            return 1
        if isinstance(value, str):
            return len(value)
        total = 0
        if isinstance(value, list):
            for item in value:
                total += size(item)
        else:
            for item in value.values():
                total += size(item)
        return total
    ''',
    "recursive_unions",
    '''
    breadth = width([])
    child: Value = [1, "ab", None]
    root: Value = {"x": child, "y": [child, 3]}
    ''',
    (("container-first resolution", "breadth != 0"),
     ("mutual union traversal", "size(root) != 7")),
)


LOOP_ELSE_DECLARATION_CONTRACT = _contract(
    "from pyjs import js",
    "loop_else_declarations",
    '''
    for item in [7]:
        body_value = 9
    else:
        pass
    for second in [2]:
        changed = second
    else:
        changed += 3
    ''',
    (("target survives else", "item != 7"),
     ("body local survives else", "body_value != 9"),
     ("else writes update the exhaustion state", "changed != 5")),
)


NESTED_LOOP_ELSE_BREAK_CONTRACT = _contract(
    '''
from pyjs import js

# Decimal trace: inner body=1, outer continuation=2, inner else=3, outer else=4.
@js
def for_probe(count: int) -> int:
    events = 0
    values: list[int] = []
    if count > 0:
        values = [5]
    for outer in [1, 2, 3]:
        for inner in values:
            events = events * 10 + 1
            break
        else:
            events = events * 10 + 3
            break
        events = events * 10 + 2
    else:
        events = events * 10 + 4
    return events

@js
def while_probe(count: int) -> int:
    events = 0
    outer = 0
    while outer < 3:
        outer += 1
        inner = 0
        while inner < count:
            inner += 1
            events = events * 10 + 1
            break
        else:
            events = events * 10 + 3
            break
        events = events * 10 + 2
    else:
        events = events * 10 + 4
    return events
''', "nested_loop_else_break", "", (
        ("for else break skips outer else", "for_probe(0) != 3"),
        ("for body break stays local", "for_probe(1) != 1212124"),
        ("while else break skips outer else", "while_probe(0) != 3"),
        ("while body break stays local", "while_probe(1) != 1212124"),
    ),
)


NESTED_CONDITIONAL_CONTRACT = _contract(
    '''
from pyjs import js, int8, float32

@js
class Recorder:
    def __init__(self):
        self.events = 0

    def record(self, value: int) -> int:
        self.events = self.events * 10 + value
        return value

@js
def combine(left: int, right: int) -> int:
    return left * 10 + right
''',
    "nested_conditional_contract",
    '''
    recorder = Recorder()
    flag = True
    value = combine(recorder.record(1), recorder.record(2) if flag else recorder.record(3))
    call_order = recorder.events
    recorder.events = 0
    conjunction = False and ((recorder.record(4) == 4) if flag else (recorder.record(5) == 5))
    disjunction = True or ((recorder.record(6) == 6) if flag else (recorder.record(7) == 7))
    skipped = recorder.events
    recorder.events = 0
    values = [recorder.record(1), recorder.record(2) if flag else recorder.record(3)]
    item_order = recorder.events
    recorder.events = 0
    compared = recorder.record(1) < (recorder.record(2) if flag else recorder.record(3))
    comparison_order = recorder.events
    recorder.events = 0
    combined = (recorder.record(1) if flag else recorder.record(2)) + (recorder.record(3) if flag else recorder.record(4))
    branch_order = recorder.events
    small = int8(127)
    wrapped = (small if flag else int8(0)) + int8(1)
    rounded = float32(1.25) + (float32(2.5) if flag else float32(0.0))
    ''',
    (
        ("conditional arguments follow preceding arguments", "call_order != 12 or value != 12"),
        ("short circuit skips nested conditional effects", "conjunction or not disjunction or skipped != 0"),
        ("literal items preserve evaluation order", "item_order != 12 or values[1] != 2"),
        ("comparison operands preserve evaluation order", "not compared or comparison_order != 12"),
        ("conditional siblings preserve evaluation order", "combined != 4 or branch_order != 13"),
        ("nested conditionals preserve portable representations", "wrapped != int8(-128) or rounded != float32(3.75)"),
    ),
)


OBJECT_COMPARISON_CONTRACT = _contract(
    '''
from pyjs import js

@js
class ComparedRow:
    def __init__(self, value: int):
        self.value = value

    def __eq__(self, other: "ComparedRow") -> bool:
        return self.value % 10 == other.value % 10

@js
def comparison_record(events: list[int], value: int) -> int:
    events.append(value)
    return value
''',
    "object_comparison_contract",
    '''
    a = [ComparedRow(1), ComparedRow(2)]
    b = [ComparedRow(11), ComparedRow(12)]
    events: list[int] = []
    ordered = comparison_record(events, 1) < comparison_record(events, 2) < comparison_record(events, 3)
    stopped = comparison_record(events, 4) < comparison_record(events, 3) < comparison_record(events, 0)
    ''',
    (
        ("custom equality in lists", "a != b"),
        ("custom equality nested in mixed tuples", '(a, "x") != (b, "x")'),
        ("custom equality in mapping values", '{"a": a} != {"a": b}'),
        ("list searches use equality", "ComparedRow(21) not in a or a.index(ComparedRow(22)) != 1 or a.count(ComparedRow(11)) != 1"),
        ("tuple search", "(ComparedRow(1), ComparedRow(2)).count(ComparedRow(11)) != 1"),
        ("iterator membership", "ComparedRow(11) not in iter(a)"),
        ("chained comparison value", "not ordered or stopped"),
        ("chained comparison evaluation order", "events != [1, 2, 3, 4, 3]"),
    ),
)


ERASED_EQUALITY_CONTRACT = _contract(
    '''
from pyjs import js

@js
def erased_equal(left: object, right: object) -> bool:
    return left == right
''',
    "erased_equality_contract",
    '''
    values: list[object] = [None, True, 1, 1.0, "one", [1, 2]]
    copied = values.copy()
    ''',
    (
        ("erased absence", "not erased_equal(values[0], None) or erased_equal(values[0], 0)"),
        ("erased numeric equality", "not erased_equal(values[1], values[2]) or not erased_equal(values[2], values[3])"),
        ("erased unlike kinds", 'erased_equal(values[2], "1") or erased_equal(values[4], 1)'),
        ("erased sequence members", "values != copied or values.count(1) != 3 or values.index(1.0) != 1"),
        ("erased nested layout", "not erased_equal(values[5], [1.0, 2.0]) or erased_equal(values[5], [2, 1])"),
    ),
)


OBJECT_ORDERING_CONTRACT = _contract(
    '''
from pyjs import js

@js
class OrderedRow:
    def __init__(self, rank: int, label: str):
        self.rank = rank
        self.label = label

    def __eq__(self, other: "OrderedRow") -> bool:
        return self.rank == other.rank

    def __lt__(self, other: "OrderedRow") -> bool:
        return self.rank < other.rank

    def __gt__(self, other: "OrderedRow") -> bool:
        return self.rank > other.rank

@js
def ordering_key(row: OrderedRow) -> str:
    return row.label

@js
def ordering_labels(rows: list[OrderedRow]) -> str:
    result = ""
    for row in rows:
        result += row.label
    return result
''',
    "object_ordering_contract",
    '''
    a = OrderedRow(2, "a")
    b = OrderedRow(1, "b")
    c = OrderedRow(2, "c")
    rows = [a, b, c]
    keyed = sorted(rows, key=ordering_key, reverse=True)
    rows.sort()
    ''',
    (
        ("stable object sorting", 'ordering_labels(rows) != "bac"'),
        ("stable reverse sorting", 'ordering_labels(sorted(rows, reverse=True)) != "acb"'),
        ("cached keys", 'ordering_labels(keyed) != "cba"'),
        ("object comparison", "not (b < a)"),
        ("first winning extrema", "min(rows) is not b or max(rows) is not a"),
        ("keyed extrema", "max(rows, key=ordering_key) is not c"),
    ),
)


GENERATOR_CONTRACT = _contract(
    '''
from collections.abc import Iterator, Callable
from pyjs import js, int8

@js
def generated(events: list[int], stop: int) -> Iterator[int]:
    events.append(stop)
    for value in range(stop):
        if value == 1:
            continue
        yield value
    events.append(10)

@js
def generated_callbacks() -> Iterator[Callable[[int8], int8]]:
    yield lambda value: value + int8(1)

@js
def callback_expressions() -> Iterator[Callable[[int8], int8]]:
    return (lambda value: value + int8(1) for index in range(2))
''',
    "generator_contract",
    '''
    events: list[int] = []
    first = generated(events, 4)
    second = generated(events, 2)
    lazy = len(events)
    a = next(first)
    b = next(second)
    tail = list(first)
    other = list(second)
    rows = (a * 10 + b for a in [1, 2, 3] if a > 1 for b in range(a) if b != 1)
    nested = ((value for value in range(stop)) for stop in [2, 3])
    inner = next(nested)
    outer_tail = list(next(nested))
    callbacks = list(generated_callbacks())
    expressions = list(callback_expressions())
    represented = list(value + int8(1) for value in [int8(126), int8(127)])
    ''',
    (
        ("creation does not execute the body", "lazy != 0"),
        ("independent suspended loops", "a != 0 or b != 0 or tail != [2, 3] or other != []"),
        ("side effects execute once", "events != [4, 2, 10, 10]"),
        ("permanent exhaustion", "next(first, -1) != -1"),
        ("nested expression loops and filters", "list(rows) != [20, 30, 32]"),
        ("nested generators retain independent outer iterators", "list(inner) != [0, 1] or outer_tail != [0, 1, 2]"),
        ("contextual yielded and expression callables", "callbacks[0](int8(127)) != int8(-128) or expressions[0](int8(127)) != int8(-128)"),
        ("portable item representation", "represented != [int8(127), int8(-128)]"),
    ),
)


GENERATOR_CLEANUP_CONTRACT = _contract(
    '''
from collections.abc import Iterator
from pyjs import js

@js
def cleanup_values(events: list[int], value: int) -> Iterator[int]:
    try:
        try:
            yield value
            raise ValueError("body")
        except ValueError as error:
            yield value + 1
            assert str(error) == "body"
            events.append(value)
            return
    finally:
        yield value + 2
        events.append(value + 10)
''',
    "generator_cleanup_contract",
    '''
    events: list[int] = []
    first = cleanup_values(events, 1)
    second = cleanup_values(events, 4)
    lazy = len(events)
    initial = [next(first), next(second)]
    caught = [next(first), next(second)]
    pending = len(events)
    cleanup = [next(first), next(second)]
    before_exhaustion = list(events)
    rest = list(first) + list(second)
    ''',
    (
        ("creation is lazy", "lazy != 0"),
        ("independent suspended try bodies", "initial != [1, 4]"),
        ("handler snapshots survive resumes", "caught != [2, 5] or pending != 0"),
        ("return suspends in finally", "cleanup != [3, 6] or before_exhaustion != [1, 4]"),
        ("cleanup resumes exactly once", "rest != [] or events != [1, 4, 11, 14]"),
        ("closed after cleanup", "next(first, -1) != -1 or next(second, -1) != -1"),
    ),
)


COMPREHENSION_CONTRACT = _contract(
    '''
from typing import Callable
from pyjs import js, int8

@js
def comp_mark(events: list[int], value: int) -> int:
    events.append(value)
    return value

@js
def comp_callbacks() -> list[Callable[[int8], int8]]:
    return [lambda value: value + int8(1) for index in range(2)]

@js
def comp_accept(events: list[int8], value: int8) -> bool:
    events.append(value)
    return value != 0

@js
class CompRow:
    def __init__(self, label: str | None):
        self.label = label
''',
    "comprehension_contract",
    '''
    events: list[int] = []
    left = 100
    values = [1, 2, 3]
    rows = [left * 10 + right for left in values if left > 1 for right in range(left) if right != 1]
    nested = [[a + b for b in range(2)] for a in values]
    unique = {value % 2 for value in values}
    mapping = {comp_mark(events, value): comp_mark(events, value + 10) for value in [1, 1, 2]}
    represented = [value + int8(1) for value in [int8(126), int8(127)]]
    callbacks = comp_callbacks()
    nullable: list[int8 | None] = [None, int8(127), int8(0), int8(-128)]
    filter_events: list[int8] = []
    filtered = [value + 1 for value in nullable if value is not None if comp_accept(filter_events, value)]
    sources: list[list[int8] | None] = [None, [int8(127)]]
    narrowed_nested = [value + 1 for row in sources if row is not None for value in row]
    shadowed = [value for value in nullable if value is not None for value in [None, value]]
    labels = [row.label.upper() for row in [CompRow("ready")] if row.label is not None
              for row in [CompRow(None), CompRow(row.label)] if row.label is not None]
    ''',
    (
        ("loop variables remain private", "left != 100"),
        ("nested loops and filters", "rows != [20, 30, 32]"),
        ("nested scopes", "nested != [[1, 2], [2, 3], [3, 4]]"),
        ("set results", "unique != {0, 1}"),
        ("dictionary key/value ordering and overwrites", "mapping != {1: 11, 2: 12} or events != [1, 11, 1, 11, 2, 12]"),
        ("represented items", "represented != [int8(127), int8(-128)]"),
        ("contextual callable results", "callbacks[0](int8(127)) != int8(-128)"),
        ("filters retain numeric narrowing", "filtered != [int8(-128), int8(-127)] or filter_events != [int8(127), int8(0), int8(-128)]"),
        ("filters narrow inner iterable sources", "narrowed_nested != [int8(-128)]"),
        ("inner targets replace prior narrowing", "shadowed != [None, int8(127), None, int8(0), None, int8(-128)]"),
        ("rebound receiver fields need fresh proofs", 'labels != ["READY"]'),
    ),
)


ITERATOR_CALLBACK_CONTRACT = _contract(
    '''
from pyjs import js, int8

@js
def iterator_record(events: list[int], value: int) -> int:
    events.append(value)
    return value * 2

@js
def iterator_increment(value: int8) -> int8:
    return value + int8(1)
''',
    "iterator_callback_contract",
    '''
    events: list[int] = []
    values = map(lambda n: iterator_record(events, n), [1, 2, 3])
    before = len(events)
    first = next(values)
    after_first = len(events)
    tail = list(values)
    pairs = list(map(lambda a, b: a + b, [1, 2, 3], [10, 20]))
    selected = list(filter(lambda value: value > 2, [0, 1, 2, 3, 4]))
    truthy = list(filter(None, ["", "a", "", "b"]))
    represented = list(map(iterator_increment, [int8(126), int8(127)]))
    nested = list(enumerate(filter(lambda value: value != 2, map(lambda value: value + 1, [0, 1, 2]))))
    ''',
    (
        ("callback creation is lazy", "before != 0"),
        ("each advance invokes the callback", "first != 2 or after_first != 1 or tail != [4, 6] or events != [1, 2, 3]"),
        ("multiple sources stop at the shortest", "pairs != [11, 22]"),
        ("filter preserves selected input items", "selected != [3, 4]"),
        ("None predicate uses item truth", 'truthy != ["a", "b"]'),
        ("callback result representations", "represented != [int8(127), int8(-128)]"),
        ("nested lazy adapters", "nested != [(0, 1), (1, 3)]"),
    ),
)


LAMBDA_CLOSURE_CONTRACT = _contract(
    '''
from collections.abc import Callable
from pyjs import js, int8

@js
def make_lambda(offset: int) -> Callable[[int], Callable[[int], int]]:
    callback: Callable[[int], Callable[[int], int]] = lambda value: lambda extra: offset + value + extra
    offset += 1
    return callback

@js
def shadow_lambda(offset: int) -> Callable[[int], Callable[[int], int]]:
    return lambda offset: lambda extra: offset + extra

@js
def narrow_lambda(offset: int8) -> Callable[[int8], int8]:
    return lambda value: value + offset

@js
def conditional_lambda(offset: int8) -> Callable[[bool], Callable[[int8], int8]]:
    return lambda flag: (lambda extra: offset + extra) if flag else (lambda extra: offset - extra)

@js
def lambda_effect(events: list[int], value: int) -> int:
    events.append(value)
    return 12 // value
''',
    "lambda_closure_contract",
    '''
    make = make_lambda(10)
    first = make(2)
    second = make(3)
    shadow = shadow_lambda(100)(4)
    events: list[int] = []
    choose: Callable[[int], int] = lambda value: lambda_effect(events, value) if value > 0 else 9
    before = len(events)
    fallback = choose(0)
    after = len(events)
    taken = choose(3)
    narrow = narrow_lambda(int8(120))
    select = conditional_lambda(int8(127))
    ''',
    (
        ("captures see later rebinding", "first(1) != 14"),
        ("invocations have independent parameter cells", "second(1) != 15"),
        ("nested parameters shadow outer bindings", "shadow(5) != 9"),
        ("lambda bodies and untaken branches are lazy", "before != 0 or after != 0 or fallback != 9"),
        ("taken branch executes once", "taken != 4 or len(events) != 1 or events[0] != 3"),
        ("represented parameters and results", "narrow(int8(20)) != int8(-116)"),
        ("conditional lambdas inherit represented signatures", "select(True)(int8(1)) != int8(-128) or select(False)(int8(1)) != int8(126)"),
    ),
)


CALLABLE_INPUT_CONTRACT = _contract(
    '''
from collections.abc import Callable
from pyjs import js

@js
def broad(value: object) -> int:
    return 7

@js
def factory() -> Callable[[int], int]:
    return broad

@js
def forward(callback: Callable[[object], int]) -> Callable[[str], int]:
    return callback
''',
    "callable_inputs",
    '''
    narrow = factory()
    text = forward(broad)
    ''',
    (("contravariant callback inputs", "narrow(3) != 7 or text('hello') != 7"),),
)


CALLABLE_DEFAULT_CONTRACT = _contract(
    '''
from collections.abc import Callable
from pyjs import js

@js
def first(value: int, extra: int = 10) -> int:
    return value + extra

@js
def second(value: int, extra: int = 20) -> int:
    return value + extra

@js
def choose(other: bool) -> Callable[[int], int]:
    return second if other else first

@js
def conditional(other: bool) -> int:
    callback = second if other else first
    return callback(2)

@js
class Box[T]:
    def __init__(self, value: T):
        self.value = value
    def get(self) -> T:
        return self.value

@js
def consume_box(box: Box[Callable[[int], int]]) -> int:
    callback = box.get()
    return callback(3)

@js
class Long:
    def read(self, value: int, extra: int = 10) -> int:
        return value + extra

@js
class Short:
    def read(self, value: int) -> int:
        return value

@js
class Other:
    def read(self, value: int, extra: str = "x") -> int:
        return value + len(extra)

@js
class Wide:
    def read(self, value: object, extra: int = 10) -> int:
        return 7

@js
def union_forward(value: Long | Short | Other | Wide) -> int:
    callback = value.read
    return callback(4)

@js
def union_reverse(value: Wide | Other | Short | Long) -> int:
    callback = value.read
    return callback(4)

@js
def consume_method(callback: Callable[[int], int]) -> int:
    return callback(4)

@js
def direct_union_forward(value: Long | Short | Other | Wide) -> int:
    return consume_method(value.read)

@js
def direct_union_reverse(value: Wide | Other | Short | Long) -> int:
    return consume_method(value.read)

@js
def indirect_union(value: Long | Short | Other | Wide,
                   consumer: Callable[[Callable[[int], int]], int]) -> int:
    return consumer(value.read)

@js
def local_union(value: Wide | Other | Short | Long) -> int:
    consumer: Callable[[Callable[[int], int]], int] = consume_method
    return consumer(value.read)
''',
    "callable_defaults",
    '''
    callback = first
    a = callback(1)
    callback = second
    b = callback(1)
    shortened: Callable[[int], int] = first
    box = Box[Callable[[int], int]](first)
    before = consume_box(box)
    box.value = second
    inferred = Box(first)
    inferred_callback = inferred.get()
    ''',
    (("inferred omitted arguments", "a != 11 or b != 21"),
     ("conditional defaults", "conditional(False) != 12 or conditional(True) != 22"),
     ("shorter view", "shortened(3) != 13"),
     ("returned view", "choose(True)(3) != 23"),
     ("explicit generic callback storage", "before != 13 or consume_box(box) != 23"),
     ("inferred generic callback storage", "inferred_callback(1) != 11"),
     ("union common prefix", "union_forward(Long()) != 14 or union_forward(Short()) != 4 or union_forward(Other()) != 5 or union_forward(Wide()) != 7"),
     ("union order independence", "union_reverse(Long()) != 14 or union_reverse(Short()) != 4 or union_reverse(Other()) != 5 or union_reverse(Wide()) != 7"),
     ("direct union argument", "direct_union_forward(Long()) != 14 or direct_union_forward(Short()) != 4 or direct_union_forward(Other()) != 5 or direct_union_forward(Wide()) != 7"),
     ("direct union argument order", "direct_union_reverse(Long()) != 14 or direct_union_reverse(Short()) != 4 or direct_union_reverse(Other()) != 5 or direct_union_reverse(Wide()) != 7"),
     ("indirect union argument", "indirect_union(Long(), consume_method) != 14 or indirect_union(Short(), consume_method) != 4 or indirect_union(Other(), consume_method) != 5 or indirect_union(Wide(), consume_method) != 7"),
     ("local callable union argument", "local_union(Long()) != 14 or local_union(Short()) != 4 or local_union(Other()) != 5 or local_union(Wide()) != 7"),
     ("view retains identity", "shortened is not first")),
)


CALLABLE_ITERABLE_CONTRACT = _contract(
    '''
from collections.abc import Callable, Iterable
from pyjs import js

@js
def total(values: Iterable[int]) -> int:
    result = 0
    for value in values:
        result += value
    for value in values:
        result += value
    return result

@js
def as_consumer() -> Callable[[list[int]], int]:
    return total

@js
def rows() -> list[int]:
    return [3, 4]

@js
def as_producer() -> Callable[[], Iterable[int]]:
    return rows

@js
def mapping() -> dict[int, int]:
    return {3: 30, 4: 40}

@js
def as_mapping_consumer() -> Callable[[dict[int, int]], int]:
    return total

@js
def as_mapping_producer() -> Callable[[], Iterable[int]]:
    return mapping

@js
def text_items(values: Iterable[int | str]) -> str:
    result = ""
    for value in values:
        result += value if isinstance(value, str) else str(value)
    for value in values:
        result += value if isinstance(value, str) else str(value)
    return result

@js
def wide_consumer() -> Callable[[list[int]], str]:
    return text_items

@js
def wide_producer() -> Callable[[], Iterable[int | str]]:
    return rows

@js
def wider(values: Iterable[int]) -> Iterable[int | str]:
    return values
''',
    "callable_iterables",
    '''
    consume = as_consumer()
    produce = as_producer()
    mapping_consume = as_mapping_consumer()
    mapping_produce = as_mapping_producer()
    wide_consume = wide_consumer()
    wide_produce = wide_producer()
    ''',
    (("reusable input view", "consume([3, 4]) != 14"),
     ("reusable result view", "total(produce()) != 14"),
     ("mapping input keys", "mapping_consume(mapping()) != 14"),
     ("mapping result keys", "total(mapping_produce()) != 14"),
     ("widened input items", 'wide_consume([3, 4]) != "3434"'),
     ("widened result items", 'text_items(wide_produce()) != "3434"'),
     ("chained item views", 'text_items(wider(produce())) != "3434"')),
)


APPLICATION_GENERIC_UNION_ORDER_CONTRACT = _contract(
    imports='''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
            def get(self) -> T:
                return self.value
        @js
        def read(box: Box[int | str]) -> str:
            value = box.get()
            if isinstance(value, int):
                return str(value + 1)
            return value
        @js
        def make(value: str | int) -> Box[str | int]:
            return Box(value)
        @js
        def optional(box: Box[None | int]) -> int:
            value = box.get()
            return value + 1 if value is not None else 0
        @js
        def nested(box: Box[list[int | str]]) -> str:
            value = box.get()[0]
            if isinstance(value, int):
                return str(value + 1)
            return value
    ''',
    function_name="application_generic_union_orders",
    setup='''
        explicit = Box[str | int](1)
        text = make("text")
        number = make(2)
        optional_number = Box[int | None](3)
        absent = Box[int | None](None)
        items: list[str | int] = [4]
        nested_box = Box[list[str | int]](items)
    ''',
    checks=(
        ("explicit opposite-order instance method", 'read(explicit) != "2"'),
        ("inferred opposite-order factory", 'read(text) != "text" or read(number) != "3"'),
        ("optional union order", "optional(optional_number) != 4 or optional(absent) != 0"),
        ("nested builtin view order", 'nested(nested_box) != "5"'),
    ),
)


GENERIC_UNION_ORDER_CONTRACT = _contract(
    '''
from pyjs import js, int8
@js
def numeric_first(values: list[int8 | str]) -> str:
    value = values[0]
    if isinstance(value, int):
        return str(value + 1)
    return value
@js
def text_first(values: list[str | int8]) -> str:
    value = values[0]
    if isinstance(value, int):
        return str(value + 1)
    return value
''',
    "generic_union_orders", "",
    (("numeric union member", "numeric_first([int8(127)]) != '-128' or text_first([int8(127)]) != '-128'"),
     ("text union member", "numeric_first(['text']) != 'text' or text_first(['text']) != 'text'")),
)


UNION_METHOD_RESULT_TYPES = '''
from pyjs import js, int8

@js
class NumericResult:
    def value(self) -> int8:
        return int8(127)

@js
class TextResult:
    def value(self) -> str:
        return 'text'
'''


UNION_CALLBACK_RESULT_CONTRACT = _contract(
    UNION_METHOD_RESULT_TYPES + '''
@js
def label(source: NumericResult | TextResult) -> str:
    callback = source.value
    alias = callback
    callbacks = [alias]
    result = callbacks[0]()
    if isinstance(result, int):
        return str(result + 1)
    return result

@js
def reverse(source: TextResult | NumericResult) -> str:
    callback = source.value
    result = callback()
    if isinstance(result, int):
        return str(result + 1)
    return result
''',
    "union_callback_results",
    "",
    (("represented result arm", "label(NumericResult()) != '-128' or reverse(NumericResult()) != '-128'"),
     ("ordinary result arm", "label(TextResult()) != 'text' or reverse(TextResult()) != 'text'")),
)


DIRECT_UNION_RESULT_CONTRACT = _contract(
    UNION_METHOD_RESULT_TYPES + '''
@js
def direct(source: TextResult | NumericResult) -> str:
    result = source.value()
    if isinstance(result, int):
        return str(result + 1)
    return result

@js
def parenthesized(source: NumericResult | TextResult) -> str:
    result = (source.value)()
    if isinstance(result, int):
        return str(result + 1)
    return result
''',
    "direct_union_results",
    "",
    (("direct result arm", "direct(NumericResult()) != '-128' or direct(TextResult()) != 'text'"),
     ("parenthesized result arm", "parenthesized(NumericResult()) != '-128' or parenthesized(TextResult()) != 'text'")),
)


CALLABLE_VALUE_CONTRACT = _contract(
    '''
from collections.abc import Callable
from pyjs import js, int8

@js
class Counter:
    def __init__(self, value: int):
        self.value = value

    def add(self, value: int) -> int:
        self.value += value
        return self.value

@js
def make_callback(value: int) -> Callable[[int], int]:
    return Counter(value).add

@js
def record_receiver(counter: Counter, events: list[int]) -> Counter:
    events.append(counter.value)
    return counter

@js
def increment(value: int) -> int:
    return value + 1

@js
def narrow(value: int8) -> int8:
    return value + int8(1)

@js
def convert(value: int8) -> int:
    return int(value + int8(1))

@js
def apply(callback: Callable[[int8], int8], value: int8) -> int8:
    return callback(value)

@js
def key(value: int) -> int:
    return -value

@js
def accept_any(callback: Callable[..., int]) -> int:
    return 7

@js
def accept_narrow(callback: Callable[..., int8]) -> int:
    return 9

''',
    "callable_values",
    '''
    plain: Callable[[int], int] = increment
    counter = Counter(10)
    method = counter.add
    callbacks: list[Callable[[int], int]] = [plain, method, make_callback(20)]
    total = 0
    for callback in callbacks:
        total += callback(2)
    key_value: Callable[[int], int] = key
    ordered = sorted([3, 1, 2], key=key_value)
    in_place = [3, 1, 2]
    same_list = in_place
    in_place.sort(key=key_value, reverse=True)
    empty: list[int] = []
    events: list[int] = []
    recorded = record_receiver(counter, events).add
    recorded_value = recorded(3)
    narrow_value: Callable[[int8], int8] = narrow
    unspecified = accept_any(make_callback(30)) + accept_narrow(narrow_value)
    ordinary_result: Callable[[int8], int] = convert
    converted = accept_any(ordinary_result) + accept_any(callback=ordinary_result)
    ''',
    (("named, bound, and returned callback values", "total != 37 or counter.value != 15"),
     ("function declarations retain callable identity", "plain is not increment or increment is not plain or increment is key"),
     ("receiver evaluated once", "len(events) != 1 or events[0] != 12 or recorded_value != 15"),
     ("callback numeric storage", "apply(narrow, int8(127)) != int8(-128)"),
     ("unspecified callback parameters preserve result typing", "unspecified != 16"),
     ("represented callback parameters with ordinary result", "converted != 14 or ordinary_result(int8(127)) != -128"),
     ("in-place keyed sorting", "in_place is not same_list or in_place[0] != 1 or in_place[2] != 3"),
     ("keyed extrema", "min(ordered, key=key_value) != 3 or max(1, 3, 2, key=key_value) != 1"),
     ("empty keyed extrema", "min(empty, key=key_value, default=7) != 7"),
     ("typed key callback", "ordered[0] != 3 or ordered[1] != 2 or ordered[2] != 1")),
)


TUPLE_INDEX_CONTRACT = _contract(
    "from pyjs import js, int8, int64",
    "tuple_index_contract",
    '''
    row = (7, "text", int8(127), int64(40))
    ''',
    (
        ("signed indexes preserve nominal types", 'row[-3].upper() != "TEXT" or row[+0] != 7'),
        ("negative index preserves int8", "row[-2] + int8(1) != int8(-128)"),
        ("negative index preserves int64", "row[-1] + int64(2) != int64(42)"),
    ),
)


UNION_KEY_REPRESENTATION_CONTRACT = _contract(
    "from pyjs import js, int8, int64, float32",
    "union_key_representation_contract",
    '''
    small: dict[int8 | None, int] = {int8(1): 10, None: 20}
    mixed: dict[float32 | str, int] = {float32(2.5): 30, "key": 40}
    query: int8 | None = int8(1)
    small[query] = 11
    wide: dict[int64 | None, int] = {int64(1): 50, None: 60}
    ''',
    (("represented member lookup", "small[int8(1)] != 11"),
     ("absent-representation member lookup", "small[None] != 20"),
     ("union query lookup", "small[query] != 11"),
     ("represented float member", "mixed[float32(2.5)] != 30"),
     ("ordinary string member", 'mixed["key"] != 40'),
     ("represented membership", "int8(1) not in small or float32(2.5) not in mixed"),
     ("BigInt member lookup", "wide[int64(1)] != 50 or wide[None] != 60"),
     ("BigInt member membership", "int64(1) not in wide or None not in wide")),
)


SET_CONSTRUCTOR_REPRESENTATION_CONTRACT = _contract(
    "from pyjs import js, int8",
    "set_constructor_representation_contract",
    '''
    source: list[int8 | None] = [int8(127), None]
    values = set[int8 | None](source)
    copied = values.copy()
    source.clear()
    wrapped = 0
    for item in copied:
        if item is not None:
            wrapped = int(item + 1)
    ''',
    (("explicit constructor and copy retain int8", "wrapped != -128"),
     ("fresh set preserves members independently", "len(values) != 2 or None not in copied"),
     ("copy is independent storage", "copied is values")),
)


SCALAR_SET_RELATIONS_CONTRACT = _contract(
    "from pyjs import js",
    "scalar_set_relations_contract",
    '''
    wide: set[int | None] = {None, 1}
    integers = {1}
    floats = {1.0}
    ''',
    (("different scalar domains compare by value", "integers != floats"),
     ("proper superset uses both layouts", "not wide > floats"),
     ("reverse relation uses both layouts", "not floats < wide"),
     ("sources are not retyped or mutated", "len(wide) != 2 or len(floats) != 1")),
)


MAPPING_LOOKUP_REPRESENTATION_CONTRACT = _contract(
    "from pyjs import js, int8, float32",
    "mapping_lookup_representation_contract",
    '''
    fallback: tuple[int8, list[float32]] = (int8(127), [float32(16777216.0)])
    values: dict[str, tuple[int8, list[float32]]] = {"hit": fallback}
    hit = values.get("hit", fallback)
    miss = values.get("missing", fallback)
    inserted = values.setdefault("added", fallback)
    existing = values.setdefault("hit", fallback)
    removed = values.pop("added", fallback)
    absent = values.pop("missing", fallback)
    ''',
    (
        ("get hit/miss retain tuple int8", "hit[0] + 1 != -128 or miss[0] + 1 != -128"),
        ("setdefault hit/miss retain tuple int8", "inserted[0] + 1 != -128 or existing[0] + 1 != -128"),
        ("pop hit/miss retain tuple int8", "removed[0] + 1 != -128 or absent[0] + 1 != -128"),
        ("get retains nested float32", "hit[1][0] + 1 != 16777216.0 or miss[1][0] + 1 != 16777216.0"),
        ("setdefault retains nested float32", "inserted[1][0] + 1 != 16777216.0"),
        ("pop retains nested float32", "removed[1][0] + 1 != 16777216.0"),
        ("lookups preserve identity", "hit is not fallback or inserted is not fallback or removed is not fallback"),
    ),
)


MAPPING_VIEW_REPRESENTATION_CONTRACT = _contract(
    "from pyjs import js, int8, int64, float32, StaticArray",
    "mapping_view_representation_contract",
    '''
    mapping = {int8(127): int64(9223372036854775807)}
    row = next(iter(mapping.items()))
    rounded = {"a": float32(16777216.0)}
    nested = {"a": StaticArray[int8, 1]([127])}
    ''',
    (
        ("keys view retains int8", "next(iter(mapping.keys())) + 1 != -128"),
        ("values view retains int64", "next(iter(mapping.values())) + 1 != -9223372036854775808"),
        ("items view retains both fields", "row[0] + 1 != -128 or row[1] + 1 != -9223372036854775808"),
        ("values view retains float32", "next(iter(rounded.values())) + 1 != 16777216.0"),
        ("values view retains nested arrays", "next(iter(nested.values()))[0] + 1 != -128"),
    ),
)


LAZY_ITERATOR_CONTRACT = _contract(
    "from pyjs import js",
    "lazy_iterator_contract",
    '''
    values = iter([2, 4, 6])
    alias = iter(values)
    first = next(alias)
    tail = list(values)
    short = iter([0, 7, 9])
    truth = any(short)
    remainder = next(short)
    rows = list(enumerate(zip([1, 2], ["a", "b"]), start=3))
    ''',
    (
        ("iterator identity and shared cursor", "alias is not values or first != 2 or tail != [4, 6]"),
        ("persistent exhaustion and truth", "next(alias, 8) != 8 or next(values, 9) != 9 or not bool(values)"),
        ("short-circuit consumption", "not truth or remainder != 9"),
        ("nested adapter row layout", 'rows != [(3, (1, "a")), (4, (2, "b"))]'),
        ("constructor consumes remaining items", "set(iter([2, 2, 4])) != {2, 4}"),
        ("reversed unicode", 'list(reversed("aé😀")) != ["😀", "é", "a"]'),
        ("range iterator reductions", "sum(iter(range(5))) != 10"),
    ),
)


EAGER_COLLECTION_CONTRACT = _contract(
    "from pyjs import int8, js",
    "eager_collection_contract",
    '''
    original = [3, 1, 2, 1]
    copied = list(original)
    copied.sort()
    mapping = dict([("a", 1), ("b", 2), ("a", 3)])
    members = set(original)
    tagged_members: set[int | str] = {1}
    tagged_members.add('word')
    empty: list[int] = []
    empty_visits = 0
    for unused in ():
        empty_visits += 1
    else:
        empty_visits += 10
    ''',
    (
        ("independent constructor and stable sorting", "copied != [1, 1, 2, 3] or original != [3, 1, 2, 1]"),
        ("dictionary replacement preserves insertion order", 'list(mapping) != ["a", "b"] or mapping["a"] != 3'),
        ("mapping iterable uses keys", "sum({2: 10, 4: 20}) != 6"),
        ("mapping item/value views", 'sum(mapping.values()) != 5 or ("a", 3) not in mapping.items()'),
        ("set algebra", "members.union([3, 4]) != {1, 2, 3, 4} or members.intersection([2, 4]) != {2}"),
        ("set subset and disjointness", "not {1, 2}.issubset(members) or not members.isdisjoint([8])"),
        ("fresh empty comparison inherits item representation", "not {int8(1)}.isdisjoint([])"),
        ("reverse ordering", "sorted(range(4), reverse=True) != [3, 2, 1, 0]"),
        ("empty extrema defaults", "min(empty, default=7) != 7 or max(empty, default=-7) != -7"),
        ("reductions", "sum(original, 5) != 12 or max(original) != 3 or min(original) != 1"),
        ("truth reductions", "any(empty) or not all(empty) or not any([0, 2]) or all([2, 0])"),
        ("empty tuple shape survives comparison context", "() != () or (1,) == () or ().count(1) != 0"),
        ("empty tuple iteration and truth reductions", "empty_visits != 10 or any(()) or not all(())"),
        ("list versus tuple equality", "[1] == (1,) or not ([1] != (1,)) or (1,) == [1]"),
        ("set versus list equality", "{1} == [1] or not ({1} != [1]) or [1] == {1}"),
        ("different mapping and sequence kinds", "[1] == {1: 2} or {1} == {1: 2} or {1} == (1,)"),
        ("same-kind equality controls", "[1] != [1] or {1} != {1} or [1] == [2] or {1} == {2}"),
        ("declared set literal layout", "len(tagged_members) != 2 or 1 not in tagged_members or 'word' not in tagged_members"),
    ),
)


# Each row tests the immediate parent and a sibling/child that must not catch it.
EXCEPTION_HIERARCHIES = (
    ("FloatingPointError", "ArithmeticError", "OverflowError"),
    ("NotImplementedError", "RuntimeError", "RecursionError"),
    ("ImportError", "Exception", "ModuleNotFoundError"),
    ("ModuleNotFoundError", "ImportError", "NameError"),
    ("SyntaxError", "Exception", "IndentationError"),
    ("IndentationError", "SyntaxError", "TabError"),
    ("TabError", "IndentationError", "NameError"),
    ("EOFError", "Exception", "OSError"),
    ("ReferenceError", "Exception", "RuntimeError"),
    ("SystemError", "Exception", "RuntimeError"),
    ("BlockingIOError", "OSError", "ChildProcessError"),
    ("ChildProcessError", "OSError", "BlockingIOError"),
    ("ConnectionError", "OSError", "BrokenPipeError"),
    ("BrokenPipeError", "ConnectionError", "ConnectionResetError"),
    ("ConnectionAbortedError", "ConnectionError", "ConnectionRefusedError"),
    ("ConnectionRefusedError", "ConnectionError", "ConnectionAbortedError"),
    ("ConnectionResetError", "ConnectionError", "BrokenPipeError"),
    ("FileExistsError", "OSError", "FileNotFoundError"),
    ("FileNotFoundError", "OSError", "FileExistsError"),
    ("InterruptedError", "OSError", "TimeoutError"),
    ("IsADirectoryError", "OSError", "NotADirectoryError"),
    ("NotADirectoryError", "OSError", "IsADirectoryError"),
    ("PermissionError", "OSError", "ProcessLookupError"),
    ("ProcessLookupError", "OSError", "PermissionError"),
    ("TimeoutError", "OSError", "InterruptedError"),
)


EXCEPTION_CONTROL_FLOW_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Holder:
        text: str | None
        def __init__(self) -> None:
            self.text = "old"
        def close(self) -> int:
            if self.text is None:
                return 0
            try:
                return len(self.text)
            finally:
                self.text = None
        def observe_cleanup(self, mode: int) -> str:
            if self.text is None:
                return "-"
            result = ""
            try:
                if mode == 1:
                    raise ValueError("clear")
                if mode == 0:
                    self.text = None
            except ValueError:
                self.text = None
            else:
                if mode == 2:
                    self.text = None
            finally:
                result = "N" if self.text is None else self.text
            return result
        def observe_else(self, clear: bool) -> str:
            if self.text is None:
                return "-"
            try:
                if clear:
                    self.text = None
            except ValueError:
                return "error"
            else:
                return "N" if self.text is None else self.text

    @js
    def cleanup(value: str | None, mode: int) -> str:
        if value is None:
            return "-"
        result = ""
        try:
            result = value.strip()
            if mode == 0:
                value = None
            if mode == 1:
                raise ValueError("clear")
        except ValueError:
            value = None
            result += "E"
        else:
            if mode == 2:
                value = None
        finally:
            result += "N" if value is None else "P"
            value = None
        return result + ("N" if value is None else value)

    @js
    def close_twice() -> int:
        value = Holder()
        return value.close() + value.close()

    @js
    def else_read(value: str | None, clear: bool) -> str:
        if value is None:
            return "-"
        try:
            result = value.upper()
            if clear:
                value = None
        except ValueError:
            return "error"
        else:
            return result + ("N" if value is None else value)
        finally:
            if value is None:
                value = "closed"
    ''',
    "exception_control_flow_contract",
    '''
    score = 0
    for value in range(3):
        try:
            if value == 1:
                raise ValueError("handled")
            score += value
        except ValueError as error:
            score += 5 if str(error) == "handled" else 100
        else:
            score += 10
        finally:
            score += 1
    try:
        try:
            raise TypeError("reraised")
        except TypeError:
            raise
    except Exception:
        score += 7
    ''',
    (
        ("handlers, else, finally, and reraising", "score != 37"),
        ("finally reads reflect body/handler/else writes", 'cleanup(" a ", 0) + cleanup(" b ", 1) + cleanup(" c ", 2) + cleanup(" d ", 3) + cleanup(None, 2) != "aNNbENNcNNdPN-"'),
        ("finally field reads reflect body/handler/else writes", 'Holder().observe_cleanup(0) + Holder().observe_cleanup(1) + Holder().observe_cleanup(2) + Holder().observe_cleanup(3) != "NNNold"'),
        ("return value is evaluated before field cleanup", 'close_twice() != 3'),
        ("else reads body writes and returns through finally", 'else_read("a", True) + else_read("b", False) + else_read(None, True) != "ANBb-"'),
        ("else field reads retain conditional body writes", 'Holder().observe_else(True) + Holder().observe_else(False) != "Nold"'),
    ),
)


EXCEPTION_VALUE_IDENTITY_CONTRACT = _contract(
    '''
from pyjs import js

@js
class Pending:
    def __init__(self, error: ValueError):
        self.error = error

@js
def make_error() -> ValueError:
    return ValueError("saved")
''',
    "exception_value_identity_contract",
    '''
    saved = make_error()
    pending = Pending(saved)
    errors = [pending.error]
    identical = True
    messages = ""
    for attempt in range(2):
        try:
            raise errors[0]
        except ValueError as caught:
            identical = identical and caught is saved
            messages += str(caught)
    ''',
    (
        ("retained identity across storage and repeated raises", "not identical"),
        ("retained message", 'messages != "savedsaved"'),
    ),
)


CUSTOM_EXCEPTION_CONTRACT = _contract(
    '''
from pyjs import js

@js
class InvalidRecord(ValueError):
    pass

@js
class InvalidTitle(InvalidRecord):
    pass

@js
def validate() -> None:
    raise InvalidTitle("title")
''',
    "custom_exception_contract",
    '''
    message = ""
    caught = False
    try:
        try:
            validate()
        except (TypeError, InvalidRecord) as error:
            caught = str(error) == "title"
            raise
    except ValueError as saved:
        message = str(saved)
    empty = "unhandled"
    try:
        raise InvalidRecord()
    except InvalidRecord as empty_error:
        empty = str(empty_error)
    ''',
    (
        ("custom inheritance, tuple matching, and reraising", 'not caught or message != "title"'),
        ("inherited empty constructor", 'empty != ""'),
    ),
)


EXCEPTION_OBJECT_CONTRACT = _contract(
    '''
from pyjs import js

@js
class RevisionConflict(Exception):
    def __init__(self, record: str, revision: int = 0):
        super().__init__(f"{record}:{revision}")
        self.record = record
        self.revision = revision

    def next_revision(self) -> int:
        return self.revision + 1

@js
class RetryConflict(RevisionConflict):
    pass

@js
def pending_conflict() -> RevisionConflict:
    return RetryConflict("record", revision=42)
''',
    "exception_object_contract",
    '''
    pending = pending_conflict()
    saved: list[RevisionConflict] = [pending]
    outcome = "unhandled"
    identity = False
    try:
        raise saved[0]
    except RevisionConflict as conflict:
        identity = conflict is pending
        outcome = str(conflict)
        conflict.revision = conflict.next_revision()
        try:
            raise
        except Exception as repeated:
            identity = identity and repeated is pending
    ''',
    (
        ("constructed message", 'outcome != "record:42"'),
        ("owned identity survives reraising", "not identity"),
        ("typed fields survive handler exit", 'pending.record != "record" or pending.revision != 43'),
        ("inherited initializer keeps dynamic class", "not isinstance(pending, RetryConflict)"),
    ),
)


EXCEPTION_CAUSE_CONTRACT = _contract(
    '''
from pyjs import js

@js
class StorageFailure(RuntimeError):
    pass

@js
def underlying_failure() -> ValueError:
    return ValueError("invalid record")
''',
    "exception_cause_contract",
    '''
    saved = StorageFailure("could not save")
    original = underlying_failure()
    identity = False
    cleanup = False
    try:
        try:
            raise saved from original
        finally:
            cleanup = True
    except RuntimeError as caught:
        identity = caught is saved and caught.__cause__ is original
        try:
            raise
        except Exception as repeated:
            identity = identity and repeated is saved and repeated.__cause__ is original
    suppressed = StorageFailure("hidden cause")
    try:
        raise suppressed from None
    except StorageFailure:
        pass
    ''',
    (
        ("cause and wrapper identities survive cleanup and reraise", "not identity or not cleanup"),
        ("explicit cause suppresses implicit context", "not saved.__suppress_context__"),
        ("from None explicitly suppresses context", "not suppressed.__suppress_context__"),
        ("from None has no cause", "suppressed.__cause__ is not None"),
    ),
)


SCALAR_EXCEPTION_MESSAGE_CONTRACT = _contract(
    '''
from pyjs import js

@js
def message_revision(events: list[int]) -> int:
    events.append(1)
    return 42
''',
    "scalar_exception_message_contract",
    '''
    events: list[int] = []
    integer_message = ""
    try:
        raise ValueError(message_revision(events))
    except ValueError as invalid:
        integer_message = str(invalid)
    key_message = ""
    try:
        raise KeyError(-42)
    except KeyError as missing:
        key_message = str(missing)
    true_message = ""
    try:
        raise RuntimeError(True)
    except RuntimeError as failed:
        true_message = str(failed)
    false_message = ""
    try:
        raise KeyError(False)
    except KeyError as false_key:
        false_message = str(false_key)
    assertion_message = ""
    assert True, message_revision(events)
    try:
        assert False, message_revision(events)
    except AssertionError as assertion:
        assertion_message = str(assertion)
    ''',
    (
        ("integer message", 'integer_message != "42"'),
        ("numeric keys are not quoted", 'key_message != "-42"'),
        ("Python boolean spelling", 'true_message != "True" or false_message != "False"'),
        ("lazy single evaluation", 'len(events) != 2 or assertion_message != integer_message'),
    ),
)


KEY_ERROR_CONTRACT = _contract(
    '''
from pyjs import js

''',
    "key_error_contract",
    '''
    missing = ""
    try:
        raise KeyError("note's title")
    except LookupError as key_error:
        missing = str(key_error)
    empty = "unhandled"
    try:
        raise KeyError()
    except KeyError as no_args:
        empty = str(no_args)
    empty_key = "unhandled"
    try:
        raise KeyError("")
    except KeyError as empty_arg:
        empty_key = str(empty_arg)
    absent = "unhandled"
    values = {"present": "value"}
    try:
        values["missing"]
    except KeyError as lookup:
        absent = str(lookup)
    ''',
    (
        ("KeyError quoting", 'missing != \'"note\\\'s title"\''),
        ("empty args and empty string differ", 'empty != "" or empty_key != "\'\'"'),
        ("missing dictionary key", 'absent != "\'missing\'"'),
    ),
)


EXCEPTION_CLEANUP_CONTRACT = _contract(
    '''
from pyjs import js

@js
def saved_return(events: list[int]) -> str:
    value = "saved"
    try:
        try:
            return value
        finally:
            value = "changed"
            events.append(1)
    finally:
        events.append(2)

@js
def replace_error(events: list[int]) -> None:
    try:
        try:
            raise ValueError("original")
        finally:
            events.append(3)
            raise TypeError("replacement")
    finally:
        events.append(4)
''',
    "exception_cleanup_contract",
    '''
    events: list[int] = []
    result = saved_return(events)
    try:
        replace_error(events)
    except TypeError as error:
        if str(error) == "replacement":
            events.append(5)
    for value in range(3):
        try:
            if value == 0:
                continue
            break
        finally:
            events.append(6 + value)
    sequence = 0
    for event in events:
        sequence = sequence * 10 + event
    ''',
    (
        ("return evaluated before cleanup", 'result != "saved"'),
        ("nested cleanup, replacement, break, and continue", "sequence != 1234567"),
    ),
)


RUNTIME_EXCEPTION_CONTRACT = _contract(
    "from pyjs import js",
    "runtime_exception_contract",
    '''
    score = 0
    values = [1]
    try:
        values[2]
    except IndexError:
        score += 1
    try:
        values[-2] = 3
    except LookupError:
        score += 2
    try:
        "note"[5]
    except IndexError:
        score += 4
    try:
        1 // 0
    except ZeroDivisionError:
        score += 8
    try:
        1 % 0
    except ArithmeticError:
        score += 16
    try:
        for value in range(0, 2, 0):
            score += value
    except ValueError:
        score += 32
    try:
        1 << -1
    except ValueError:
        score += 64
    try:
        int("not a number")
    except ValueError:
        score += 128
    ''',
    (("catchable Python runtime categories", "score != 255"),),
)


CONTEXT_MANAGER_CONTRACT = _contract(
    '''
from pyjs import js

@js
class Scope:
    def __init__(self, events: list[str], name: str, suppress: bool | None):
        self.events = events
        self.name = name
        self.suppress = suppress

    def __enter__(self) -> str:
        self.events.append("enter:" + self.name)
        return self.name

    def __exit__(self, kind: object, value: object, traceback: object) -> bool | None:
        self.events.append("exit:" + self.name)
        return self.suppress

@js
def leave(events: list[str]) -> str:
    with Scope(events, "outer", False), Scope(events, "inner", False) as value:
        return value

@js
def decision(result: bool | None, fail: bool) -> str:
    events: list[str] = []
    try:
        with Scope(events, "decision", result):
            if fail:
                raise ValueError("expected")
    except ValueError:
        return "raised"
    return "done"

@js
class OptionalScope:
    def __init__(self, value: bool | None, events: list[str]):
        self.value = value
        self.events = events

    def __enter__(self) -> bool | None:
        self.events.append("enter")
        return self.value

    def __exit__(self, kind: object, value: object, traceback: object) -> None:
        self.events.append("exit")

@js
def optional_entry(value: bool | None) -> str:
    events: list[str] = []
    with OptionalScope(value, events) as entered:
        if entered is None:
            events.append("none")
        elif entered:
            events.append("true")
        else:
            events.append("false")
    return "|".join(events)
''',
    "context_manager_contract",
    '''
    events: list[str] = []
    value = leave(events)
    with Scope(events, "suppress", True):
        raise ValueError("expected")
    ''',
    (("captured return", 'value != "inner"'),
     ("reverse cleanup and suppression", '"|".join(events) != "enter:outer|enter:inner|exit:inner|exit:outer|enter:suppress|exit:suppress"'),
     ("normal exit ignores nullable truth", 'decision(None, False) + decision(False, False) + decision(True, False) != "donedonedone"'),
     ("only true suppresses the active exception", 'decision(None, True) + decision(False, True) + decision(True, True) != "raisedraiseddone"'),
     ("nullable enter binds None", 'optional_entry(None) != "enter|none|exit"'),
     ("nullable enter binds false", 'optional_entry(False) != "enter|false|exit"'),
     ("nullable enter binds true", 'optional_entry(True) != "enter|true|exit"')),
)


SCALAR_NUMERIC_CONTRACT = _contract(
    "from pyjs import js",
    "scalar_numeric_contract",
    """
    left = divmod(-7, 3)
    right = divmod(7.5, -2.0)
    """,
    (
        ("signed integer divmod", "left[0] != -3 or left[1] != 2"),
        ("signed float divmod", "right[0] != -4.0 or right[1] != -0.5"),
        ("half-even rounding", "round(2.5) != 2 or round(3.5) != 4"),
        ("decimal rounding", "round(2.675, 2) != 2.67"),
        ("integer decimal rounding", "round(250, -2) != 200"),
        ("decimal integer parsing", "int(' -123 ') != -123"),
        ("float parsing", "float('12.50e+1') != 125.0"),
        ("float conversion truncates", "int(-3.75) != -3"),
    ),
)


BOOLEAN_NUMERIC_CONTRACT = _contract(
    "from pyjs import js",
    "boolean_numeric_contract",
    "",
    (
        ("Boolean addition widens", "True + True != 2 or False + True != 1"),
        ("Boolean subtraction is signed", "False - True != -1 or 2 - True != 1"),
        ("mixed multiplication", "True * 3 != 3 or 3 * False != 0"),
        ("mixed float arithmetic", "True - 1.5 != -0.5 or 1.5 + True != 2.5"),
        ("division", "True / True != 1.0 or True / 2 != 0.5"),
        ("floor and modulo", "True // -2 != -1 or True % -2 != -1"),
        ("Boolean bitwise", "not (True & True) or (False | False) or not (True ^ False)"),
        ("mixed integer bitwise", "True | 2 != 3 or 2 ^ True != 3 or True & 2 != 0"),
        ("shifts widen", "True << True != 2 or True >> True != 0"),
        ("ordering", "not (False < True) or not (True <= True) or True > 2"),
    ),
)


MODULAR_POWER_CONTRACT = _contract(
    "from pyjs import js, int8, uint8, int64\nfrom builtins import pow as power",
    "modular_power_contract",
    "",
    (("ordinary inverse", "power(3, -2, 11) != 5"),
     ("ordinary negative modulus", "power(2, 3, -5) != -2"),
     ("minimum exponent", "power(2, -9223372036854775808, 5) != 1"),
     ("minimum base", "power(-9223372036854775808, 3, 9223372036854775807) != 9223372036854775806"),
     ("represented arguments", "power(int8(2), int8(5), int8(7)) != int8(4)"),
     ("base result wrapping", "power(int8(2), 8, 257) + 128 != int8(-128)"),
     ("exponent result wrapping", "power(2, int8(8), 257) + 128 != int8(-128)"),
     ("unsigned result wrapping", "power(uint8(255), 2, 1024) + 255 != uint8(0)"),
     ("negative modulus result wrapping", "power(int8(127), 1, -257) + 2 != int8(-128)"),
     ("int64 modular multiplication", "power(int64(2), 63, 9223372036854775807) != int64(1)"),
     ("modulus does not own representation", "power(2, 8, int8(7)) + 127 != 131"),
     ("bool owns ordinary integer result", "power(True, int8(-1), 5) + 127 != 128")),
)


BINARY_POWER_CONTRACT = _contract(
    "from pyjs import js, int8, int64\nfrom builtins import pow as power",
    "binary_power_contract",
    "",
    (
        ("ordinary power", "power(3, 4) != 81 or power(-2, 3) != -8"),
        ("zero exponent", "power(0, 0) != 1"),
        ("narrow result wraps", "power(int8(4), 4) != int8(0)"),
        ("represented exponent", "power(2, int8(7)) != int8(-128)"),
        ("int64 result", "power(int64(2), 62) != int64(4611686018427387904)"),
        ("explicit None modulus", "power(int8(2), 1000, None) != int8(0)"),
    ),
)


RANGE_NUMERIC_LOOKUP_CONTRACT = _contract(
    "from pyjs import js",
    "range_numeric_lookup_contract",
    "values = range(-3, 6, 2)",
    (
        ("integral float membership", "1.0 not in values or 2.0 in values"),
        ("fractional float misses", "1.5 in values or values.count(1.5) != 0"),
        ("Boolean is still numeric", "True not in values or False in values"),
        ("float count", "values.count(1.0) != 1"),
        ("float index", "values.index(3.0) != 3"),
        ("reverse float lookup", "range(5, -4, -2).index(-1.0) != 3"),
    ),
)


REVERSED_PROTOCOL_CONTRACT = _contract(
    """
    from builtins import reversed as reverse
    from pyjs import js
    @js
    class Reversible:
        def __init__(self, value: int):
            self.value = value
            self.calls = 0
        def __reversed__(self) -> int:
            self.calls += 1
            return self.value
    """,
    "reversed_protocol",
    "value = Reversible(7)",
    (
        ("protocol may return a non-iterator", "reversed(value) != 7"),
        ("named builtin alias", "reverse(value) != 7"),
        ("static empty keyword expansion", "reverse(value, **{}) != 7"),
        ("exactly one method call per operation", "value.calls != 3"),
    ),
)


ASSERT_NARROWING_CONTRACT = _contract(
    """
    from pyjs import js, int8
    @js
    def present(value: int | None) -> int:
        assert value is not None
        return value + 1
    @js
    def negated(value: int | None) -> int:
        assert not (value is None)
        return value + 1
    @js
    def truthy(value: int | None) -> int:
        assert value
        return value + 1
    @js
    def both(left: int | None, right: int | None) -> int:
        assert left is not None and right is not None
        return left + right
    @js
    def checked(value: int | str) -> int:
        assert isinstance(value, int)
        return value + 1
    @js
    def excluded(value: int | str) -> int:
        assert not isinstance(value, str)
        return value + 1
    @js
    def narrow(value: int8 | None) -> int:
        assert value is not None
        return int(value + 1)
    """,
    "assert_narrowing",
    "",
    (
        ("None identity", "present(4) != 5"),
        ("negated identity", "negated(4) != 5"),
        ("truthiness", "truthy(4) != 5"),
        ("conjunction", "both(3, 4) != 7"),
        ("isinstance", "checked(4) != 5"),
        ("negative isinstance", "excluded(4) != 5"),
        ("portable layout projection", "narrow(int8(127)) != -128"),
    ),
)


ASSERT_CAPTURE_CONTRACT = _contract(
    """
    from collections.abc import Callable
    from pyjs import js, int8
    @js
    def closure(value: str | None) -> str:
        assert value is not None
        action: Callable[[], str] = lambda: value.upper() if value is not None else 'none'
        before = action()
        value = None
        return before + action()
    @js
    def generator(value: str | None) -> str:
        assert value
        action = (value.upper() if None is not value else 'none' for _ in range(2))
        before = next(action)
        value = None
        return before + next(action)
    @js
    def truthy(value: int8 | None) -> int:
        assert value is not None
        action: Callable[[], int] = lambda: int(value) if value else 7
        before = action()
        value = int8(0)
        zero = action()
        value = None
        return before + zero + action()
    @js
    def wider(value: int | str | None) -> str:
        assert value is not None
        action: Callable[[], int] = lambda: 1 if value else 0
        explicit: Callable[[], bool] = lambda: bool(value)
        negated: Callable[[], bool] = lambda: not value
        before = repr((action(), explicit(), negated()))
        value = None
        return before + repr((action(), explicit(), negated()))
    @js
    def mark(events: list[int]) -> str:
        events.append(1)
        return 'rhs'
    @js
    def boolean(value: str | None) -> str:
        assert value is not None
        events: list[int] = []
        both: Callable[[], str | None] = lambda: value and mark(events)
        either: Callable[[], str] = lambda: value or mark(events)
        before = repr((both(), either()))
        value = None
        return before + repr((both(), either(), len(events)))
    @js
    def classinfo(value: str | None) -> str:
        assert value is not None
        action: Callable[[], str] = lambda: value.upper() if isinstance(value, str) else 'none'
        source = (value.upper() if isinstance(value, (str, int)) else 'none' for _ in range(2))
        before = action() + next(source)
        value = None
        return before + action() + next(source)
    @js
    def evaluation() -> int:
        events: list[int] = []
        if not isinstance(mark(events), (str, int)):
            return -1
        present = bool(mark(events))
        if not present:
            return -2
        if (mark(events) and mark(events)) != 'rhs':
            return -3
        return len(events)
    """,
    "assert_capture",
    "",
    (
        ("closure rechecks captured optional storage", "closure('kept') != 'KEPTnone'"),
        ("generator rechecks between resumes", "generator('kept') != 'KEPTnone'"),
        ("truthiness checks absence and portable zero", "truthy(int8(3)) != 17"),
        ("wider union truth and explicit bool", "wider(3) != '(1, True, False)(0, False, True)'"),
        ("wider union false non-None value", "wider('') != '(0, False, True)(0, False, True)'"),
        ("and/or value selection and lazy RHS", "boolean('text') != \"('rhs', 'text')(None, 'rhs', 2)\""),
        ("and/or false non-None value", "boolean('') != \"('', 'rhs')(None, 'rhs', 2)\""),
        ("single and tuple classinfo in deferred bodies", "classinfo('kept') != 'KEPTKEPTnonenone'"),
        ("guard subjects evaluated once", "evaluation() != 4"),
    ),
)


ASSERT_BOOLEAN_FLOW_CONTRACT = _contract(
    """
    from collections.abc import Callable
    from pyjs import js, int8
    @js
    class Box:
        def __init__(self, value: int | None): self.value = value
    @js
    class Switch:
        def __init__(self, value: int): self.value = value
        def __bool__(self) -> bool: return self.value != 0
    @js
    def branch(value: int | None) -> int:
        if value is None:
            return -1
        return value and 5
    @js
    def field(box: Box) -> int:
        if box.value is None:
            return -1
        return box.value and box.value + 10
    @js
    def checked(value: int | str | None) -> str:
        assert isinstance(value, str)
        assert value is not None
        return (value and value.upper()) + (value or 'empty')
    @js
    def assigned() -> int:
        value: int8 | None = None
        value = int8(4)
        return int(value and int8(9))
    @js
    def objects(value: Switch | None, fallback: Switch) -> int:
        if value is None:
            return -1
        left: Switch = value or fallback
        right: Switch = value and fallback
        return left.value * 10 + right.value
    @js
    def nested(value: int | None) -> str:
        assert value is not None
        action: Callable[[], int] = lambda: (value and 9) if value is not None else -1
        scoped: Callable[[int | None], int] = lambda item: (item and 5) if item is not None else -1
        eager: list[int] = [value and 7 for _ in range(2)]
        source = ((value and 11) if value is not None else -1 for _ in range(value and 2))
        first = repr((action(), next(source), scoped(3), eager))
        value = None
        return first + repr((action(), next(source), scoped(None)))
    """,
    "assert_boolean_flow",
    "",
    (
        ("immediate branch refinement", "branch(None) != -1 or branch(0) != 0 or branch(3) != 5"),
        ("immediate field refinement", "field(Box(None)) != -1 or field(Box(0)) != 0 or field(Box(4)) != 14"),
        ("successive assertions preserve subset", "checked('') != 'empty' or checked('ab') != 'ABab'"),
        ("assignment and portable representation", "assigned() != 9"),
        ("application truth protocol and result types", "objects(Switch(0), Switch(2)) != 20 or objects(Switch(5), Switch(2)) != 52"),
        ("fresh deferred proofs and eager comprehension scopes", "nested(3) != '(9, 11, 5, [7, 7])(-1, -1, -1)'"),
    ),
)


ASSERT_FAILURE_CONTRACT = _contract(
    """
    from pyjs import js
    @js
    def one_of(value: int | str | None) -> int:
        assert isinstance(value, (int, str))
        if isinstance(value, int):
            return value + 1
        return len(value)
    @js
    def detail(events: list[int]) -> str:
        events.append(1)
        return "invalid"
    @js
    def checked(value: int | str | None, events: list[int]) -> int:
        assert value is not None, detail(events)
        assert isinstance(value, int), detail(events)
        return value + 1
    @js
    def exercise() -> str:
        events: list[int] = []
        results: list[str] = []
        for value in [None, "wrong", 4]:
            try:
                results.append(str(checked(value, events)))
            except AssertionError as error:
                results.append(str(error))
        return repr((results, events))
    """,
    "assert_failure",
    "",
    (
        ("runtime checks and lazy messages", "exercise() != \"(['invalid', 'invalid', '5'], [1, 1])\""),
        ("tuple classinfo", "one_of('kept') != 4 or one_of(4) != 5"),
    ),
)


APPLICATION_ROUNDING_CONTRACT = _contract(
    """
    from pyjs import js
    @js
    class Rounded:
        def __init__(self, value: int):
            self.value = value
        def __round__(self, ndigits: int = 7) -> int:
            return self.value + ndigits
    @js
    class Shifted(Rounded):
        def __round__(self, ndigits: int = 7) -> int:
            return super().__round__(ndigits) + 2
    @js
    def rounded(value: Rounded) -> int:
        return round(value, 3)
    """,
    "application_rounding",
    "value = Rounded(10)",
    (
        ("omitted digits use method default", "round(value) != 17"),
        ("explicit None also uses method default", "round(value, None) != 17"),
        ("non-None digits forwarded", "round(value, 2) != 12"),
        ("subclass override dispatched", "rounded(Shifted(10)) != 15"),
    ),
)


REPRESENTED_ROUNDING_CONTRACT = _contract(
    "from pyjs import int64, js",
    "represented_rounding",
    "",
    (
        ("positive rounding wraps", "round(int64(9223372036854775807), -1) != int64(-9223372036854775806)"),
        ("negative rounding wraps", "round(int64(-9223372036854775808), -1) != int64(9223372036854775806)"),
        ("positive decimal overflow wraps", "round(int64(9223372036854775807), -19) != int64(-8446744073709551616)"),
        ("negative decimal overflow wraps", "round(int64(-9223372036854775808), -19) != int64(8446744073709551616)"),
    ),
)


EMPTY_LITERAL_SUM_CONTRACT = _contract(
    '''
    from pyjs import js, int8, int64, float32
    @js
    def start(events: list[int]) -> int8:
        events.append(1)
        return int8(7)
    ''',
    "empty_literal_sum_contract",
    '''
    small = sum([], int8(120))
    wide = sum((), start=int64(1152921504606846976))
    floating = sum([], float32(1.25))
    events: list[int] = []
    effectful = sum([], start(events))
    ''',
    (
        ("ordinary start", "sum([]) != 0 or sum([], 5) != 5 or sum([], start=0.5) != 0.5"),
        ("boolean start identity", "sum((), start=True) is not True"),
        ("narrow integer width", "small + int8(8) != int8(-128)"),
        ("wide integer precision", "wide + int64(1) != int64(1152921504606846977)"),
        ("float width", "floating + float32(0.5) != float32(1.75)"),
        ("start evaluated once", "effectful != int8(7) or events != [1]"),
    ),
)


INTEGER_LIST_MEMBERSHIP_CONTRACT = _contract(
    "from pyjs import js",
    "integer_list_membership_contract",
    '''
    values = [-12, 0, 42, 999]
    empty: list[int] = []
    flags = [False]
    ''',
    (
        ("values across the list", "-12 not in values or 999 not in values"),
        ("missing items and empty lists", "7 in values or 0 in empty"),
        ("boolean storage", "False not in flags or True in flags"),
        ("explicit method", "not values.__contains__(42)"),
    ),
)


STRING_DICTIONARY_MEMBERSHIP_CONTRACT = _contract(
    "from pyjs import js",
    "string_dictionary_membership_contract",
    '''
    values: dict[str, str] = {"present": "", "other": "value"}
    empty: dict[str, str] = {}
    ''',
    (
        ("empty values still have keys", '"present" not in values'),
        ("membership inspects keys, not values", '"value" in values'),
        ("empty dictionaries", '"present" in empty'),
        ("explicit method", 'not values.__contains__("other")'),
    ),
)


MEMBERSHIP_ORDER_CONTRACT = _contract(
    """
    from pyjs import int64, js

    @js
    def needle(events: list[int]) -> str:
        events.append(1)
        return "key"

    @js
    def text(events: list[int]) -> str:
        events.append(2)
        return "some key here"

    @js
    def mapping(events: list[int]) -> dict[str, str]:
        events.append(3)
        return {"key": "value"}

    @js
    def values(events: list[int]) -> list[str]:
        events.append(4)
        return ["key"]

    @js
    def number(events: list[int], value: int) -> int:
        events.append(value)
        return value

    @js
    def wide(events: list[int], value: int) -> int64:
        events.append(value)
        return int64(7)
    """,
    "membership_order_contract",
    """
    events: list[int] = []
    found_text = needle(events) in text(events)
    missing = needle(events) not in mapping(events)
    explicit = text(events).__contains__(needle(events))
    found_list = needle(events) in values(events)
    found_tuple = needle(events) in tuple(values(events))
    found_view = needle(events) in mapping(events).keys()
    found_range = number(events, 1) in range(number(events, 3))
    mixed_events: list[int] = []
    wide_needle = wide(mixed_events, 1) in [number(mixed_events, 7)]
    plain_needle = number(mixed_events, 7) in [wide(mixed_events, 2)]
    mixed_missing = wide(mixed_events, 3) not in {number(mixed_events, 4): 1}
    """,
    (
        ("membership results", "not found_text or missing or not explicit"),
        ("syntax evaluates needle first", "events[0] != 1 or events[1] != 2 or events[2] != 1 or events[3] != 3"),
        ("explicit method evaluates receiver first", "events[4] != 2 or events[5] != 1"),
        ("helper membership results", "not found_list or not found_tuple or not found_view or not found_range"),
        ("helper membership evaluates needle first", "events[6:] != [1, 4, 1, 4, 1, 3, 1, 3]"),
        ("mixed-representation results", "not wide_needle or not plain_needle or not mixed_missing"),
        ("coercion preserves needle-first order", "mixed_events != [1, 7, 7, 2, 3, 4]"),
    ),
)


INHERITED_FACTORY_FIELD_CONTRACT = _contract(
    '''
from pyjs import js

@js
class Parent:
    def __init__(self, count: int):
        self.count = count

@js
class Child(Parent):
    pass

@js
def make() -> Child:
    return Child(2)
''',
    "inherited_factory_field_contract",
    '''
    value = make()
    value.count = 42
    ''',
    (("inherited initializer owns factory-result field", "value.count != 42"),),
)


INHERITED_FIELD_ASSIGNMENT_CONTRACT = _contract(
    """
    from pyjs import js
    @js
    class Box:
        def __init__(self, value: int):
            self.value = value
    @js
    class Parent:
        def __init__(self):
            self.saved: Box | None = None
        def reset(self):
            self.saved = None
        def read(self) -> int:
            saved = self.saved
            if isinstance(saved, Box):
                return saved.value
            return -1
    @js
    class Child(Parent):
        def put(self, value: Box):
            self.saved = value
    @js
    class Grandchild(Child):
        def clear(self):
            self.saved = None
    @js
    def replace(parent: Parent, value: Box):
        parent.saved = value
    """,
    "inherited_field_assignment",
    """
    child = Grandchild()
    alias: Parent = child
    original = child.read()
    child.put(Box(7))
    from_parent = alias.read()
    child.reset()
    reset = child.read()
    replace(alias, Box(9))
    from_child = child.read()
    child.clear()
    """,
    (("initial inherited optional field", "original != -1"),
     ("subclass write visible through parent", "from_parent != 7"),
     ("parent reset visible through subclass", "reset != -1"),
     ("parent alias writes use same storage", "from_child != 9"),
     ("grandchild clears inherited optional field", "alias.read() != -1")),
)


CLASS_DECLARED_FIELD_ASSIGNMENT_CONTRACT = _contract(
    """
    from pyjs import js, int8
    @js
    class Box:
        def __init__(self, value: int):
            self.value = value
    @js
    class Parent:
        saved: Box | None
        count: int8
        rows: list[list[int8]]
        def __init__(self):
            self.saved = None
            self.count = int8(0)
            self.rows = []
        def reset(self):
            self.saved = None
            self.rows = []
    @js
    class Child(Parent):
        def put(self):
            self.saved = Box(7)
            self.count = int8(127)
            self.rows = [[int8(7)]]
    @js
    class Grandchild(Child):
        def clear(self):
            self.saved = None
    """,
    "class_declared_field_assignment",
    """
    child = Grandchild()
    alias: Parent = child
    child.put()
    first = alias.saved
    count = alias.count
    row = alias.rows[0][0]
    alias.reset()
    empty = child.saved is None and len(child.rows) == 0
    alias.saved = Box(9)
    alias.count = int8(-128)
    last = child.saved
    child.clear()
    """,
    (("subclass writes keep optional object storage", "first is None or first.value != 7"),
     ("subclass writes preserve fixed-width fields", "count != int8(127)"),
     ("fresh nested literals use the declared representation", "row != int8(7)"),
     ("parent reset visible through subclass", "not empty"),
     ("parent alias writes use the original slots", "last is None or last.value != 9 or child.count != int8(-128)"),
     ("grandchild clears the shared optional field", "alias.saved is not None")),
)


UNPACK_FIELD_CONTRACT = _contract(
    '''
    from pyjs import js
    @js
    class Row:
        def __init__(self):
            self.left = -1
            self.right = -1
    @js
    def owner(row: Row, values: list[int]) -> Row:
        values[1] = 99
        return row
    ''',
    "unpack_fields",
    '''
    row = Row()
    values = [1, 2]
    owner(row, values).left, row.right = values
    first = row.left
    second = row.right
    fresh, (row.left, row.right) = (3, (4, 5))
    ''',
    (("capture before receiver mutation", "first != 1 or second != 2"),
     ("mixed new local and nested fields", "fresh != 3 or row.left != 4 or row.right != 5")),
)


FIELD_ASSIGNMENT_CONTRACT = _contract(
    """
    from pyjs import js

    @js
    class Row:
        def __init__(self, count: int):
            self.count = count

        def initialize(self):
            self.count = self.count + 1

    @js
    def make_row(count: int) -> Row:
        return Row(count)

    @js
    def target(rows: list[Row], events: list[int]) -> Row:
        events.append(2)
        return rows[2]

    @js
    def replacement(events: list[int]) -> int:
        events.append(1)
        return 8

    @js
    def select_index(events: list[int], state: list[int]) -> int:
        events.append(2)
        return state[0]

    @js
    def bump(events: list[int], state: list[int]) -> int:
        events.append(1)
        state[0] = 1
        return 3
    """,
    "field_assignment_result",
    """
    rows: list[Row] = []
    for index in [0, 1, 2]:
        rows.append(make_row(index))
    rows[2].initialize()
    initialized_count = rows[2].count
    rows[0].count = 5
    alias = rows[0]
    groups = [[rows[1]], [rows[2]]]
    groups[0][0].count = 6
    events: list[int] = []
    target(rows, events).count = replacement(events)
    target(rows, events).count: int = replacement(events)
    augmented_events: list[int] = []
    state = [0]
    rows[select_index(augmented_events, state)].count += bump(augmented_events, state)
    items = [0]
    item_events: list[int] = []
    state[0] = 0
    items[select_index(item_events, state)] = replacement(item_events)
    chained_events: list[int] = []
    chained = target(rows, chained_events).count = replacement(chained_events)
    chained_rows = [Row(0), Row(0)]
    chained_rows[0].count = chained_rows[chained_rows[0].count].count = 1
    augmented_items = [5]
    augmented_item_events: list[int] = []
    state[0] = 0
    augmented_items[select_index(augmented_item_events, state)] += bump(augmented_item_events, state)
    constructed_count = Row(12).count
    conditional = Row(0)
    (conditional if state[0] == 1 else rows[0]).count = 13
    conditional_count = (conditional if state[0] == 1 else rows[0]).count
    """,
    (
        ("initialize reads fields declared by the constructor", "initialized_count != 3"),
        ("indexed factory result waits for constructor fields", "rows[0].count != 8"),
        ("assignment mutates the existing object", "alias.count != 8"),
        ("nested indexing preserves the assignment receiver", "rows[1].count != 6"),
        ("function-call receivers accept field writes", "rows[2].count != 8"),
        ("assignment operands run exactly once", "len(events) != 4"),
        ("RHS runs before target", "events[0] != 1"),
        ("target runs after RHS", "events[1] != 2"),
        ("annotated RHS runs before target", "events[2] != 1"),
        ("annotated target runs after RHS", "events[3] != 2"),
        ("augmented assignment evaluates each operand once", "len(augmented_events) != 2"),
        ("augmented receiver runs before RHS", "augmented_events[0] != 2"),
        ("augmented RHS runs after receiver", "augmented_events[1] != 1"),
        ("item assignment stores the replacement", "items[0] != 8"),
        ("item assignment evaluates each operand once", "len(item_events) != 2"),
        ("item assignment RHS runs before index", "item_events[0] != 1"),
        ("item assignment index runs after RHS", "item_events[1] != 2"),
        ("chained assignment stores the same RHS", "chained != 8"),
        ("chained assignment evaluates RHS once", "len(chained_events) != 2"),
        ("chained assignment RHS precedes receivers", "chained_events[0] != 1"),
        ("chained assignment resolves the attribute", "chained_events[1] != 2"),
        ("chained targets store left-to-right", "chained_rows[1].count != 1"),
        ("augmented item writes to captured index", "augmented_items[0] != 8"),
        ("augmented item evaluates each operand once", "len(augmented_item_events) != 2"),
        ("augmented item index precedes RHS", "augmented_item_events[0] != 2"),
        ("augmented item RHS follows index", "augmented_item_events[1] != 1"),
        ("constructor result exposes its instance fields", "constructed_count != 12"),
        ("conditional receiver keeps the selected instance", "conditional_count != 13 or conditional.count != 13"),
    ),
)


# Valid Python, but not a supported compiled layout/dispatch contract yet.
# Keep constructor and base-typed effects visible: concrete-only calls can
# accidentally hide a compiler treating the inherited field as a plain slot.
PROPERTY_FIELD_OVERRIDE_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Base:
        def __init__(self):
            self.events: list[str] = []
            self.value: str | None = None

    @js
    class Child(Base):
        def __init__(self):
            super().__init__()
            self.stored = "initial"
        @property
        def value(self) -> str:
            return self.stored + "!"
        @value.setter
        def value(self, item: str | None) -> None:
            self.events.append("setter")
            self.stored = "empty" if item is None else item

    @js
    def read(child: Child) -> str:
        return child.value

    @js
    def read_base(item: Base) -> str:
        value = item.value
        return "None" if value is None else value

    @js
    def write_base(item: Base) -> None:
        item.value = "base"
    ''',
    "property_field_override_result",
    '''
    base = Base()
    child = Child()
    initialized = len(child.events)
    first = read(child)
    inherited = read_base(child)
    write_base(child)
    written = read_base(child)
    child.value = None
    cleared = read(child)
    child.value = "updated"
    ''',
    (
        ("base field retains its nullable contract", "base.value is not None"),
        ("base initializer invokes the subclass setter", "initialized != 1"),
        ("subclass getter overrides inherited field metadata", "first != 'initial!'"),
        ("base-typed read invokes the subclass getter", "inherited != 'initial!'"),
        ("base-typed write invokes the subclass setter", "written != 'base!'"),
        ("setter accepts its wider input contract", "cleared != 'empty!'"),
        ("subclass getter and setter both execute", "read(child) != 'updated!' or len(child.events) != 4"),
    ),
)


LITERAL_FIELD_ASSIGNMENT_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Holder:
        def __init__(self):
            self.items: list[int | str] = []
            self.members: set[int | str] = {0}
            self.groups: dict[str, list[int | str]] = {}
            self.setters = 0
        @property
        def values(self) -> list[int | str]:
            return self.items
        @values.setter
        def values(self, value: list[int | str]):
            self.setters += 1
            self.items = value

    @js
    def receiver(holder: Holder, events: list[int]) -> Holder:
        events.append(2)
        return holder

    @js
    def item(events: list[int]) -> int:
        events.append(1)
        return 3
    ''',
    "literal_field_assignment_result",
    '''
    holder = Holder()
    events: list[int] = []
    receiver(holder, events).items = [item(events)]
    first = holder.items
    receiver(holder, events).members = {item(events)}
    receiver(holder, events).groups = {'row': [item(events)]}
    receiver(holder, events).values = [item(events)]
    holder.items.append('item')
    holder.members.add('member')
    holder.groups['row'].append('group')
    ''',
    (
        ("literal field operands execute RHS first exactly once", "events != [1, 2, 1, 2, 1, 2, 1, 2]"),
        ("field replacement preserves the prior allocation", "len(first) != 1 or first[0] != 3"),
        ("setter gets destination-typed storage once", "holder.setters != 1 or holder.items != [3, 'item']"),
        ("set literals use the destination item type", "len(holder.members) != 2 or 3 not in holder.members or 'member' not in holder.members"),
        ("nested literals retain destination item types", "holder.groups['row'] != [3, 'group']"),
    ),
)


MAPPING_ASSIGNMENT_CONTRACT = _contract(
    """
    from pyjs import js

    @js
    def key(events: list[int]) -> str:
        events.append(2)
        return "value"

    @js
    def replacement(events: list[int]) -> str:
        events.append(1)
        return "8"

    @js
    def receiver(groups: list[list[int]], events: list[int]) -> list[int]:
        events.append(2)
        return groups[0]

    @js
    def swap(groups: list[list[int]], events: list[int]) -> int:
        events.append(1)
        groups[0] = [5]
        return 9
    """,
    "mapping_assignment_result",
    """
    mapping = {"value": "0"}
    events: list[int] = []
    mapping[key(events)] = replacement(events)
    mapping.__setitem__(key(events), replacement(events))
    mapping[key(events)] += replacement(events)
    groups = [[0]]
    original = groups[0]
    receiver_events: list[int] = []
    receiver(groups, receiver_events)[0] = swap(groups, receiver_events)
    augmented_groups = [[0]]
    augmented_original = augmented_groups[0]
    augmented_events: list[int] = []
    receiver(augmented_groups, augmented_events)[0] += swap(augmented_groups, augmented_events)
    """,
    (
        ("mapping augmented write preserves concatenation", 'mapping["value"] != "88"'),
        ("mapping operands run once", "len(events) != 6"),
        ("mapping RHS runs before key", "events[0] != 1"),
        ("mapping key runs after RHS", "events[1] != 2"),
        ("explicit setitem key runs before value", "events[2] != 2"),
        ("explicit setitem value runs after key", "events[3] != 1"),
        ("augmented mapping key runs before RHS", "events[4] != 2"),
        ("augmented mapping RHS runs after key", "events[5] != 1"),
        ("item receiver resolves after RHS mutation", "groups[0][0] != 9"),
        ("item write does not use the original receiver", "original[0] != 0"),
        ("item receiver and RHS each run once", "len(receiver_events) != 2"),
        ("item RHS precedes receiver", "receiver_events[0] != 1"),
        ("item receiver follows RHS", "receiver_events[1] != 2"),
        ("augmented item retains original receiver", "augmented_original[0] != 9"),
        ("augmented item does not overwrite replacement", "augmented_groups[0][0] != 5"),
        ("augmented receiver and RHS each run once", "len(augmented_events) != 2"),
        ("augmented receiver precedes RHS", "augmented_events[0] != 2"),
        ("augmented RHS follows receiver", "augmented_events[1] != 1"),
    ),
)


UNICODE_TEXT_CONTRACT = _contract(
    "from pyjs import js",
    "unicode_text_result",
    'value = "é😀é\\0"',
    (
        ("length counts code points, not bytes or UTF-16 units", "len(value) != 4"),
        ("membership finds supplementary characters", '"😀" not in value'),
        ("prefix uses complete Unicode text", 'not value.startswith("é😀")'),
        ("suffix preserves embedded NUL", 'not value.endswith("é\\0")'),
        ("empty prefix matches", 'not value.startswith("")'),
        ("concatenation preserves equality", 'value != "é" + "😀é\\0"'),
        ("Unicode lowercase", '"ÉΣΑ".lower() != "éσα"'),
    ),
)


UNICODE_CHARACTER_CONTRACT = _contract(
    "from pyjs import js",
    "unicode_character_result",
    "",
    (
        ("chr constructs complete code points", 'chr(0) + chr(233) + chr(128512) != "\\0é😀"'),
        ("ord reverses chr at the Unicode limit", 'ord(chr(0x10ffff)) != 0x10ffff'),
    ),
)


TEXT_EDIT_CONTRACT = _contract(
    "from pyjs import js",
    "text_edit_result",
    'value = "é😀é\\0z"',
    (
        ("Unicode scalar index", 'value[1] != "😀"'),
        ("reverse slices preserve code points", 'value[::-1] != "z\\0́e😀é"'),
        ("slice bounds clip", 'value[-99:99:2] != "ée\\0"'),
        ("empty search rejects an oversized start", 'value.find("", 99) != -1'),
        ("bounded search returns original character index", 'value.find("e", 1, 4) != 2'),
        ("empty count uses code points", 'value.count("", 1, 3) != 3'),
        ("strip recognizes Unicode whitespace", '"\\u3000é\\x85".strip() != "é"'),
        ("explicit strip characters", '"ééabcé".strip("é") != "abc"'),
        ("replacement inserts between characters", '"é😀".replace("", "x", 2) != "xéx😀"'),
        ("repeat preserves complete UTF-8", '3 * "é" != "ééé"'),
        ("joining an empty literal", '"é😀".join([]) != ""'),
        ("join split results", '"|".join("a::b::".split("::")) != "a|b|"'),
        ("reverse split chooses last match", '"|".join("aaa".rsplit("aa")) != "a|"'),
        ("limited whitespace split preserves trailing space", '"|".join(" a  b ".split(None, 1)) != "a|b "'),
        ("boolean equality", '(True == False) or (True != True)'),
        ("partition returns the first separator", '"a::b::c".partition("::")[2] != "b::c"'),
        ("missing reverse partition keeps the original last", '"abc".rpartition(":")[2] != "abc"'),
        ("empty suffix removal preserves text", '"é😀".removesuffix("") != "é😀"'),
        ("splitlines recognizes Unicode boundaries", '"|".join("a\\r\\nb\\u2028".splitlines()) != "a|b"'),
        ("zfill places zeros after a sign", '"-12".zfill(5) != "-0012"'),
    ),
)


COLLECTION_EDIT_CONTRACT = _contract(
    "from pyjs import js, int8",
    "collection_edit_result",
    '''
        values = [1, 2, 3]
        values.extend(values)
        values.insert(-99, 9)
        last = values.pop()
        popped_value = [int8(127)].pop()
        popped_row = [[int8(127)]].pop()
        copied = values.copy()
        copied.reverse()
        selected = values[::-2]
        values[1:3] = [7, 8, 9]
        del values[::2]
        repeated = copied * 2
        mapping = {"a": 1, "b": 2}
        removed = mapping.pop("a")
        missing = mapping.pop("missing", 99)
        old = mapping.setdefault("b", 88)
        added = mapping.setdefault("c", 3)
        other = mapping.copy()
        other.update({"b": 20, "d": 4})
        del other["c"]
        items = {1, 2, 3}
        items.discard(99)
        items.remove(2)
        more = items.copy()
        more.update({3, 4})
        words = ["é", "😀", "é", "end"]
        first = words.index("é", 1)
        total = words.count("é")
        words.remove("é")
    ''',
    (
        ("self-extension snapshots its input", "last != 3 or len(copied) != 6"),
        ("list pop retains int8", "popped_value + 1 != -128"),
        ("list pop retains nested int8", "popped_row[0] + 1 != -128"),
        ("copy and reverse preserve source", "copied[0] != 2 or copied[-1] != 9"),
        ("reverse extended slice", "len(selected) != 3 or selected[1] != 3"),
        ("slice replacement and deletion", "len(values) != 3 or values[0] != 7 or values[2] != 1"),
        ("list repetition creates complete copies", "len(repeated) != 12 or repeated[6] != 2"),
        ("pop and setdefault", "removed != 1 or missing != 99 or old != 2 or added != 3"),
        ("mapping copies own their backing arrays", 'mapping["b"] != 2 or other["b"] != 20 or "c" in other'),
        ("set mutation and copying", "len(items) != 2 or 2 in items or len(more) != 3 or 4 not in more"),
        ("list search and first-match removal", 'first != 2 or total != 2 or words[0] != "😀" or "end" not in words'),
    ),
)


PORTABLE_STORAGE_CHECKS = (
    ("annotation-only fields preserve representation", "deferred.value != -128"),
    ("augmented field assignment reads before storing", "counter.value != 2"),
    ("uint16 reassignment and return preserve storage", "returned_unsigned(uint16(65535)) != 65535"),
    ("int16 construction wraps above the maximum", "values[0] != -32768"),
    ("negative int16 construction is preserved", "values[1] != -3"),
    ("ordinary int16 construction is preserved", "values[2] != 5"),
    ("StaticArray length is preserved", "len(values) != 3"),
    ("int8 addition wraps", "int8(127) + 1 != -128"),
    ("uint16 construction wraps negative values", "uint16(-1) != 65535"),
    (
        "int64 addition wraps",
        "int64(9223372036854775807) + 1 != -9223372036854775808",
    ),
    ("conditional expressions retain int8", "selected + 1 != -128"),
    (
        "StaticArray iteration retains int8",
        "iterated_byte(narrow) != -128",
    ),
    ("float32 arithmetic rounds", "rounded != 16777216.0"),
    ("nested StaticArray writes are visible", "nested[0][0] != 1"),
    ("negative nested indexes are normalized", "nested[0][1] != 2"),
    (
        "inferred scalar returns retain int8",
        "inferred_byte(int8(127)) + 1 != -128",
    ),
    (
        "inferred StaticArray returns retain their layout",
        "inferred_values[0] + 1 != -128",
    ),
    ("list items retain int8", "dynamic_values[0] + 1 != -128"),
    ("parameter rebinding retains declared list representation", "rebound_items(dynamic_values, dynamic_values)[0] != -128"),
    ("explicit conversion permits ordinary storage", "ordinary_storage(0, [0]) != 600"),
    (
        "nested list items retain int8",
        "nested_dynamic_values[0][0] + 1 != -128",
    ),
    (
        "compound StaticArray items retain int8",
        "compound[0][0] + 1 != -128",
    ),
    (
        "compound StaticArray writes normalize int8",
        "changed_compound[0][0] + 2 != -128",
    ),
    (
        "StaticArray retains int64 items",
        "wide_values[0] + wide_values[1] != -9223372036854775808",
    ),
    (
        "StaticArray retains uint32 items",
        "unsigned_values[0] + unsigned_values[1] != 0",
    ),
    (
        "StaticArray retains float32 items",
        "float_values[0] + float_values[1] != 16777216.0",
    ),
    (
        "StaticArray retains float64 items",
        "double_values[0] + double_values[1] != 16777217.0",
    ),
)

PORTABLE_STORAGE = _contract(
    """
    from pyjs import StaticArray, float32, float64, int8, int16, int64, js
    from pyjs import uint16, uint32


    @js
    class Counter:
        def __init__(self):
            self.value = int8(127)

        def advance(self, positive: bool):
            self.value += int8(1) if positive else int8(-1)


    @js
    class Deferred:
        value: int8

        def populate(self):
            self.value = int8(127)
            self.value += int8(1)


    @js
    def returned_unsigned(value: uint16) -> uint16:
        if value > 0:
            value = value | uint16(0)
        return value


    @js
    def inferred_byte(value: int8):
        return value


    @js
    def rebound_items(values: list[int8], replacement: list[int8]) -> list[int8]:
        values = []
        values.append(int8(127))
        replacement = []
        replacement.append(values[0] + int8(1))
        return replacement


    @js
    def ordinary_storage(value: int, values: list[int]) -> int:
        value = int(int8(100))
        values = [int(int8(100))]
        local: int = int(int8(100))
        local = int(int8(100))
        return value + 100 + values[0] + 100 + local + 100


    @js
    def inferred_array(value: StaticArray[int8, 1]):
        return value


    @js
    def iterated_byte(values: StaticArray[int8, 1]) -> int8:
        for value in values:
            return value + 127
        return int8(0)
    """,
    "portable_storage_result",
    """
    values = StaticArray[int16, 3]([32768, -3, 5])
    counter = Counter()
    deferred = Deferred()
    deferred.populate()
    counter.advance(True)
    counter.value += int8(-126)
    selected = int8(127) if values[2] > 0 else int8(0)
    narrow = StaticArray[int8, 1]([1])
    rounded = float32(16777216.0) + float32(1.0)
    nested = StaticArray[StaticArray[int8, 2], 1]([[127, 0]])
    nested[0][0] = 1
    nested[0][-1] = 2
    inferred_values = inferred_array(StaticArray[int8, 1]([127]))
    dynamic_values: list[int8] = [int8(127)]
    nested_dynamic_values: list[list[int8]] = [[int8(127)]]
    compound = StaticArray[list[int8], 1]([[int8(127)]])
    changed_compound = StaticArray[list[int8], 1]([[int8(0)]])
    changed_compound[0][0] = int8(126)
    wide_values = StaticArray[int64, 2]([9223372036854775807, 1])
    unsigned_values = StaticArray[uint32, 2]([4294967295, 1])
    float_values = StaticArray[float32, 2]([16777216.0, 0.0])
    float_values[1] = 1.0
    double_values = StaticArray[float64, 2]([16777216.0, 0.0])
    double_values[1] = 1.0
    """,
    PORTABLE_STORAGE_CHECKS,
)


PORTABLE_FLOAT_CHECKS = (
    ("float32 rounds every operation", "rounded != 16777216.0"),
    (
        "float32 overflow produces infinity",
        "not overflow > float32(1e30)",
    ),
    (
        "float32 infinity subtraction produces NaN",
        "invalid == invalid",
    ),
    (
        "float32 underflow rounds below the smallest subnormal",
        "float32(1e-46) != 0.0",
    ),
    (
        "float32 preserves its smallest subnormal range",
        "not float32(1e-45) > 0.0",
    ),
    (
        "float32 addition is supported",
        "float32(1.5) + float32(2.25) != 3.75",
    ),
    (
        "float32 subtraction is supported",
        "float32(4.5) - float32(1.25) != 3.25",
    ),
    (
        "float32 multiplication is supported",
        "float32(1.5) * float32(2.0) != 3.0",
    ),
    (
        "float32 true division is supported",
        "float32(7.5) / float32(2.5) != 3.0",
    ),
    (
        "float32 accepts an ordinary right operand",
        "float32(2.0) + 1.5 != 3.5",
    ),
    (
        "float32 accepts an ordinary left operand",
        "1.5 + float32(2.0) != 3.5",
    ),
    (
        "reflected float32 subtraction is supported",
        "5.0 - float32(2.0) != 3.0",
    ),
    (
        "reflected float32 division is supported",
        "6.0 / float32(2.0) != 3.0",
    ),
    ("float32 negation is supported", "-float32(1.5) != -1.5"),
    ("float32 unary plus is supported", "+float32(1.5) != 1.5"),
    ("float32 absolute value is supported", "abs(float32(-1.5)) != 1.5"),
    (
        "float32 comparisons are supported",
        "not float32(1.0) < float32(2.0)",
    ),
    (
        "float64 retains binary64 precision",
        "float64(16777216.0) + float64(1.0) == float64(16777216.0)",
    ),
    (
        "inline results normalize to float32",
        "increment_float32(float32(16777216.0)) != 16777216.0",
    ),
)

PORTABLE_FLOAT = _contract(
    """
    from pyjs import float32, float64, js


    @js.inline("({_arg_strs[0]} + 1.0)")
    def increment_float32(value: float32) -> float32:
        return float32(float(value) + 1.0)
    """,
    "portable_float_result",
    """
    rounded = float32(16777216.0) + float32(1.0)
    overflow = float32(1e50)
    invalid = overflow - overflow
    """,
    PORTABLE_FLOAT_CHECKS,
)


def _float32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _portable_float_matrix_checks():
    checks = []
    for name, normalize in (("float32", _float32), ("float64", float)):
        cases = (
            (f"{name}(16777217.0)", normalize(16777217.0)),
            (
                f"{name}(16777216.0) + {name}(1.0)",
                normalize(normalize(16777216.0) + normalize(1.0)),
            ),
            (
                f"{name}(-16777216.0) - {name}(1.0)",
                normalize(normalize(-16777216.0) - normalize(1.0)),
            ),
            (
                f"{name}(4097.0) * {name}(4097.0)",
                normalize(normalize(4097.0) * normalize(4097.0)),
            ),
            (
                f"{name}(1.0) / {name}(10.0)",
                normalize(normalize(1.0) / normalize(10.0)),
            ),
            (f"{name}(16777216.0) + 1.0", normalize(16777217.0)),
            (f"1.0 + {name}(16777216.0)", normalize(16777217.0)),
            (f"{name}(16777216.0) + 1", normalize(16777217.0)),
            (f"1 + {name}(16777216.0)", normalize(16777217.0)),
            (f"2.0 - {name}(16777216.0)", normalize(-16777214.0)),
            (f"3 - {name}(1.5)", normalize(1.5)),
            (f"{name}(1.5) * 2", normalize(3.0)),
            (f"1.0 / {name}(10.0)", normalize(0.1)),
            (f"3 / {name}(2.0)", normalize(1.5)),
            (f"-{name}(1.5)", normalize(-1.5)),
            (f"+{name}(1.5)", normalize(1.5)),
            (f"abs({name}(-1.5))", normalize(1.5)),
            (f"{name}(1.0) < {name}(2.0)", True),
            (f"{name}(2.0) == 2.0", True),
            (f"{name}(2.0) == 2", True),
        )
        for index, (expression, expected) in enumerate(cases, 1):
            if type(expected) is bool:
                failure = f"not ({expression})" if expected else f"({expression})"
            else:
                failure = f"({expression}) != {expected!r}"
            checks.append((f"{name} case {index}: {expression}", failure))
    return tuple(checks)


PORTABLE_FLOAT_MATRIX = _contract(
    """
    from pyjs import float32, float64, js
    """,
    "portable_float_matrix_result",
    "",
    _portable_float_matrix_checks(),
)


WGSL_STORAGE_CHECKS = (
    ("signed division truncates toward zero", "values[0] / 3 != -2"),
    ("signed remainder follows the dividend", "values[0] % 3 != -1"),
    ("unsigned division is supported", "u32(7) / u32(3) != 2"),
    ("unsigned remainder is supported", "u32(7) % u32(3) != 1"),
    ("u32 addition wraps", "u32(4294967295) + 1 != 0"),
    ("f32 arithmetic rounds", "rounded != 16777216.0"),
    (
        "f32 division by zero produces infinity",
        "f32(1.0) / f32(0.0) <= f32(1000.0)",
    ),
    (
        "signed overflow division returns the minimum",
        "minimum / i32(-1) != minimum",
    ),
    ("signed overflow remainder returns zero", "minimum % i32(-1) != 0"),
    (
        "signed division by zero returns the dividend",
        "minimum / i32(0) != minimum",
    ),
    ("signed remainder by zero returns zero", "minimum % i32(0) != 0"),
    (
        "unsigned division by zero returns the dividend",
        "maximum / u32(0) != maximum",
    ),
    ("unsigned remainder by zero returns zero", "maximum % u32(0) != 0"),
)

WGSL_STORAGE = _contract(
    """
    from pyjs import js
    from pyjs.shader import Array, f32, i32, u32
    """,
    "wgsl_storage_result",
    """
    values = Array[i32, 2]([i32(-7), i32(5)])
    rounded = f32(16777216.0) + f32(1.0)
    minimum = i32(-2147483648)
    maximum = u32(4294967295)
    """,
    WGSL_STORAGE_CHECKS,
)


PORTABLE_OPERATOR_CHECKS = (
    ("int8 addition wraps", "int8(127) + 1 != -128"),
    ("uint8 addition wraps", "uint8(255) + 1 != 0"),
    ("int16 addition wraps", "int16(32767) + 1 != -32768"),
    ("uint16 addition wraps", "uint16(65535) + 1 != 0"),
    ("int32 addition wraps", "int32(2147483647) + 1 != -2147483648"),
    ("uint32 addition wraps", "uint32(4294967295) + 1 != 0"),
    (
        "int64 addition wraps",
        "int64(9223372036854775807) + 1 != -9223372036854775808",
    ),
    ("int8 subtraction wraps", "int8(120) - 127 != -7"),
    ("int8 multiplication wraps", "int8(20) * 13 != 4"),
    ("int8 floor division follows Python", "int8(-7) // 2 != -4"),
    ("int8 modulo follows Python", "int8(-7) % 2 != 1"),
    ("int8 true division returns float", "int8(-7) / 2 != -3.5"),
    ("int8 exponentiation wraps", "int8(20) ** 3 != 64"),
    ("int8 bitwise and wraps", "int8(0b1010) & 0b1100 != 0b1000"),
    ("int8 bitwise or wraps", "int8(0b1010) | 0b0101 != 0b1111"),
    ("int8 bitwise xor wraps", "int8(0b1010) ^ 0b1111 != 0b0101"),
    ("int8 left shift wraps", "int8(64) << 2 != 0"),
    ("signed right shift fills with sign", "int8(-1) >> 8 != -1"),
    ("unsigned right shift fills with zero", "uint8(255) >> 8 != 0"),
    ("uint8 inversion wraps", "~uint8(0) != 255"),
    ("int8 negation wraps", "-int8(-128) != -128"),
    ("int8 unary plus preserves the value", "+int8(127) != 127"),
    ("reflected int8 addition wraps", "130 + int8(127) != 1"),
    ("reflected int8 subtraction wraps", "130 - int8(127) != 3"),
    ("reflected int8 multiplication wraps", "3 * int8(100) != 44"),
    ("reflected int8 floor division works", "9 // int8(4) != 2"),
    ("reflected int8 modulo works", "9 % int8(4) != 1"),
    ("reflected int8 power wraps", "2 ** int8(7) != -128"),
    (
        "bool-left addition remains an ordinary integer",
        "True + int8(127) != 128",
    ),
    (
        "bool-left multiplication remains an ordinary integer",
        "(True * int8(2)) + 127 != 129",
    ),
    (
        "bool-left floor division remains an ordinary integer",
        "(True // int8(2)) + 128 != 128",
    ),
    (
        "bool-left modulo remains an ordinary integer",
        "(True % int8(2)) + 127 != 128",
    ),
    (
        "bool-left power remains an ordinary integer",
        "(True ** int8(7)) + 127 != 128",
    ),
    (
        "bool-left bitwise results remain ordinary integers",
        "(True | int8(2)) + 127 != 130",
    ),
    (
        "bool-left shifts remain ordinary integers",
        "(True << int8(2)) + 127 != 131",
    ),
    (
        "explicit int8 addition normalizes its result",
        "int8(127).__add__(1) != -128",
    ),
    (
        "explicit reflected int8 addition normalizes its result",
        "int8(127).__radd__(1) != -128",
    ),
    (
        "explicit int8 multiplication normalizes its result",
        "int8(100).__mul__(2) != -56",
    ),
    (
        "explicit int8 floor division follows Python",
        "int8(-7).__floordiv__(2) != -4",
    ),
    (
        "explicit int8 modulo follows Python",
        "int8(-7).__mod__(2) != 1",
    ),
    (
        "explicit int8 power normalizes its result",
        "int8(20).__pow__(3) != 64",
    ),
    (
        "explicit int8 shift normalizes its result",
        "int8(64).__lshift__(2) != 0",
    ),
    (
        "explicit int64 addition normalizes its result",
        "int64(9223372036854775807).__add__(1) != -9223372036854775808",
    ),
    (
        "explicit int64 true division rounds once",
        "int64(3).__truediv__(int64(2)) != 1.5",
    ),
    (
        "unsigned division normalizes a negative quotient",
        "uint8(1) // -256 != 255",
    ),
    (
        "signed modulo normalizes a wide positive remainder",
        "int8(-1) % 256 != -1",
    ),
    (
        "plain division operands are not narrowed before operating",
        "int8(1) // 256 != 0",
    ),
    ("int64 overflow division wraps", "minimum // int64(-1) != minimum"),
    ("int64 overflow modulo returns zero", "minimum % int64(-1) != 0"),
    (
        "positive int64 remains exact above 2**53",
        "int64(9007199254740993) != 9007199254740993",
    ),
    (
        "negative int64 remains exact above 2**53",
        "int64(-9007199254740993) != -9007199254740993",
    ),
    ("large int8 construction wraps exactly", "int8(9007199254740993) != 1"),
    ("negative uint32 construction wraps", "uint32(-1) != 4294967295"),
    ("int8 absolute value wraps", "abs(int8(-128)) != -128"),
    (
        "int64 true division rounds once",
        """
        int64(-1465195632138975614) / int64(6084712057446794809)
        != -0.24079950181796872
        """,
    ),
    (
        "large right arithmetic operands stay exact",
        "int8(1) + 9007199254740993 != 2",
    ),
    (
        "large left arithmetic operands stay exact",
        "9007199254740993 + int8(1) != 2",
    ),
    (
        "large uint32 multiplication operands stay exact",
        "uint32(1) * 9007199254740993 != 1",
    ),
    (
        "maximum int64 true division matches Python",
        "int64(9223372036854775807) / int64(1) != 9.223372036854776e18",
    ),
    (
        "minimum int64 division by negative one matches Python",
        "int64(-9223372036854775808) / int64(-1) != 9.223372036854776e18",
    ),
    (
        "small int64 quotient matches Python",
        "int64(1) / int64(9223372036854775807) != 1.0842021724855044e-19",
    ),
    (
        "int64 addition with an ordinary float selects float",
        "int64(9007199254740993) + 0.5 != 9007199254740992.0",
    ),
    (
        "ordinary float subtraction converts int64",
        "0.5 - int64(9007199254740993) != -9007199254740992.0",
    ),
    (
        "int64 multiplication with an ordinary float selects float",
        "int64(9007199254740993) * 0.5 != 4503599627370496.0",
    ),
    (
        "ordinary float division converts int64",
        "2.0 / int64(9007199254740993) != 2.220446049250313e-16",
    ),
    (
        "opposite int64 limits divide exactly",
        "int64(9223372036854775807) / int64(-9223372036854775808) != -1.0",
    ),
    (
        "large int64 quotient matches Python",
        "int64(9223372036854775807) / int64(3) != 3.0744573456182584e18",
    ),
    ("int64 narrows to int8 explicitly", "int8(wide) != 1"),
    ("int64 narrows to uint32 explicitly", "uint32(wide) != 1"),
    ("int64 converts to Python int", "int(int64(7)) != 7"),
    ("inline int8 results normalize", "double_byte(int8(100)) != -56"),
    (
        "inline int64 results normalize",
        "increment_int64(int64(9223372036854775807)) != -9223372036854775808",
    ),
)

PORTABLE_OPERATOR = _contract(
    """
    from pyjs import int8, int16, int32, int64, js
    from pyjs import uint8, uint16, uint32


    @js.inline("({_arg_strs[0]} * 2)")
    def double_byte(value: int8) -> int8:
        return int8(int(value) * 2)


    @js.inline("({_arg_strs[0]} + 1n)")
    def increment_int64(value: int64) -> int64:
        return int64(int(value) + 1)
    """,
    "portable_operator_result",
    """
    minimum = int64(-9223372036854775808)
    wide = int64(9007199254740993)
    """,
    PORTABLE_OPERATOR_CHECKS,
)


PORTABLE_INTEGER_LAYOUTS = (
    ("int8", 8, True),
    ("uint8", 8, False),
    ("int16", 16, True),
    ("uint16", 16, False),
    ("int32", 32, True),
    ("uint32", 32, False),
    ("int64", 64, True),
)


def _wrap_integer(value, bits, signed):
    modulus = 1 << bits
    value %= modulus
    if signed and value >= modulus >> 1:
        value -= modulus
    return value


def _portable_integer_matrix_checks(layouts):
    checks = []
    for name, bits, signed in layouts:
        modulus = 1 << bits
        minimum = -(modulus >> 1) if signed else 0
        maximum = (modulus >> 1) - 1 if signed else modulus - 1
        distinct_plain = f"2 ** {bits}" if bits < 64 else str(maximum)

        def fixed(value, bits=bits, signed=signed):
            return _wrap_integer(value, bits, signed)

        cases = (
            (f"{name}({maximum + 1})", minimum),
            (f"{name}({minimum - 1})", maximum),
            (f"{name}({maximum + modulus + 2})", minimum + 1),
            (f"{name}({maximum}) + 1", fixed(maximum + 1)),
            (f"{name}({minimum}) - 1", fixed(minimum - 1)),
            (f"{name}(20) * 13", fixed(fixed(20) * 13)),
            (f"{name}(-7) // 3", fixed(fixed(-7) // 3)),
            (f"{name}(-7) % 3", fixed(fixed(-7) % 3)),
            (f"{name}(20) ** 3", fixed(fixed(20) ** 3)),
            (f"{name}(10) & 12", fixed(fixed(10) & 12)),
            (f"{name}(10) | 5", fixed(fixed(10) | 5)),
            (f"{name}(10) ^ 15", fixed(fixed(10) ^ 15)),
            (f"{name}(64) << 2", fixed(fixed(64) << 2)),
            (f"{name}(-1) >> {bits}", fixed(fixed(-1) >> bits)),
            (f"{name}(1) >> {bits}", fixed(fixed(1) >> bits)),
            (f"-{name}({minimum})", fixed(-fixed(minimum))),
            (f"+{name}({maximum})", fixed(maximum)),
            (f"~{name}(0)", fixed(~fixed(0))),
            (f"abs({name}({minimum}))", fixed(abs(fixed(minimum)))),
            (f"130 + {name}(127)", fixed(130 + fixed(127))),
            (f"130 - {name}(127)", fixed(130 - fixed(127))),
            (f"3 * {name}(100)", fixed(3 * fixed(100))),
            (f"9 // {name}(4)", fixed(9 // fixed(4))),
            (f"9 % {name}(4)", fixed(9 % fixed(4))),
            (f"2 ** {name}(7)", fixed(2 ** fixed(7))),
            (f"255 & {name}(3)", fixed(255 & fixed(3))),
            (f"128 | {name}(1)", fixed(128 | fixed(1))),
            (f"255 ^ {name}(1)", fixed(255 ^ fixed(1))),
            (f"1 << {name}(7)", fixed(1 << fixed(7))),
            (f"-128 >> {name}(7)", fixed(-128 >> fixed(7))),
            (
                f"1677624431168367 >> {name}(49)",
                fixed(1677624431168367 >> fixed(49)),
            ),
            (
                f"1677624431168367 << {name}(49)",
                fixed(1677624431168367 << fixed(49)),
            ),
            (f"{name}(0) == {distinct_plain}", False),
            (f"{name}(0) > -1", True),
            *(() if bits == 64 else ((f"{name}(2) < 2.5", True),)),
            (f"{name}(3) + 0.5", 3.5),
            (f"0.5 + {name}(3)", 3.5),
            (f"{name}(3) - 0.5", 2.5),
            (f"3.5 - {name}(2)", 1.5),
            (f"{name}(3) * 0.5", 1.5),
            (f"0.5 * {name}(3)", 1.5),
            (f"{name}(-7) / 2", fixed(-7) / 2),
            (f"5 / {name}(2)", 2.5),
        )
        for index, (expression, expected) in enumerate(cases, 1):
            if type(expected) is bool:
                failure = f"not ({expression})" if expected else f"({expression})"
            else:
                failure = f"({expression}) != {expected!r}"
            checks.append((f"{name} case {index}: {expression}", failure))
    return tuple(checks)


def _portable_integer_matrix(name, layouts):
    return _contract(
        """
        from pyjs import int8, int16, int32, int64, js
        from pyjs import uint8, uint16, uint32
        """,
        f"portable_{name}_integer_matrix_result",
        "",
        _portable_integer_matrix_checks(layouts),
    )


PORTABLE_SIGNED_INTEGER_MATRIX = _portable_integer_matrix(
    "signed",
    tuple(layout for layout in PORTABLE_INTEGER_LAYOUTS if layout[2]),
)
PORTABLE_UNSIGNED_INTEGER_MATRIX = _portable_integer_matrix(
    "unsigned",
    tuple(layout for layout in PORTABLE_INTEGER_LAYOUTS if not layout[2]),
)


def _portable_array_matrix():
    setup = []
    checks = []
    for name, bits, signed in PORTABLE_INTEGER_LAYOUTS:
        maximum = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
        wrapped = -(1 << (bits - 1)) if signed else 0
        variable = f"{name}_values"
        setup.extend(
            (
                f"{variable} = StaticArray[{name}, 2]([{maximum}, 1])",
                f"{variable}[0] = {maximum + 1}",
            )
        )
        checks.extend(
            (
                (f"{name} array length is retained", f"len({variable}) != 2"),
                (
                    f"{name} array writes normalize items",
                    f"{variable}[0] != {wrapped}",
                ),
                (f"{name} array reads retain items", f"{variable}[1] != 1"),
            )
        )
    for name, expected in (
        ("float32", 16777216.0),
        ("float64", 16777217.0),
    ):
        variable = f"{name}_values"
        setup.extend(
            (
                f"{variable} = StaticArray[{name}, 2]([0.0, 1.0])",
                f"{variable}[0] = 16777217.0",
            )
        )
        checks.extend(
            (
                (f"{name} array length is retained", f"len({variable}) != 2"),
                (
                    f"{name} array writes normalize items",
                    f"{variable}[0] != {expected!r}",
                ),
                (f"{name} array reads retain items", f"{variable}[1] != 1.0"),
            )
        )
    return _contract(
        """
        from pyjs import StaticArray, float32, float64, int8, int16, int32
        from pyjs import int64, js, uint8, uint16, uint32
        """,
        "portable_array_matrix_result",
        "\n".join(setup),
        tuple(checks),
    )


PORTABLE_ARRAY_MATRIX = _portable_array_matrix()


EVALUATION_ORDER_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Counter:
        def __init__(self):
            self.value = 0

        def next(self) -> int:
            self.value = self.value + 1
            return self.value

        def touch(self) -> Counter:
            self.value = self.value * 10 + 1
            return self

        def argument(self) -> int:
            self.value = self.value * 10 + 2
            return self.value

        @staticmethod
        def answer(value: int) -> int:
            return value
    ''',
    "evaluation_order_result",
    '''
    counter = Counter()
    values = {str(counter.next()): str(counter.next()), str(counter.next()): str(counter.next())}
    receiver = Counter()
    result = receiver.touch().answer(receiver.argument())
    result = result + Counter.answer(receiver.value)
    ''',
    (
        ("dictionary entries evaluate key then value", "values['1'] + values.get('3', '') != '24'"),
        ("static method receiver runs once before arguments", "result != 24"),
    ),
)


GENERIC_OPERATOR_CONTRACT = _contract(
    '''
    from pyjs import js
    @js
    class Operand[T]:
        def __init__(self, value: T):
            self.value = value
        def __add__(self, other: object) -> str:
            return "forward"
        def __radd__(self, other: object) -> str:
            return "reverse"
    @js
    class Child(Operand[int]):
        def __radd__(self, other: object) -> str:
            return "child"
    ''',
    "generic_operator_contract",
    '''
    text = Operand("text")
    number = Operand(1)
    child = Child(2)
    ''',
    (
        ("same Python class specializations retain forward priority", "text + number != 'forward'"),
        ("runtime subclass priority ignores base specialization", "text + child != 'child'"),
    ),
)


STRUCTURAL_OPERATOR_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Left:
        __pyjs_structural__ = True
        def __add__(self, other: "Right") -> int:
            return 11
        def __eq__(self, other: "Right") -> bool:
            return False

    @js
    class Right:
        def __radd__(self, other: Left) -> int:
            return 22
        def __eq__(self, other: Left) -> bool:
            return True
    ''',
    "structural_operator_contract",
    '''
    left = Left()
    right = Right()
    ''',
    (
        ("structural compatibility is not runtime subclass priority", "left + right != 11"),
        ("explicit reflected calls still use the reflected method", "right.__radd__(left) != 22"),
        ("structural compatibility does not reverse equality", "left == right"),
    ),
)


CUSTOM_ARITHMETIC_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Number:
        def __init__(self, value: int):
            self.value = value
        def __abs__(self) -> int:
            return abs(self.value)
        def __divmod__(self, other: Number) -> int:
            return self.value // other.value * 10 + self.value % other.value

    @js
    class Reflected(Number):
        def __rdivmod__(self, other: Number) -> int:
            return self.value * 10 + other.value

    @js
    class Probe:
        def __init__(self):
            self.order = 0
        def left(self) -> Number:
            self.order = self.order * 10 + 1
            return Number(9)
        def right(self) -> Reflected:
            self.order = self.order * 10 + 2
            return Reflected(4)
    ''',
    "custom_arithmetic_contract",
    '''
    probe = Probe()
    ordinary = divmod(Number(-17), Number(5))
    reflected = divmod(probe.left(), probe.right())
    ''',
    (
        ("custom abs dispatch", "abs(Number(-7)) != 7"),
        ("ordinary scalar abs remains supported", "abs(-2) != 2 or abs(-1.5) != 1.5 or abs(True) != 1"),
        ("custom divmod dispatch", "ordinary != -37"),
        ("subclass reflected method wins", "reflected != 49"),
        ("reflected dispatch preserves operand order", "probe.order != 12"),
    ),
)


UNION_REFLECTED_ARITHMETIC_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class First:
        def __rsub__(self, other: int) -> int:
            return other * 100

    @js
    class Second:
        def __rsub__(self, other: int) -> int:
            return other * 1000

    @js
    class Probe:
        def __init__(self):
            self.order = 0
        def left(self) -> int:
            self.order = self.order * 10 + 1
            return 5
        def right(self, first: bool) -> First | Second:
            self.order = self.order * 10 + 2
            return First() if first else Second()
    ''',
    "union_reflected_arithmetic_contract",
    '''
    probe = Probe()
    first = probe.left() - probe.right(True)
    second = probe.left() - probe.right(False)
    ''',
    (
        ("union reflection preserves single operand evaluation", "probe.order != 1212"),
        ("union reflection selects each member", "first != 500 or second != 5000"),
    ),
)


BACKEND_CONTRACTS = {
    "portable storage": PORTABLE_STORAGE,
    "portable floats": PORTABLE_FLOAT,
    "portable float matrix": PORTABLE_FLOAT_MATRIX,
    "portable operators": PORTABLE_OPERATOR,
    "portable signed integer matrix": PORTABLE_SIGNED_INTEGER_MATRIX,
    "portable unsigned integer matrix": PORTABLE_UNSIGNED_INTEGER_MATRIX,
    "portable array matrix": PORTABLE_ARRAY_MATRIX,
    "WGSL storage": WGSL_STORAGE,
}


NUMERIC_NAME_CONTRACT = _contract(
    '''
    from builtins import int as Integer
    from pyjs import js

    @js
    class int:
        def __init__(self, text: str):
            self.text = text

    @js
    class float:
        def __init__(self, text: str):
            self.text = text

    @js
    class Box[T]:
        def __init__(self, item: T):
            self.item = item

    @js
    def describe_int(value: int | bool) -> str:
        if isinstance(value, int):
            return value.text
        return "bool"

    @js
    def describe_float(value: float | Integer) -> str:
        if isinstance(value, float):
            return value.text
        return "number"

    @js
    def describe_builtin(value: Integer | str) -> str:
        if isinstance(value, Integer):
            return str(value + 1)
        return value

    @js
    def describe_namesake(value: int | Integer) -> str:
        if isinstance(value, int):
            return value.text
        return str(value)
    ''',
    "numeric_names",
    "item = int('application')\nother = float('floating')\nboxed = Box[int](item)\nnumber = Box[Integer](4)",
    (("application int field after narrowing", "describe_int(item) != 'application'"),
     ("bool does not inherit application int", "describe_int(True) != 'bool' or describe_int(False) != 'bool'"),
     ("application float field after narrowing", "describe_float(other) != 'floating'"),
     ("numeric promotion does not match application float", "describe_float(3) != 'number' or describe_float(True) != 'number'"),
     ("builtin bool remains an int", "describe_builtin(True) != '2' or describe_builtin(3) != '4'"),
     ("same-name union members stay distinct", "describe_namesake(item) != 'application' or describe_namesake(5) != '5'"),
     ("specializations have distinct layouts", "boxed.item.text != 'application' or number.item != 4")),
    integer_type="Integer",
)


def nominal_object_contract(name):
    return _contract(
        f'''
        from builtins import int as Integer, bool as Boolean, object as Object, list as List, range as Range
        from pyjs import js

        @js
        class {name}:
            def __init__(self, rank: Integer):
                self.rank = rank
                self.other = rank + 1

            def __eq__(self, other: Object) -> Boolean:
                if isinstance(other, {name}):
                    return self.rank == other.rank
                return False

        @js
        class Child({name}):
            pass

        @js
        def pick(value: Object) -> Integer:
            if isinstance(value, {name}):
                return value.other
            return -1

        @js
        def echo(value: Object) -> Object:
            return value

        @js
        def optional_match(value: Integer | None) -> Boolean:
            return isinstance(value, {name})

        @js
        def initialize(value: {name} | None) -> Integer:
            if value is None:
                value = {name}(9)
            return value.rank

        @js
        def rewrite(value: {name} | None) -> Integer:
            total = 0
            if value is not None:
                for index in Range(2):
                    value = {name}(2)
                    total += value.rank
                total += value.rank
            return total
        ''',
        "nominal_objects",
        f'''
        item = {name}(3)
        child = Child(7)
        assigned: {name} | None = None
        assigned = {name}(5)
        values: List[Object] = [item, '', 4, child]
        rows = [{name}(2), {name}(1), {name}(3), {name}(1)]
        needle = {name}(1)
        first = rows.index(needle)
        count = rows.count(needle)
        present = needle in rows
        rows.remove(needle)
        ''',
        (("erased application retains fields", "pick(echo(item)) != 4 or pick(values[0]) != 4"),
         ("assignment narrows nominal optional storage", "assigned.rank != 5"),
         ("branch initialization proves nominal presence", "initialize(None) != 9 or initialize(item) != 3"),
         ("loop rewrites preserve nominal presence", "rewrite(None) != 0 or rewrite(item) != 6"),
         ("erased subclass uses nominal ancestry", "pick(echo(child)) != 8 or pick(values[3]) != 8"),
         ("short builtin values never masquerade as records", "pick('') != -1 or pick(4) != -1"),
         ("builtin values retain their own identities", "pick(True) != -1 or pick(1.5) != -1 or pick(None) != -1 or pick([1]) != -1"),
         ("erased container items keep distinct kinds", "pick(values[1]) != -1 or pick(values[2]) != -1"),
         ("absent optionals do not match application object", "optional_match(None) or optional_match(1)"),
         ("object-typed equality checks application fields", f"not (item == {name}(3)) or item == {name}(4)"),
         ("sequence equality uses nominal object arguments", f"[{name}(3)] != [{name}(3)] or [{name}(3)] == [{name}(4)]"),
         ("search uses application equality", "not present or first != 1 or count != 2"),
         ("remove deletes the first matching record", "len(rows) != 3 or rows[0].rank != 2 or rows[1].rank != 3 or rows[2].rank != 1")),
        integer_type="Integer",
    )


def nominal_union_comparison_contract(name, *, optional=False):
    alternative = "None" if optional else "Other"
    value = "None" if optional else "Other()"
    return _contract(
        f'''
        from builtins import object as Anything
        from pyjs import js
        @js
        class {name}:
            def __init__(self, rank: int):
                self.rank = rank
            def __eq__(self, other: Anything) -> bool:
                return isinstance(other, {name}) and self.rank == other.rank
        @js
        class Other:
            pass
        @js
        def same(left: {name} | {alternative}, right: {name}) -> bool:
            return left == right
        @js
        def reflected(left: {name}, right: {name} | {alternative}) -> bool:
            return left == right
        ''',
        "nominal_comparison",
        f"item = {name}(1)",
        (("same-class forward comparison calls application equality", f"not same({name}(1), item) or same({name}(2), item)"),
         ("alternate forward comparison is safe", f"same({value}, item)"),
         ("same-class reflected comparison calls application equality", f"not reflected(item, {name}(1)) or reflected(item, {name}(2))"),
         ("alternate reflected comparison is safe", f"reflected(item, {value})")),
    )


def nominal_constructor_contract(name):
    return _contract(
        f'''
        from pyjs import js
        @js
        class {name}[T]:
            def __init__(self, value: T):
                self.value = value
        ''',
        "nominal_constructor",
        f"first = {name}(value=3)\nsecond = {name}(4)",
        (("keyword inference follows the application signature", "first.value != 3"),
         ("positional construction does not request a builtin iterable", "second.value != 4")),
    )


def nominal_truth_contract(name):
    return _contract(
        f'''
        from builtins import bool as Boolean
        from pyjs import js
        @js
        class {name}:
            def __init__(self, value: int):
                self.value = value
            def __bool__(self) -> Boolean:
                return self.value > 0
        ''',
        "nominal_truth",
        f'''
        absent = {name}(0)
        present = {name}(1)
        total = 0
        if absent:
            total += 1
        if present:
            total += 2
        conditional = 1 if absent else 0
        ''',
        (("if uses application truth conversion", "total != 2"),
         ("conditional uses application truth conversion", "conditional != 0")),
    )


DATACLASS_NAN_IDENTITY_SOURCE = '''
from dataclasses import dataclass
from pyjs import js
@js
@dataclass
class Record:
    value: float
@js
def same(left: Record, right: Record) -> bool:
    return left == right
@js
def main() -> int:
    value = float('nan')
    record = Record(value)
    return 0 if same(record, record) and not same(record, Record(value)) else 1
'''


DATACLASS_IDENTITY_CONTRACT = _contract(
    '''
    from dataclasses import dataclass
    from pyjs import js
    @js
    class Field:
        def __init__(self, calls: list[int]):
            self.calls = calls
            self.explode = False
        def __eq__(self, other: "Field") -> bool:
            self.calls.append(1)
            if self.explode:
                raise ValueError('field compared')
            return False
    @js
    @dataclass
    class Record:
        field: Field
    @js
    class Other:
        pass
    @js
    def same(left: Record | Other, right: Record) -> bool:
        return left == right
    ''',
    "dataclass_identity",
    '''
    calls: list[int] = []
    field = Field(calls)
    record = Record(field)
    direct = record == record
    union = same(record, record)
    self_calls = len(calls)
    separate = same(record, Record(field))
    distinct_calls = len(calls)
    calls.clear()
    field.explode = True
    same_after_mutation = record == record and same(record, record)
    caught = False
    try:
        same(record, Record(field))
    except ValueError:
        caught = True
    ''',
    (("dataclass self equality does not compare fields", "not direct or not union or self_calls != 0"),
     ("distinct dataclasses compare even aliased non-reflexive fields", "separate or distinct_calls != 1"),
     ("self shortcut does not suppress distinct-record callback exceptions", "not same_after_mutation or not caught or calls != [1]")),
)


def nominal_alias_comparison_contract(name):
    return _contract(
        f'''
        from builtins import object as Anything
        from pyjs import js
        @js
        class {name}:
            def __init__(self, calls: list[int]):
                self.calls = calls
                self.explode = False
                self.unequal_explode = False
            def __eq__(self, other: Anything) -> bool:
                self.calls.append(1)
                if self.explode:
                    raise ValueError('called')
                return False
            def __ne__(self, other: Anything) -> bool:
                self.calls.append(2)
                if self.unequal_explode:
                    raise TypeError('inequality called')
                return False
        @js
        class Other:
            pass
        @js
        def same(left: {name} | Other, right: {name}) -> bool:
            return left == right
        @js
        def different(left: {name} | Other, right: {name}) -> bool:
            return left != right
        @js
        def reflected(left: {name}, right: {name} | Other) -> bool:
            return left != right
        ''',
        "nominal_alias_comparison",
        f'''
        calls: list[int] = []
        item = {name}(calls)
        direct = same(item, item)
        direct_calls = len(calls)
        calls.clear()
        item.explode = True
        unequal = different(item, item) or reflected(item, item)
        unequal_calls = calls == [2, 2]
        calls.clear()
        rows = [item]
        contained = item in rows
        index = rows.index(item)
        count = rows.count(item)
        sequence_equal = rows == [item] and (item,) == (item,)
        mapping_equal = {{'key': item}} == {{'key': item}}
        rows.remove(item)
        container_calls = len(calls)
        caught = False
        try:
            same(item, item)
        except ValueError:
            caught = True
        equality_calls = len(calls)
        calls.clear()
        item.unequal_explode = True
        unequal_caught = False
        try:
            different(item, item)
        except TypeError:
            unequal_caught = True
        ''',
        (("root equality calls an aliased custom receiver", "direct or direct_calls != 1"),
         ("sequence search preserves identity shortcuts", "not contained or index != 0 or count != 1 or len(rows) != 0"),
         ("container equality preserves member identity", "not sequence_equal or not mapping_equal or container_calls != 0"),
         ("root equality preserves callback exceptions", "not caught or equality_calls != 1"),
         ("root inequality selects its own callback in both union positions", "unequal or not unequal_calls"),
         ("root inequality preserves its own exceptions", "not unequal_caught or calls != [2]")),
    )


def scalar_namesake_sort_contract(name):
    return _contract(
        f'''
        from builtins import int as Integer, str as String, bool as Boolean
        from pyjs import js

        @js
        class {name}:
            def __init__(self, rank: Integer, label: String):
                self.rank = rank
                self.label = label

            def __lt__(self, other: "{name}") -> Boolean:
                return self.rank < other.rank

        @js
        def identity(value: {name}) -> {name}:
            return value
        ''',
        "namesake_sort",
        f'''
        values = [{name}(2, 'b'), {name}(1, 'a'), {name}(2, 'c')]
        ascending = sorted(values)
        descending = sorted(values, reverse=True)
        keyed = sorted(values, key=identity)
        original = ''.join([value.label for value in values])
        values.sort()
        in_place = ''.join([value.label for value in values])
        values.sort(key=identity, reverse=True)
        ''',
        (("ascending uses record comparisons", "''.join([value.label for value in ascending]) != 'abc'"),
         ("reverse remains stable", "''.join([value.label for value in descending]) != 'bca'"),
         ("record-valued keys use comparisons", "''.join([value.label for value in keyed]) != 'abc'"),
         ("record sequences retain element equality", "ascending != keyed or ascending == descending or tuple(ascending) != tuple(keyed)"),
         ("sorted leaves input unchanged", "original != 'bac'"),
         ("in-place uses record comparisons", "in_place != 'abc'"),
         ("keyed in-place remains stable", "''.join([value.label for value in values]) != 'bca'")),
        integer_type="Integer",
    )


COLLECTION_NAME_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class list:
        def __init__(self):
            self.value = 0
        def append(self, value: int) -> None:
            self.value += value

    @js
    class dict:
        def __init__(self):
            self.value = 0
        def setdefault(self, key: int, value: int) -> int:
            self.value = key + value
            return self.value

    @js
    class set:
        def __init__(self):
            self.value = 0
        def add(self, value: int) -> None:
            self.value += value

    @js
    class frozenset:
        def copy(self) -> int:
            return 9

    @js
    class Iterator:
        def value(self) -> int:
            return 5

    @js
    class Child(Iterator):
        pass

    @js
    def accept(value: Iterator) -> int:
        return value.value()
    ''',
    "collection_names",
    '''
    sequence = list()
    sequence.append(3)
    sequence.append(4)
    mapping = dict()
    mapped = mapping.setdefault(2, 5)
    members = set()
    members.add(8)
    copied = frozenset().copy()
    inherited = accept(Child())
    ''',
    (("application list method", "sequence.value != 7"),
     ("application dict method", "mapped != 7 or mapping.value != 7"),
     ("application set method", "members.value != 8"),
     ("application frozenset method", "copied != 9"),
     ("application Iterator is nominal", "inherited != 5")),
)


TUPLE_ITERABLE_CONTRACT = _contract(
    '''
    from pyjs import js, int8
    from collections.abc import Iterator

    @js
    class tuple:
        def __iter__(self) -> Iterator[int8]:
            return iter([int8(127)])
    ''',
    "tuple_item_inference",
    "value = next(iter(tuple()))",
    (("application tuple item inference", "int(value + 1) != -128"),),
)


OPTIONAL_STRING_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Probe:
        def __init__(self):
            self.calls = 0

        def take(self, value: str | None) -> str | None:
            self.calls = self.calls + 1
            return value

    @js
    def fallback(value: str | None) -> str:
        return value or "fallback"

    @js
    def keep(value: str | None) -> str | None:
        return value and "selected"

    @js
    def empty_last(value: str | None) -> str | None:
        return value or None
    ''',
    "optional_string_result",
    '''
    probe = Probe()
    selected = probe.take(None) or probe.take("") or probe.take("x") or probe.take("bad")
    stopped = probe.take(None) and probe.take("bad")
    ''',
    (
        ("or evaluates each operand once and short circuits", 'selected != "x"'),
        ("and preserves null and short circuits", "stopped is not None"),
        ("short circuited calls never run", "probe.calls != 4"),
        ("null is falsy for or", 'fallback(None) != "fallback"'),
        ("empty string is falsy for or", 'fallback("") != "fallback"'),
        ("nonempty string is truthy for or", 'fallback("x") != "x"'),
        ("null is falsy for and", "keep(None) is not None"),
        ("and preserves the empty string", 'keep("") != ""'),
        ("and selects the right operand", 'keep("x") != "selected"'),
        ("null may be the final operand", 'empty_last("") is not None'),
        ("null final operand is skipped for truthy values", 'empty_last("x") != "x"'),
    ),
)


UNION_NONE_GUARD_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    def describe(value: list[str] | str | None) -> str:
        if value is None:
            return "absent"
        if isinstance(value, str):
            return value.upper()
        return str(len(value) + 1)

    @js
    def describe_present(value: list[str] | str | None) -> str:
        if value is not None:
            if isinstance(value, str):
                return value.upper()
            return str(len(value) + 1)
        return "absent"
    ''',
    "union_none_guard_result", "",
    (
        ("None keeps the early-return branch", 'describe(None) != "absent"'),
        ("list remains after the following str guard", 'describe(["a", "b", "c", "d"]) != "5"'),
        ("str remains in the non-None union", 'describe("snow") != "SNOW"'),
        ("is not None excludes None in the true branch", 'describe_present("snow") != "SNOW"'),
        ("nested concrete narrowing preserves list", 'describe_present(["a", "b", "c", "d"]) != "5"'),
        ("false is-not-None branch remains reachable", 'describe_present(None) != "absent"'),
    ),
)


OPTIONAL_INTEGER_CONTRACT = _contract(
    '''
from pyjs import js, int64

@js
def same(left: int64 | None, right: int64 | None) -> bool:
    return left == right

@js
def different(left: int64 | None, right: int64 | None) -> bool:
    return left != right

@js
def literal(value: int64 | None) -> bool:
    return value == 9007199254740993

@js
def chained(value: int64 | None) -> bool:
    return value == 9007199254740993 == value

@js
def textual(value: int64 | None) -> bool:
    return value == "0"

@js
def boolean(value: int64 | None) -> bool:
    return value == False

@js
def replace(value: int64 | None, other: int64 | None) -> int64 | None:
    if value is not None:
        value = other
    return value

@js
def populate(value: int64 | None) -> int64 | None:
    if value is None:
        value = int64(5)
    return value

@js
def local(value: int64 | None, other: int64 | None) -> int64 | None:
    saved: int64 | None = value
    if saved is not None:
        saved = other
    return saved
''',
    "optional_integer_contract",
    '''
    large = int64(9007199254740993)
    nearby = int64(9007199254740992)
    zero = int64(0)
    ''',
    (
        ("None is distinct from numeric zero", "same(None, zero) or same(zero, None)"),
        ("optional equality retains None", "not same(None, None) or different(None, None)"),
        ("large represented values retain precision", "not same(large, large) or same(large, nearby)"),
        ("inequality dispatch retains member kind", "not different(None, zero) or not different(large, nearby)"),
        ("large ordinary literal coercion stays exact", "not literal(large) or literal(nearby) or literal(None)"),
        ("chained comparison preserves literal precision", "not chained(large) or chained(nearby) or chained(None)"),
        ("text is not parsed by numeric equality", "textual(zero) or textual(None)"),
        ("bool remains numeric but None does not", "not boolean(zero) or boolean(None)"),
        ("parameter overwrite invalidates nonnull proof", "replace(large, None) is not None"),
        ("parameter assignment retains union member map", "populate(None) != int64(5) or populate(large) != large"),
        ("local overwrite retains nullable storage", "local(large, None) is not None or local(large, nearby) != nearby"),
    ),
)


OPTIONAL_BRANCH_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    class Holder:
        text: str | None
        def __init__(self) -> None:
            self.text = "old"

    @js
    def rebind(value: Holder | None) -> Holder | None:
        if value is None:
            return None
        if value.text is not None:
            value = None
        return value

    @js
    def switch(value: str | None) -> str | None:
        if value is not None:
            value = None
        else:
            value = "found"
        return value

    @js
    def nested(value: str | None, reset: bool) -> str | None:
        if value is None:
            value = "found"
            if reset:
                value = None
        return value

    @js
    def early(value: str | None) -> str | None:
        if value is None:
            return "missing"
        else:
            value = None
        return value

    @js
    def negated(value: str | None) -> str | None:
        if not (value is None):
            value = None
        else:
            return "missing"
        return value

    @js
    def later(value: str | None, reset: bool) -> str | None:
        if value is None:
            return "missing"
        if reset:
            value = None
        return value

    @js
    def normalize(value: str | None, trim: bool) -> str:
        if value is None:
            return "-"
        if trim:
            value = value.strip()
        return value

    @js
    def concatenate(value: str | None) -> str:
        if value is None:
            value = ""
        for part in ["a", "b"]:
            value += part
        while len(value) < 4:
            value = value + "c"
        return value

    @js
    def retarget(value: str | None, items: list[str]) -> str:
        if value is None:
            value = "empty"
        for value in items:
            pass
        return value

    @js
    def clear_both(left: str | None, right: str | None) -> str:
        if left is None:
            left = "a"
        if right is None:
            right = "b"
        for index in range(2):
            if left is not None:
                left = None
        for index in range(2):
            if right is not None:
                right = None
        return (left or "-") + (right or "-")

    ''',
    "optional_branch_result",
    "",
    (
        ("present branch can clear the value", 'switch("old") is not None'),
        ("absent branch initializes the value", 'switch(None) != "found"'),
        ("nested write invalidates earlier initialization", 'nested(None, True) is not None'),
        ("nested no-op preserves initialization", 'nested(None, False) != "found"'),
        ("surviving branch can invalidate its condition", 'early("old") is not None'),
        ("early return remains intact", 'early(None) != "missing"'),
        ("negated guard cannot restore presence", 'negated("old") is not None'),
        ("negated guard preserves its absent return", 'negated(None) != "missing"'),
        ("later conditional write clears presence", 'later("old", True) is not None'),
        ("later conditional no-op retains value", 'later("old", False) != "old"'),
        ("receiver rebinding must not reanalyze its old guard", 'rebind(Holder()) is not None'),
        ("receiver absent path remains intact", 'rebind(None) is not None'),
        ("conditional concrete writes preserve presence", 'normalize(None, True) + normalize(" a ", True) + normalize("b", False) != "-ab"'),
        ("loop concrete writes preserve presence", 'concatenate(None) + concatenate("z") != "abcczabc"'),
        ("loop targets preserve presence including empty iteration", 'retarget(None, []) + retarget("start", ["end"]) != "emptyend"'),
        ("separate loop invariants converge after widening", 'clear_both(None, "b") != "--"'),
    ),
)


OPTIONAL_OBJECT_CONTRACT = _contract(
    '''
    from pyjs import js

    @js
    def opaque() -> object:
        return None

    @js
    def write(payload: object, mode: int) -> bool:
        value: object | None = "present"
        if value is None:
            value = "present"
        if mode == 0:
            value = payload
        elif mode == 1:
            for index in range(1):
                value = payload
        else:
            value = opaque()
        return value is None

    @js
    def direct(payload: object) -> bool:
        value: object | None = "present"
        if value is None:
            value = "present"
        value = payload
        return value is None

    @js
    def cleanup_object(mode: int) -> str:
        value: object | None = "old"
        result = ""
        if value is not None:
            try:
                try:
                    value = opaque()
                    if mode > 0:
                        raise ValueError("fail")
                except ValueError:
                    if mode == 2:
                        raise ValueError("reraised")
                    result = "handled"
                finally:
                    result += "none" if value is None else "present"
            except ValueError:
                result += "caught"
        return result
    ''',
    "optional_object_contract",
    "",
    (
        ("direct object assignment can be absent", 'not direct(None) or direct("present")'),
        ("conditional object assignment can be absent", 'not write(None, 0) or write("present", 0)'),
        ("loop object assignment can be absent", 'not write(None, 1) or write("present", 1)'),
        ("object-returning call can be absent", 'not write(None, 2)'),
        ("guarded object write reaches normal and exceptional finally", 'cleanup_object(0) + cleanup_object(1) + cleanup_object(2) != "nonehandlednonenonecaught"'),
    ),
)


STRING_SEARCH_CASES = (
    ("", ""), ("", "x"), ("note", ""), ("note", "note"), ("note", "missing"),
    ("note", "no"), ("note", "te"), ("café", "fé"), ("😀", "😀"),
    ("😀", "\ud83d"), ("😀", "\ude00"), ("a😀b", "a\ud83d"),
    ("a😀b", "\ude00b"), ("\ud83d", "\ud83d"), ("\ude00", "\ude00"),
    ("😀\ud83d", "\ud83d"), ("😀\ude00", "\ude00"),
    ("😀-\ud83d-x", "\ud83d"), ("\ude00-😀", "\ude00"),
)


PORTABLE_FAILURE_SOURCES = {
    "division by zero": """
from pyjs import int8


def main() -> int:
    return int8(1) // int8(0)
""",
    "negative exponent": """
from pyjs import int8


def main() -> int:
    return int8(2) ** int8(-1)
""",
    "negative shift": """
from pyjs import int8


def main() -> int:
    return int8(1) << int8(-1)
""",
    "fixed float division by zero": """
from pyjs import float32


def main() -> int:
    value = float32(1.0) / float32(0.0)
    return 1 if value else 0
""",
}
