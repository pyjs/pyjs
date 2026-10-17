import re

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("operator, method", [
    ("+", "add"), ("-", "sub"), ("*", "mul"), ("/", "truediv"),
    ("//", "floordiv"), ("%", "mod"), ("**", "pow"), ("<<", "lshift"),
    (">>", "rshift"), ("&", "and"), ("|", "or"), ("^", "xor"),
])
def test_runtime_binary_operator_matrix(tmp_path, operator, method):
    source = '''
class Base:
    def __OP__(self, other: "Base") -> int:
        return 1
class Child(Base):
    def __rOP__(self, other: Base) -> int:
        return 2
def operate(left: Base, right: Base) -> int:
    return left SYMBOL right
def main() -> str:
    return (str(operate(Base(), Base())) + str(operate(Base(), Child()))
            + str(operate(Child(), Base())) + str(operate(Child(), Child())))
'''.replace("OP", method).replace("SYMBOL", operator)
    comparison = LLVM().assert_matches_python(source, directory=tmp_path,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "1211"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_binary_methods_precede_static_reflected_fallback(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Left:
            def __init__(self, value: int):
                self.value = value
        class Right:
            def __init__(self, value: int):
                self.value = value
            def __radd__(self, other: Left) -> Left:
                gc_collect()
                return Left(other.value + self.value + 100)
        class Child(Left):
            def __add__(self, other: Right) -> Left:
                gc_collect()
                return Left(self.value + other.value + 1000)
        def ordinary(left: Left, right: Right) -> int:
            return (left + right).value
        def augmented(left: Left, right: Right) -> int:
            left += right
            return left.value
        def main() -> str:
            gc_set_threshold(1)
            return (str(ordinary(Left(3), Right(4))) + ':'
                    + str(ordinary(Child(3), Right(4))) + ':'
                    + str(augmented(Left(3), Right(4))) + ':'
                    + str(augmented(Child(3), Right(4))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "107:1007:107:1007"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_reflection_uses_strict_subtype_priority(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        class Base:
            def __init__(self, value: int):
                self.value = value
            def __add__(self, other: "Base") -> int:
                return self.value + other.value
        class Child(Base):
            def __radd__(self, other: Base) -> int:
                return other.value + self.value + 1000
        class Grandchild(Child):
            pass
        def add(left: Base, right: Base) -> int:
            return left + right
        def main() -> str:
            return (str(add(Base(1), Child(2))) + ':'
                    + str(add(Child(1), Child(2))) + ':'
                    + str(add(Base(1), Grandchild(2))) + ':'
                    + str(add(Child(1), Grandchild(2))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "1003:3:1003:3"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_binary_callbacks_keep_captured_operands_and_exception_order(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __init__(self, value: int, events: list[str]):
                self.value = value
                self.events = events
            def __add__(self, other: "Base") -> int:
                self.events.append('add')
                return self.value + other.value
        class Child(Base):
            def __radd__(self, other: Base) -> int:
                self.events.append('reflect')
                gc_collect()
                other.value += 10
                if self.value < 0:
                    raise ValueError('negative')
                return other.value + self.value
        def left(pool: list[Base], events: list[str]) -> Base:
            events.append('left')
            return pool[0]
        def right(pool: list[Base], events: list[str], value: int) -> Base:
            events.append('right')
            pool.clear()
            gc_collect()
            return Child(value, events)
        def run(value: int) -> str:
            events: list[str] = []
            pool: list[Base] = [Base(1, events)]
            try:
                result = str(left(pool, events) + right(pool, events, value))
            except ValueError as error:
                result = str(error)
            return result + ':' + ','.join(events) + ':' + str(len(pool))
        def main() -> str:
            gc_set_threshold(1)
            return run(2) + ';' + run(-1)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "13:left,right,reflect:0;negative:left,right,reflect:0"
    assert comparison.native.stderr == ""


def test_runtime_binary_none_returns_and_annotation_only_subclasses(tmp_path):
    comparison = LLVM().assert_matches_python('''
        class Base:
            def __add__(self, other: "Base") -> None:
                pass
        class Child(Base):
            def __radd__(self, other: Base) -> None:
                pass
        class Unused(Base):
            __radd__ = None
        def operate(left: Base, right: Base) -> bool:
            return (left + right) is None
        def main() -> str:
            unused: list[Unused] = []
            return str(operate(Base(), Base())) + ':' + str(operate(Base(), Child())) + ':' + str(len(unused))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "True:True:0"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("return_type, body, message", [
    ("str", "return 'text'", "result must preserve its analyzed type"),
    ("int8", "return int8(2)", "result must preserve its numeric representation"),
])
def test_runtime_reflected_result_cannot_change_analyzed_storage(return_type, body, message):
    source = '''
from pyjs.numeric import int8
class Base:
    def __add__(self, other: "Base") -> int:
        return 1
class Child(Base):
    def __radd__(self, other: Base) -> RETURN:
        BODY
def operate(left: Base, right: Base) -> int:
    return left + right
def main() -> int:
    return operate(Base(), Child())
'''.replace("RETURN", return_type).replace("BODY", body)
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(source)


def test_reflected_priority_is_checked_before_disabled_ordinary_method(tmp_path):
    comparison = LLVM().assert_matches_python('''
        class Base:
            def __add__(self, other: "Base") -> int:
                return 1
        class Disabled(Base):
            __add__ = None
        class Reflected(Disabled):
            def __radd__(self, other: Base) -> int:
                return 9
        def operate(left: Base, right: Base) -> str:
            try:
                return str(left + right)
            except TypeError as error:
                return str(error)
        def main() -> str:
            return (operate(Disabled(), Base()) + ';' + operate(Disabled(), Reflected())
                    + ';' + operate(Base(), Disabled()))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "'NoneType' object is not callable;9;1"
    assert comparison.native.stderr == ""


def test_static_binary_inline_lowering_remains_available(tmp_path):
    comparison = LLVM().assert_matches_python('''
        from pyjs import llvm
        class Item:
            def __init__(self, value: int):
                self.value = value
            @llvm.inline("{self}")
            def __add__(self, other: "Item") -> "Item":
                return self
        def main() -> str:
            left = Item(7)
            result = left + Item(8)
            return str(result.value) + ':' + str(result is left)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "7:True"
    assert comparison.native.stderr == ""


def test_empty_inline_operator_keeps_its_existing_argument_omission(tmp_path):
    # This explicit native escape intentionally differs from CPython. Preserve
    # the established operator lowering: receiver evaluated, operand omitted.
    result = LLVM().run_source('''
        from pyjs import llvm
        class Item:
            @llvm.inline("")
            def __add__(self, other: "Item") -> None:
                pass
        def make(events: list[str], label: str) -> Item:
            events.append(label)
            return Item()
        def main() -> str:
            events: list[str] = []
            make(events, 'left') + make(events, 'right')
            return ','.join(events)
    ''', directory=tmp_path)
    assert result.returncode == 0
    assert result.stdout == "left"
    assert result.stderr == ""


@pytest.mark.parametrize("storage", ["object", "int | str"])
def test_binary_arms_project_overloaded_results_once(tmp_path, storage):
    source = '''
from typing import overload
class Base:
    @overload
    def __add__(self, other: "Base") -> int: ...
    @overload
    def __add__(self, other: int) -> str: ...
    def __add__(self, other: "Base | int") -> STORAGE:
        return str(other) if isinstance(other, int) else 42
class Child(Base):
    def __radd__(self, other: Base) -> int:
        return 99
def operate(left: Base, right: Base) -> str:
    return str(left + right)
def main() -> str:
    return operate(Base(), Base()) + ':' + operate(Base(), Child())
'''.replace("STORAGE", storage)
    comparison = LLVM().assert_matches_python(source, directory=tmp_path,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "42:99"
    assert comparison.native.stderr == ""


def test_runtime_reflected_alias_requires_analyzed_protocol_declaration():
    # An alias has no independent declaration/effect binding yet. Do not
    # directly call its target with reversed operands but forward lifetimes.
    with pytest.raises(LLVMUnsupported, match="binary aliases require an analyzed protocol declaration"):
        transpile_llvm('''
        class Base:
            def __init__(self, value: int):
                self.value = value
            def __sub__(self, other: "Base") -> int:
                return self.value - other.value
        class Child(Base):
            __rsub__ = Base.__sub__
        def subtract(left: Base, right: Base) -> int:
            return left - right
        def main() -> str:
            return str(subtract(Base(10), Child(3))) + ':' + str(subtract(Child(10), Child(3)))
        ''')


def test_same_class_does_not_fall_back_to_reflected_method(tmp_path):
    comparison = LLVM().assert_matches_python('''
        class Only:
            def __radd__(self, other: "Only") -> int:
                return 1
        def main() -> str:
            try:
                return str(Only() + Only())
            except TypeError as error:
                return str(error)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "unsupported operand type(s) for +: 'Only' and 'Only'"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("inline", [False, True])
def test_runtime_binary_alias_and_inline_diagnostics(inline):
    declaration = ('''@llvm.inline("{other}")
    def __radd__(self, other: Base) -> Base:
        return other''' if inline else '''def __add__(self, other: Base) -> Base:
        return self
    __radd__ = __add__''')
    source = '''
from pyjs import llvm
class Base:
    def __add__(self, other: "Base") -> "Base":
        return self
class Child(Base):
    DECLARATION
def operate(left: Base, right: Base) -> Base:
    return left + right
def main() -> bool:
    left = Base()
    return operate(left, Child()) is left
'''.replace("DECLARATION", declaration)
    message = ("binary inline overrides are not supported" if inline else
               "binary aliases require an analyzed protocol declaration")
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(source)


@pytest.mark.parametrize("subclasses", [2, 32])
def test_inherited_binary_dispatch_does_not_grow_with_class_pairs(tmp_path, subclasses):
    children = "\n".join(f"class Child{i}(Base):\n    pass" for i in range(subclasses))
    instances = ", ".join(f"Child{i}()" for i in range(subclasses))
    source = f'''
class Base:
    def __add__(self, other: "Base") -> int:
        return 1
{children}
def operate(left: Base, right: Base) -> int:
    return left + right
def main() -> int:
    values: list[Base] = [{instances}]
    result = 0
    for left in values:
        for right in values:
            result += operate(left, right)
    return result % 251
'''
    ir = transpile_llvm(source)
    # Whole-module IR includes the runtime and constructor/vtable scaffolding
    # for every class. Inspect only this operator's otherwise unvarying body.
    body = re.search(r"define [^\n]*@[^\n]*operate[^\n]*\{(.*?)\n\}", ir, re.S)
    assert body is not None
    assert "protocol.class" not in body[1]
    assert len(re.findall(r"call i64 @[^\n]*__add__", body[1])) == 1
    comparison = LLVM().assert_matches_python(source, directory=tmp_path,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.returncode == subclasses ** 2 % 251
    assert comparison.native.stderr == ""


def test_grouped_binary_dispatch_keeps_class_specific_error_names(tmp_path):
    comparison = LLVM().assert_matches_python('''
        class Base:
            def __radd__(self, other: "Base") -> int:
                return 7
        class First(Base):
            pass
        class Second(Base):
            pass
        def operate(left: Base, right: Base) -> str:
            try:
                return str(left + right)
            except TypeError as error:
                return str(error)
        def main() -> str:
            return (operate(First(), First()) + ';' + operate(Second(), Second())
                    + ';' + operate(First(), Second()) + ';' + operate(Second(), First()))
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == (
        "unsupported operand type(s) for +: 'First' and 'First';"
        "unsupported operand type(s) for +: 'Second' and 'Second';7;7")
    assert comparison.native.stderr == ""
