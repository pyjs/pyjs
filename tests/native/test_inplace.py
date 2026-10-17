import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM

UNION_BINARY_SOURCE = '''
from pyjs.native import gc_collect, gc_set_threshold
class A:
    def __init__(self, value: int):
        self.value = value
    def __add__(self, other: int) -> "A | B":
        gc_collect()
        return A(self.value + other)
class B:
    def __init__(self, value: int):
        self.value = value
    def __add__(self, other: int) -> "A | B":
        gc_collect()
        return B(self.value + other * 10)
class BinaryChild(A):
    def __add__(self, other: int) -> A | B:
        return A(self.value + other * 100)
class InplaceChild(A):
    def __iadd__(self, other: int) -> A | B:
        self.value += other
        return self
def update(item: A | B) -> str:
    alias = item
    item += 2
    return str(item.value) + ":" + str(alias.value) + ":" + str(item is alias)
def main() -> str:
    gc_set_threshold(1)
    return update(A(1)) + ";" + update(B(1)) + ";" + update(LAST(1))
'''


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_receiver_without_inplace_methods_keeps_binary_fallback(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(
        UNION_BINARY_SOURCE.replace("LAST", "BinaryChild"), directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"),
    )
    assert comparison.native.stdout == "3:1:False;21:1:False;201:1:False"
    assert comparison.native.stderr == ""


def test_union_fallback_checks_late_reached_inplace_subclass():
    with pytest.raises(LLVMUnsupported, match="union receivers with in-place methods require narrowing.*at line"):
        transpile_llvm(UNION_BINARY_SOURCE.replace("LAST", "InplaceChild"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("alias", ["direct", "inherited", "introduced"])
def test_union_binary_aliases_preserve_the_selected_function(tmp_path, optimize, alias):
    source = UNION_BINARY_SOURCE
    if alias != "introduced":
        source = source.replace("class B:", "    __iadd__ = __add__\nclass B:")
    if alias == "inherited":
        source = source.replace("class InplaceChild", "class AliasChild(A):\n    pass\nclass InplaceChild")
    if alias == "introduced":
        source = source.replace("class InplaceChild", "    __iadd__ = __add__\nclass InplaceChild")
    source = source.replace("LAST", {"direct": "A", "inherited": "AliasChild", "introduced": "BinaryChild"}[alias])
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    last = "201" if alias == "introduced" else "3"
    assert comparison.native.stdout == f"3:1:False;21:1:False;{last}:1:False"
    assert comparison.native.stderr == ""


def test_union_alias_cannot_silently_select_a_runtime_binary_override():
    source = UNION_BINARY_SOURCE.replace("class B:", "    __iadd__ = __add__\nclass B:")
    with pytest.raises(LLVMUnsupported, match="union receivers with in-place methods require narrowing"):
        transpile_llvm(source.replace("LAST", "BinaryChild"))


def test_union_alias_cannot_silently_select_a_static_binary_override():
    source = UNION_BINARY_SOURCE.replace("class B:", "    __iadd__ = __add__\nclass B:")
    source = source.replace("def update(item: A | B)", "def update(item: BinaryChild | B)")
    source = source.replace("update(A(1))", "update(BinaryChild(1))").replace("LAST", "BinaryChild")
    with pytest.raises(CompilationError, match="union in-place aliases must match their selected binary methods"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_fallback_ignores_annotation_only_inplace_subclasses(tmp_path, optimize):
    source = UNION_BINARY_SOURCE.split("def main()", 1)[0] + '''
class Box:
    def __init__(self):
        self.note: InplaceChild | None = None
def peek(note: InplaceChild | None) -> int:
    return 0 if note is None else 1
def main() -> str:
    gc_set_threshold(1)
    pending: list[InplaceChild] = []
    note: InplaceChild | None = None
    box = Box()
    return (update(A(1)) + ";" + update(B(1)) + ";" + str(len(pending))
            + ":" + str(note is None) + ":" + str(peek(None)) + ":" + str(box.note is None))
'''
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "3:1:False;21:1:False;0:True:0:True"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("declaration", ["local", "inherited", "introduced"])
def test_binary_method_alias_keeps_inplace_identity_and_dispatch(tmp_path, optimize, declaration):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold
class Base:
    def __init__(self, value: int):
        self.value = value
    def __add__(self, other: int) -> "Base":
        gc_collect()
        return Base(self.value + other)
    BASE_ALIAS
class Child(Base):
    CHILD_ALIAS
    def __add__(self, other: int) -> Base:
        return Base(self.value + other + 100)
def update(item: Base) -> str:
    alias = item
    item += 5
    return str(item.value) + ":" + str(alias.value) + ":" + str(item is alias)
def main() -> str:
    gc_set_threshold(1)
    MAIN
'''.replace("BASE_ALIAS", "__iadd__ = __add__" if declaration != "introduced" else "pass").replace(
        "CHILD_ALIAS", "__iadd__ = Base.__add__" if declaration == "introduced" else "pass").replace(
        "MAIN", "item = Base(1)\n    alias = item\n    item += 5\n    return str(item.value) + ':' + str(alias.value) + ':' + str(item is alias)"
        if declaration == "local" else "return update(Base(1)) + ';' + update(Child(2))")
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stdout == ("6:1:False" if declaration == "local" else "6:1:False;7:2:False")
    assert comparison.native.stderr == ""


def test_inplace_alias_does_not_silently_use_reflected_fallback():
    with pytest.raises(CompilationError, match="in-place alias must match the statically selected binary method"):
        transpile_llvm('''
            class Base:
                def __add__(self, other: "Base") -> "Base":
                    return self
                __iadd__ = __add__
            class Child(Base):
                def __radd__(self, other: Base) -> Base:
                    return self
            def main() -> int:
                left = Base()
                left += Child()
                return int(left is left)
        ''')


def test_arbitrary_inplace_method_alias_has_an_alias_specific_diagnostic():
    with pytest.raises(LLVMUnsupported, match="in-place aliases must reference an analyzed binary method.*at line"):
        transpile_llvm('''
            class Item:
                def add(self, other: int) -> "Item":
                    return self
                __iadd__ = add
            def main() -> int:
                item = Item()
                item += 1
                return int(item is item)
        ''')


@pytest.mark.parametrize("operator, method", [
    ("+", "add"), ("-", "sub"), ("*", "mul"), ("/", "truediv"),
    ("//", "floordiv"), ("%", "mod"), ("**", "pow"), ("<<", "lshift"),
    (">>", "rshift"), ("&", "and"), ("|", "or"), ("^", "xor"),
])
def test_application_inplace_operator_preserves_aliases_without_binary_method(tmp_path, operator, method):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold

class Acc:
    def __init__(self, value: int):
        self.value = value
    def __iMETHOD__(self, other: int) -> "Acc":
        gc_collect()
        self.value += other
        return self

def main() -> str:
    gc_set_threshold(1)
    value = Acc(2)
    alias = value
    value OP= 5
    return str(alias.value) + ":" + str(value is alias)
'''.replace("METHOD", method).replace("OP", operator)
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=2,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "7:True"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_inplace_override_and_binary_fallback(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Acc:
            def __init__(self, value: int):
                self.value = value
            def __add__(self, other: int) -> "Acc":
                return Acc(self.value + other + 100)
        class Mutating(Acc):
            def __iadd__(self, other: int) -> Acc:
                gc_collect()
                self.value += other
                return self
        class Replacing(Mutating):
            def __iadd__(self, other: int) -> Acc:
                gc_collect()
                return Acc(self.value + other + 200)

        def update(value: Acc) -> str:
            alias = value
            value += 5
            return str(alias.value) + ":" + str(value.value) + ":" + str(alias is value)
        def main() -> str:
            gc_set_threshold(1)
            return update(Acc(1)) + ";" + update(Mutating(2)) + ";" + update(Replacing(3))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "1:106:False;7:7:True;3:208:False"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_reflected_fallback_and_introduced_inplace_preserve_lifetimes(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Right:
            def __init__(self, value: int):
                self.value = value
            def __radd__(self, other: "Left") -> "Left":
                gc_collect()
                return Left(other.value + self.value + 100)
        class Left:
            def __init__(self, value: int):
                self.value = value
                self.saved: Right | None = None
        class Mutating(Left):
            def __iadd__(self, other: Right) -> Left:
                self.saved = other
                self.value += other.value
                gc_collect()
                return self

        def update(value: Left, other: Right) -> Left:
            value += other
            return value
        def build(mutating: bool) -> Left:
            value: Left = Mutating(1) if mutating else Left(2)
            return update(value, Right(5))
        def main() -> str:
            gc_set_threshold(1)
            first = build(True)
            second = build(False)
            gc_collect()
            saved = first.saved
            assert isinstance(saved, Right)
            return str(first.value) + ":" + str(second.value) + ":" + str(saved.value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "6:107:5"
    assert comparison.native.stderr == ""


def test_inplace_accepts_none_operand_and_return(tmp_path):
    comparison = LLVM().assert_matches_python('''
        class Item:
            def __init__(self):
                self.value = 1
            def __iadd__(self, other: None) -> None:
                self.value = 5
        def main() -> str:
            item: Item | None = Item()
            assert isinstance(item, Item)
            alias = item
            item += None
            return str(item is None) + ":" + str(alias.value)
    ''', directory=tmp_path, optimize=2, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "True:5"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_inplace_replacement_crosses_erased_result_boundary(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int):
                self.value = value
        class Base:
            def __add__(self, other: int) -> object:
                return self
        class Child(Base):
            def __iadd__(self, other: int) -> Box:
                gc_collect()
                return Box(other)
        def main() -> str:
            gc_set_threshold(1)
            item: object = Child()
            assert isinstance(item, Base)
            item += 7
            gc_collect()
            assert isinstance(item, Box)
            return str(item.value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stdout == "7"
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("numeric, value", [("int8", "120"), ("int64", "36028797018963969")])
def test_inplace_portable_operands_do_not_mutate_shared_type_metadata(tmp_path, numeric, value):
    integer = NATIVE_ENVIRONMENT.builtins.search("int")._self
    original = integer.representation
    source = '''
from pyjs import NUMERIC
class Acc:
    def __init__(self):
        self.value = 1
    def __iadd__(self, other: NUMERIC) -> "Acc":
        self.value += int(other)
        return self
def main() -> str:
    item = Acc()
    item += NUMERIC(VALUE)
    ordinary = 300
    ordinary += 23
    return str(item.value) + ":" + str(ordinary)
'''.replace("NUMERIC", numeric).replace("VALUE", value)
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=2,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert integer.representation == original


@pytest.mark.parametrize("operand, result, expression, message", [
    ("str", "Acc", "self", "operand must preserve"),
    ("int8", "Acc", "self", "operand must preserve"),
    ("int", "int", "1", "result must preserve"),
])
def test_runtime_inplace_signature_mismatch_has_a_located_diagnostic(operand, result, expression, message):
    source = '''
from pyjs import int8
class Acc:
    def __add__(self, other: int) -> "Acc":
        return self
class Child(Acc):
    def __iadd__(self, other: OPERAND) -> RESULT:
        return EXPRESSION
def update(value: Acc) -> Acc:
    value += 1
    return value
def main() -> int:
    value = Child()
    return int(update(value) is value)
'''.replace("OPERAND", operand).replace("RESULT", result).replace("EXPRESSION", expression)
    with pytest.raises(LLVMUnsupported, match=message + ".*at line"):
        transpile_llvm(source)


def test_matrix_augmented_assignment_reports_the_unsupported_operator():
    with pytest.raises(CompilationError, match="LLVM augmented assignment does not support MatMult"):
        transpile_llvm('''
            class Item:
                def __imatmul__(self, other: int) -> "Item":
                    return self
            def main() -> int:
                item = Item()
                item @= 1
                return int(item is item)
        ''')


@pytest.mark.parametrize("definition, message", [
    ("__iadd__ = None", "in-place operators require an ordinary application method"),
    ('def __iadd__(self, *items: int) -> "Item":\n        return self',
     "in-place methods require exactly one fixed operand parameter"),
    ('def __iadd__(self, other: int) -> object:\n        return NotImplemented',
     "NotImplemented"),
])
def test_unsupported_inplace_protocols_are_diagnosed(definition, message):
    source = '''
class Item:
    DEFINITION
    def __add__(self, other: int) -> "Item":
        return self
def main() -> int:
    item = Item()
    item += 1
    return int(item is item)
'''.replace("DEFINITION", definition)
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm(source)


def test_union_inplace_requires_narrowing():
    with pytest.raises(CompilationError, match="augmented assignment requires a concrete receiver type"):
        transpile_llvm('''
            class Left:
                def __iadd__(self, other: int) -> "Left":
                    return self
            class Right:
                def __iadd__(self, other: int) -> "Right":
                    return self
            def update(item: Left | Right) -> Left | Right:
                item += 1
                return item
            def main() -> int:
                return int(update(Left()) is update(Right()))
        ''')


@pytest.mark.parametrize("has_base_inplace", [False, True])
def test_runtime_subclass_cannot_silently_disable_inplace_method(has_base_inplace):
    source = '''
class Base:
    BASE_INPLACE
    def __add__(self, other: int) -> "Base":
        return self
class Child(Base):
    __iadd__ = None
def update(value: Base) -> Base:
    value += 1
    return value
def main() -> int:
    item = Child()
    return int(update(item) is item)
'''.replace("BASE_INPLACE", 'def __iadd__(self, other: int) -> "Base":\n        return self' if has_base_inplace else "pass")
    with pytest.raises(LLVMUnsupported, match="in-place operators require an ordinary application method.*at line"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("target", ["field", "property", "index", "super"])
def test_inplace_target_order_and_partial_mutation_on_failed_writeback(tmp_path, optimize, target):
    source = '''
from pyjs.native import gc_collect, gc_set_threshold

class Acc:
    def __init__(self, events: list[str]):
        self.events = events
        self.value = 1
    def __iadd__(self, other: int) -> "Acc":
        self.events.append("inplace")
        self.value += other
        gc_collect()
        return self
    def __add__(self, other: int) -> "Acc":
        raise AssertionError("ordinary add must not run")

class Holder:
    def __init__(self):
        self.events: list[str] = []
        self.item = Acc(self.events)
        self.items: list[Acc] = [self.item]
    @property
    def value(self) -> Acc:
        self.events.append("get")
        return self.item
    @value.setter
    def value(self, item: Acc) -> None:
        self.events.append("set")
        raise ValueError("setter failed")
    def receiver(self) -> "Holder":
        self.events.append("receiver")
        return self
    def index(self) -> int:
        self.events.append("index")
        return 0
    def rhs(self, fail: bool) -> int:
        self.events.append("rhs")
        gc_collect()
        if fail:
            raise ValueError("rhs failed")
        return 5

class Child(Holder):
    def update(self, fail: bool) -> str:
        try:
            TARGET += self.rhs(fail)
        except AttributeError:
            self.events.append("attribute")
        except ValueError as error:
            self.events.append(str(error))
        finally:
            self.events.append("finally")
        return str(self.item.value) + ":" + str(self.events)

def main() -> str:
    gc_set_threshold(1)
    return Child().update(False) + ";" + Child().update(True)
'''.replace("TARGET", {
        "field": "self.receiver().item", "property": "self.receiver().value",
        "index": "self.receiver().items[self.index()]", "super": "super().value",
    }[target])
    comparison = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                              sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
