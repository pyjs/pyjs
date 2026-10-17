"""Finite scalar enum semantics preserve nominal identity over scalar storage."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_integer_slots_keep_ordinary_results_with_portable_operands(tmp_path, optimize):
    expressions = [
        "Number.LARGE + int8(127)", "Number.NEGATIVE - int8(127)",
        "Number.LARGE * int8(2)", "Number.LARGE // int8(2)",
        "Number.LARGE % int8(127)", "Number.LARGE << int8(1)",
        "Number.LARGE >> int8(1)", "Number.LARGE & int8(127)",
        "Number.LARGE | int8(0)", "Number.LARGE ^ int8(127)",
        "Number.TWO ** int8(8)",
    ]
    statements = '\n    '.join(
        f"value{index} = {expression}; output.append(str(value{index}) + ':' + str(value{index} + 256))"
        for index, expression in enumerate(expressions))
    result = LLVM().assert_matches_python(f'''
from enum import IntEnum
from pyjs import int8
class Number(IntEnum):
    TWO = 2
    LARGE = 257
    NEGATIVE = -257
def main() -> str:
    output: list[str] = []
    {statements}
    return '|'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_enum_sorting_and_structural_order_keep_nominal_results(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from enum import IntEnum, StrEnum
from pyjs.native import gc_collect, gc_set_threshold
class Number(IntEnum):
    LOW = -9223372036854775808
    ONE = 1
    ALIAS = 1
    HIGH = 9223372036854775807
class Text(StrEnum):
    EMPTY = ""
    FIRST = "a"
    LAST = "✓"
def main() -> str:
    gc_set_threshold(1)
    numbers = [Number.HIGH, Number.ONE, Number.LOW, Number.ALIAS]
    ordered = sorted(numbers)
    numbers.sort(reverse=True)
    words = [Text.LAST, Text.EMPTY, Text.FIRST]
    words.sort()
    assert ordered[0] is Number.LOW and ordered[1] is Number.ONE
    assert min(numbers) is Number.LOW and max(numbers) is Number.HIGH
    assert min(words) is Text.EMPTY and max(words) is Text.LAST
    assert [Number.LOW] < [Number.HIGH]
    assert [Text.EMPTY] < [Text.LAST]
    assert [Text.FIRST] <= [Text.FIRST]
    assert [Text.LAST] > [Text.FIRST]
    assert [Number.ONE] >= [Number.ALIAS]
    assert sorted([(Number.HIGH,), (Number.LOW,)])[0][0] is Number.LOW
    gc_collect()
    return repr(numbers) + repr(ordered) + repr(words) + repr(sorted(words, reverse=True))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("base,value", [("IntEnum", "1"), ("StrEnum", "'one'")])
def test_structural_ordering_preserves_enum_arguments_for_callbacks(tmp_path, optimize, base, value):
    comparison = LLVM().assert_matches_python(f'''
from enum import {base}
from pyjs.native import gc_collect, gc_set_threshold
class Member({base}):
    ONE = {value}
class Boundary:
    def __init__(self, events: list[str]):
        self.events = events
    def __lt__(self, other: Member) -> bool:
        self.events.append('lt')
        gc_collect()
        return other is Member.ONE
    def __le__(self, other: Member) -> bool:
        self.events.append('le')
        gc_collect()
        return other is Member.ONE
    def __gt__(self, other: Member) -> bool:
        self.events.append('gt')
        gc_collect()
        return other is Member.ONE
    def __ge__(self, other: Member) -> bool:
        self.events.append('ge')
        gc_collect()
        return other is Member.ONE
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    boundary = Boundary(events)
    assert (Member.ONE,) < (boundary,)
    assert (Member.ONE,) <= (boundary,)
    assert (Member.ONE,) > (boundary,)
    assert (Member.ONE,) >= (boundary,)
    assert (boundary,) < (Member.ONE,)
    assert (boundary,) <= (Member.ONE,)
    assert (boundary,) > (Member.ONE,)
    assert (boundary,) >= (Member.ONE,)
    return '|'.join(events)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_enum_members_and_collections(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
import enum
from enum import StrEnum
class Color(StrEnum):
    RED = "r'ed"
    ALIAS = "r'ed"
    BLUE = "blue"
class Status(enum.IntEnum):
    READY = 2
    READY_ALIAS = 2
    FAILED = 9
def summarize(color: Color, status: Status) -> str:
    colors: list[Color] = [color, Color.BLUE]
    statuses: list[Status] = [status, Status.FAILED]
    return '|'.join((
        Color.RED.name, Color.ALIAS.name, Color.BLUE.value.upper(),
        str(color), repr(color), repr(status), status.name, str(status.value),
        str(color == "r'ed"), str(status == 2),
        str(Color.RED is Color.ALIAS), str(Status.READY is Status.READY_ALIAS),
        str(Color("r'ed") is Color.RED),
        ','.join(colors), str(sum(statuses)), repr(colors), repr(statuses),
        str(hash(color) == hash(color.value)), str(hash(status) == hash(status.value)),
    ))
def main() -> str:
    return summarize(Color.RED, Status.READY)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_enum_constructor_failure_and_retry(tmp_path, optimize):
    comparison = LLVM().assert_library_matches_python('''
from enum import IntEnum, StrEnum
class Color(StrEnum):
    RED = "red"
    BLUE = "blue"
class Status(IntEnum):
    READY = 2
    FAILED = 9
def render(color: str, status: int) -> str:
    messages: list[str] = []
    try:
        Color(color)
    except ValueError as error:
        messages.append(str(error))
    try:
        Status(status)
    except ValueError as error:
        messages.append(str(error))
    return '|'.join([Color("red").name, Status(9).name, *messages])
''', "missing", 7, directory=tmp_path, entry_point="render", optimize=optimize)
    assert comparison.matches
    comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_enum_nominal_and_numeric_operations(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from enum import IntEnum as Integers, StrEnum as Strings, auto
from pyjs.native import gc_set_threshold, gc_collect
class State(Integers):
    ZERO = 0
    ONE = auto()
    ALIAS = 1
    MAX = 9223372036854775807
class Other(Integers):
    ONE = 1
class Label(Strings):
    READY = "a'\\n✓"
    ALIAS = "a'\\n✓"
    EMPTY = ""
    NUMBER = "12"
class OtherLabel(Strings):
    READY = "a'\\n✓"
class Record:
    def __init__(self, state: State, label: Label):
        self.state = state
        self.label = label
def main() -> int:
    gc_set_threshold(1)
    record = Record(State.ONE, Label.READY)
    print(repr(State.MAX), State.ONE.__repr__(), State.ONE.__str__())
    print(repr(Label.ALIAS), Label.READY.__repr__(), Label.READY.__str__())
    print(f"{State.MAX!r}", f"{Label.READY!r}", f"{State.ONE:04d}", f"{Label.EMPTY:>3s}")
    ordinary = 1
    print(State.ONE is Other.ONE, State.ONE is not Other.ONE, State.ONE is ordinary)
    print(Label.READY is OtherLabel.READY, Label.READY is Label.READY.value)
    print(State.ONE == Other.ONE, Label.READY == OtherLabel.READY)
    print(bool(State.ZERO), bool(State.ONE), bool(Label.EMPTY), bool(Label.READY))
    print(State.ONE + 2, State.ONE < 2, State.ONE << 2, State.ONE * 3)
    print(repr(sum([State.ONE], State.ONE)), repr(sum([State.ONE], start=State.ONE)))
    print(State(True).name, int(Label.NUMBER), float(Label.NUMBER), format(State.ONE, '.2f'))
    print([10, 20][State.ONE], hex(State.ONE), len(Label.READY), Label.READY.upper())
    print(isinstance(State.ONE, State), isinstance(State.ONE, int), isinstance(State.ONE, Other))
    print(isinstance(Label.READY, Label), isinstance(Label.READY, str))
    gc_collect()
    print(record.state.name, record.label.name, record.label == Label.READY)
    return 0
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("base,value", [("IntEnum", "1"), ("StrEnum", "'a'")])
def test_scalar_enums_cannot_lose_nominal_identity_when_erased(base, value):
    with pytest.raises(LLVMUnsupported, match="scalar enums cannot be erased"):
        transpile_llvm(f'''
from enum import {base}
class State({base}):
    READY = {value}
def erase(value: object) -> str:
    return repr(value)
def main() -> str:
    return erase(State.READY)
''')


@pytest.mark.parametrize("base,value,scalar", [("IntEnum", "1", "int"), ("StrEnum", "'a'", "str")])
@pytest.mark.parametrize("body", [
    "return read(State.READY, {value})",
    "value: {scalar} = State.READY\n    return repr(value)",
    "values: list[{scalar}] = [State.READY]\n    return repr(values)",
    "values: dict[{scalar}, {scalar}] = {{}}\n    values[State.READY] = {value}\n    return repr(values)",
    "values: dict[{scalar}, int] = {{}}\n    values.setdefault(State.READY, 1)\n    return repr(values)",
    "values: dict[{scalar}, int | None] = {{}}\n    values.setdefault(State.READY)\n    return repr(values)",
    "values: set[{scalar}] = set()\n    values.add(State.READY)\n    return repr(values)",
])
def test_enum_scalar_widening_is_explicit(base, value, scalar, body):
    with pytest.raises(LLVMUnsupported, match="scalar enums cannot be erased or widened"):
        transpile_llvm(f'''
from enum import {base}
class State({base}):
    READY = {value}
def read(value: {scalar}, equal_value: {scalar}) -> str:
    return repr(value)
def main() -> str:
    {body.format(value=value, scalar=scalar)}
''')


OPTIONAL_MUTATIONS = [
    ("dict[{scalar} | None, int]", "{{}}", "values[key] = 1"),
    ("dict[{scalar} | None, int]", "{{}}", "values.setdefault(key, 1)"),
    ("set[{scalar} | None]", "set()", "values.add(key)"),
]


def optional_mutation_source(base, value, scalar, annotation, initial, mutation, *, convert):
    key = f"{scalar}(value) if value is not None else None" if convert else "value"
    return f'''
from enum import {base}
class State({base}):
    READY = {value}
def store(value: State | None) -> str:
    key = {key}
    values: {annotation.format(scalar=scalar)} = {initial.format()}
    {mutation}
    return repr(values)
def main() -> str:
    return store(State.READY) + '|' + store(None)
'''


@pytest.mark.parametrize("base,value,scalar", [("IntEnum", "1", "int"), ("StrEnum", "'a'", "str")])
@pytest.mark.parametrize("annotation,initial,mutation", OPTIONAL_MUTATIONS)
def test_optional_enum_mutation_cannot_erase_nominal_identity(base, value, scalar, annotation, initial, mutation):
    with pytest.raises(LLVMUnsupported, match="scalar enums cannot be erased or widened"):
        transpile_llvm(optional_mutation_source(base, value, scalar, annotation, initial, mutation, convert=False))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("base,value,scalar", [("IntEnum", "1", "int"), ("StrEnum", "'a'", "str")])
@pytest.mark.parametrize("annotation,initial,mutation", OPTIONAL_MUTATIONS)
def test_optional_enum_mutation_explicit_conversion(tmp_path, base, value, scalar, annotation, initial, mutation, optimize):
    source = optional_mutation_source(base, value, scalar, annotation, initial, mutation, convert=True)
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("base,value,scalar", [("IntEnum", "1", "int"), ("StrEnum", "'a'", "str")])
@pytest.mark.parametrize("disabled", ["__hash__ = None", "__eq__ = {scalar}.__eq__", "__str__ = None"])
def test_disabled_enum_protocols_are_custom_behavior(base, value, scalar, disabled):
    with pytest.raises(CompilationError, match="scalar enums do not support custom behavior"):
        transpile_llvm(f'''
from enum import {base}
class State({base}):
    READY = {value}
    {disabled.format(scalar=scalar)}
def main() -> int:
    return hash(State.READY)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_enum_members_can_share_inherited_scalar_method_names(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from enum import IntEnum, StrEnum
class Label(StrEnum):
    READY = 'ready'
    upper = 'upper'
    center = 'center'
    format = '{}'
    ALIAS = 'upper'
class Number(IntEnum):
    READY = 4
    conjugate = 2
    bit_length = 7
    from_bytes = 8
def describe(raw: str, number: int) -> str:
    label, state = Label(raw), Number(number)
    values: dict[Label, int] = {label: state.value}
    return '|'.join((label.name, label.value, str(label), repr(label), repr(values),
                     state.name, repr(state), str(state + 1), str(label == raw)))
def main() -> str:
    return '|'.join((describe('ready', 4), describe('center', 2), describe('upper', 7),
                     repr(Label.upper), Label.upper.upper(), Label.center.center(8),
                     repr(Label.format), str(Label.upper is Label.ALIAS),
                     str(Number.bit_length), str(Number.bit_length + 1),
                     repr(Number.conjugate), repr(Number.from_bytes)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("statement", ["State.ONE = State.ONE", "del State.ONE"])
def test_enum_members_are_read_only(statement):
    with pytest.raises(CompilationError, match="Enum members are read-only"):
        transpile_llvm(f'''
from enum import IntEnum
class State(IntEnum):
    ONE = 1
def main() -> int:
    {statement}
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_enum_binary_operators_return_ordinary_scalars(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from enum import IntEnum, StrEnum
class Number(IntEnum):
    ONE = 1
    TWO = 2
class Other(IntEnum):
    THREE = 3
class Label(StrEnum):
    A = 'a'
    B = 'b'
def main() -> str:
    x, y = Number.TWO, Number.ONE
    return '|'.join((repr(x + y), repr(x - y), repr(x * y),
                    repr(x / y), repr(x // y), repr(x % y), repr(x ** y),
                    repr(x << y), repr(x >> y), repr(x | y), repr(x & y), repr(x ^ y),
                    repr(x + Other.THREE), repr(x | 1), repr(1 | x),
                    repr(x & 1), repr(1 & x), repr(x ^ 1), repr(1 ^ x),
                    repr(Label.A + Label.B)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_scalar_enum_constructor_exception(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from enum import IntEnum, StrEnum
class Number(IntEnum):
    pass
class Label(StrEnum):
    pass
def main() -> str:
    result: list[str] = []
    try:
        Number(1)
    except TypeError as error:
        result.append(str(error))
    try:
        Label('a')
    except TypeError as error:
        result.append(str(error))
    return '|'.join(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("base,value", [("IntEnum", "1"), ("StrEnum", "'a'")])
@pytest.mark.parametrize("annotation,default", [("State", "State.READY"), ("tuple[State]", "(State.READY,)")])
def test_dataclass_enum_defaults_have_a_located_diagnostic(base, value, annotation, default):
    with pytest.raises(CompilationError, match="Enum default for dataclass field 'state' is not supported"):
        transpile_llvm(f'''
from dataclasses import dataclass
from enum import {base}
class State({base}):
    READY = {value}
@dataclass
class Record:
    state: {annotation} = {default}
def main() -> str:
    return repr(Record())
''')


def test_explicit_inherited_enum_descriptor_uses_the_scalar_model(tmp_path):
    LLVM().assert_matches_python('''
from enum import IntEnum, StrEnum
class Number(IntEnum):
    ONE = 1
    __str__ = int.__repr__
    __eq__ = int.__eq__
    __hash__ = int.__hash__
class Label(StrEnum):
    A = 'a'
    __str__ = str.__str__
    __eq__ = str.__eq__
    __hash__ = str.__hash__
def main() -> str:
    return str(Number.ONE) + str(Label.A) + str(hash(Number.ONE) == hash(1)) + str(hash(Label.A) == hash('a'))
''', directory=tmp_path)


@pytest.mark.parametrize("expression", [
    "len(DEFAULT)", "1 if DEFAULT is DEFAULT else 0",
    "1 if DEFAULT == OTHER else 0", "1 if DEFAULT < OTHER else 0",
    "1 if DEFAULT else 0", "1 if State.ONE is State.ONE else 0",
    "1 if TEXT == OTHER_TEXT else 0",
])
def test_isolated_global_enum_and_string_dependencies(tmp_path, expression):
    LLVM().assert_matches_python(f'''
from enum import IntEnum, StrEnum
class State(IntEnum):
    ONE = 1
class Label(StrEnum):
    A = 'a'
    B = 'b'
DEFAULT = Label.A
OTHER = Label.B
TEXT = 'a'
OTHER_TEXT = 'b'
def main() -> int:
    return {expression}
''', directory=tmp_path)


@pytest.mark.parametrize("start", ["State.ONE", "start=State.ONE"])
def test_potentially_empty_sum_cannot_erase_an_enum_start(start):
    with pytest.raises(LLVMUnsupported, match="sum with an enum start requires a statically nonempty iterable"):
        transpile_llvm(f'''
from enum import IntEnum
class State(IntEnum):
    ONE = 1
def display(values: list[State]) -> str:
    return repr(sum(values, {start}))
def main() -> str:
    return display([])
''')


@pytest.mark.parametrize("body", [
    "def __repr__(self) -> str:\n        return 'changed'",
    "@classmethod\n    def _missing_(cls, value):\n        return cls.ONE",
    "@property\n    def value(self) -> int:\n        return 9",
    "def extra(self) -> int:\n        return 7",
])
def test_custom_enum_behavior_is_diagnosed_before_body_analysis(body):
    with pytest.raises(CompilationError, match="scalar enums do not support custom behavior"):
        transpile_llvm(f'''
from enum import IntEnum
class State(IntEnum):
    ONE = 1
    {body}
def main() -> str:
    return repr(State.ONE)
''')


def test_enum_constants_optional_values_and_explicit_widening(tmp_path):
    LLVM().assert_matches_python('''
import enum as enums
class IntEnum:
    pass
class State(enums.IntEnum):
    ZERO = 0
    ONE = 1
class Label(enums.StrEnum):
    EMPTY = ''
    ONE = 'one'
MEMBER = State.ONE
def display(state: State | None, label: Label | None) -> str:
    return f'{state!r}:{label!r}'
def ordinary(state: int, label: str) -> str:
    return f'{state!r}:{label!r}'
def same(a: State | None, b: State | None) -> str:
    return str(a is b)
def same_label(a: Label | None, b: Label | None) -> str:
    return str(a is b)
def main() -> str:
    return '|'.join((display(MEMBER, Label.ONE), display(State.ZERO, Label.EMPTY),
                     display(None, None), ordinary(int(State.ONE), str(Label.ONE)),
                     same(None, State.ONE), same(State.ONE, State.ONE), same(None, None),
                     same_label(None, Label.EMPTY), same_label(Label.EMPTY, Label.EMPTY),
                     same_label(None, None)))
''', directory=tmp_path)


@pytest.mark.parametrize("expression,return_type", [
    ("State(1) == State.ONE", "bool"),
    ("len(State.ONE.name)", "int"),
    ("len(Label.ONE)", "int"),
    ("Label.ONE < Label.TWO", "bool"),
    ("State.ONE == 1", "bool"),
])
def test_isolated_enum_operations_prepare_their_runtime(tmp_path, expression, return_type):
    result = f"1 if ({expression}) else 0" if return_type == "bool" else expression
    LLVM().assert_matches_python(f'''
from enum import IntEnum, StrEnum
class State(IntEnum):
    ONE = 1
class Label(StrEnum):
    ONE = '✓'
    TWO = 'z'
def main() -> int:
    return {result}
''', directory=tmp_path)


def test_enum_mapping_keys_and_constructor_bool_failure(tmp_path):
    LLVM().assert_matches_python('''
from enum import IntEnum, StrEnum
class State(IntEnum):
    ONE = 1
    ALIAS = 1
    TWO = 2
class Label(StrEnum):
    ONE = 'one'
    ALIAS = 'one'
    TWO = 'two'
def main() -> str:
    states: dict[State, str] = {State.ONE: 'first', State.TWO: 'second'}
    labels: dict[Label, int] = {Label.ONE: 1, Label.TWO: 2}
    states[State.ALIAS] = 'updated'
    labels[Label.ALIAS] = 3
    labels.setdefault(Label.TWO, 4)
    members: set[State] = set()
    members.add(State.ONE)
    scalar_keys: dict[str, int] = {'one': 5}
    scalar_values: set[int] = {1}
    print(repr(members), scalar_keys[Label.ONE], State.ONE in scalar_values)
    message = ''
    try:
        State(False)
    except ValueError as error:
        message = str(error)
    return f'{states!r}|{labels!r}|{message}|{sorted([State.TWO, State.ONE])!r}'
''', directory=tmp_path)


@pytest.mark.parametrize("definition,expected", [
    ("class State(IntEnum):\n    ONE = 9223372036854775808", "must fit signed i64"),
    ("class Base(IntEnum):\n    def __str__(self) -> str:\n        return 'changed'\nclass State(Base):\n    ONE = 1", "custom behavior"),
    ("class State(IntEnum):\n    ONE = 1\nState.ONE._value_ = 2", "unchanged underlying values"),
    ("class State(IntEnum):\n    ONE = 1\nState.ONE._add_value_alias_(9)", "post-definition value aliases"),
    ("class State(IntEnum):\n    ONE = 1\n    name = 2", "cannot shadow name/value"),
    ("class State(IntEnum):\n    ONE = 1\n    value = 2", "cannot shadow name/value"),
])
def test_enum_definition_boundaries(definition, expected):
    with pytest.raises(CompilationError, match=expected):
        transpile_llvm(f'from enum import IntEnum\n{definition}\ndef main() -> str:\n    return repr(State.ONE)\n')


def test_enum_union_and_cast_do_not_invent_member_identity():
    prefix = 'from enum import IntEnum\nclass State(IntEnum):\n    ONE = 1\n'
    with pytest.raises(LLVMUnsupported, match="no concrete runtime tag"):
        transpile_llvm(prefix + '''
def display(value: State | str) -> str:
    return repr(value)
def main() -> str:
    return display(State.ONE)
''')
    with pytest.raises(LLVMUnsupported, match="concrete casts require matching types"):
        transpile_llvm(prefix + '''
from typing import cast
def main() -> str:
    return repr(cast(State, 42))
''')


@pytest.mark.parametrize("base,value", [("IntEnum", "1"), ("StrEnum", "'a'")])
def test_enum_host_boundary_and_defaults_are_explicit(base, value):
    prefix = f'from enum import {base}\nclass State({base}):\n    ONE = {value}\n'
    with pytest.raises(LLVMUnsupported, match="library enum values require scalar inputs/outputs"):
        transpile_llvm(prefix + 'def main(value: State) -> str:\n    return repr(value)\n', target="library")
    with pytest.raises(LLVMUnsupported, match="immutable constant"):
        transpile_llvm(prefix + '''
def display(value: State = State.ONE) -> str:
    return repr(value)
def main() -> str:
    return display()
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_enum_format_and_constructor_allocation_recovery(tmp_path, optimize):
    source = transpile_llvm('''
from enum import IntEnum, StrEnum
from pyjs.native import gc_collect, gc_count
from tests.native.allocation_support import arm, remaining
class State(IntEnum):
    READY = 9223372036854775807
    ALIAS = 9223372036854775807
class Label(StrEnum):
    READY = "a'\\n✓"
    ALIAS = "a'\\n✓"
def render(mode: int) -> str:
    if mode == 0:
        return repr(State.ALIAS)
    if mode == 1:
        return repr(Label.ALIAS)
    if mode == 2:
        return repr([State.READY])
    if mode == 3:
        return f'{Label.READY!r}'
    try:
        if mode == 4:
            State(0)
        else:
            Label('missing')
    except ValueError as error:
        return str(error)
    return 'unexpected'
def main() -> int:
    mode = 0
    while mode < 6:
        expected = render(mode)
        arm(1000)
        probe = render(mode)
        stages = 1000 - remaining()
        arm(0)
        if probe != expected or (mode >= 2 and stages < 1):
            return 1
        if mode < 2 and stages != 0:
            return 2
        failure = 1
        while failure <= stages:
            result = 'unchanged'
            caught = False
            arm(failure)
            try:
                result = render(mode)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or result != 'unchanged' or gc_count() != 0:
                return 3
            if render(mode) != expected:
                return 4
            failure += 1
        mode += 1
    return 0
''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
