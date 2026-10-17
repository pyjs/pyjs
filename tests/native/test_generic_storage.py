"""Generic records own concrete fields; aliases cannot change that layout."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM

BOX = '''
class Box[T]:
    def __init__(self, value: T):
        self.value = value
'''


@pytest.mark.parametrize("boundary", ["call", "return", "assignment", "cast", "subclass", "nested", "union"])
def test_generic_scalar_storage_cannot_be_reinterpreted(boundary):
    cases = {
        "call": '''
def main() -> int:
    return read(Box[bool](True))
''',
        "return": '''
def create() -> Box[int]:
    return Box[bool](True)
def main() -> int:
    return read(create())
''',
        "assignment": '''
def main() -> int:
    original = Box[bool](True)
    alias: Box[int] = original
    return read(alias)
''',
        "cast": '''
from typing import cast
def main() -> int:
    original = Box[bool](True)
    return read(cast(Box[int], original))
''',
        "subclass": '''
class Child(Box[bool]):
    pass
def main() -> int:
    return read(Child(True))
''',
        "nested": '''
def consume(value: Box[Box[int]]) -> int:
    return read(value.value)
def main() -> int:
    return consume(Box[Box[bool]](Box[bool](True)))
''',
        "union": '''
def consume(value: Box[int] | str) -> int:
    return 0 if isinstance(value, str) else read(value)
def main() -> int:
    return consume(Box[bool](True))
''',
    }
    # Ordinary subclasses with incompatible bases are already rejected by
    # shared analysis, before native layout validation is reached.
    error = CompilationError if boundary == "subclass" else LLVMUnsupported
    # pytest appends exception notes after the diagnostic's first line.
    message = ("expects Box\\[int\\], got Child" if boundary == "subclass"
               else r"(?m)^LLVM generic object views require matching type arguments .* at line \d+$")
    with pytest.raises(error, match=message):
        transpile_llvm(BOX + '''
def read(value: Box[int]) -> int:
    return value.value + 40
''' + cases[boundary])


@pytest.mark.parametrize("custom", [False, True], ids=["application", "custom-element"])
def test_erased_generic_payload_cannot_mutate_a_concrete_alias(custom):
    imports = "from pyjs.web.domx import CustomElement\n" if custom else ""
    base = "(CustomElement)" if custom else ""
    with pytest.raises(LLVMUnsupported, match="generic object views require matching type arguments"):
        transpile_llvm(imports + BOX + f'''
class Item{base}:
    def __init__(self):
        self.name = "item"
class Other:
    def __init__(self):
        self.number = 1
def replace(value: Box[object]) -> None:
    value.value = Other()
def main() -> str:
    original = Box[Item](Item())
    replace(original)
    return original.value.name
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_aliases_explicit_copies_and_union_views(tmp_path, optimize):
    result = LLVM().assert_matches_python(BOX + '''
from pyjs.native import gc_collect, gc_set_threshold

class Child(Box[int]):
    pass

def update(value: Box[int]) -> None:
    gc_collect()
    value.value += 10

def read(value: Box[int] | Box[bool]) -> int:
    gc_collect()
    return int(value.value) + 40

def reverse(value: Box[bool] | Box[int]) -> int:
    gc_collect()
    return int(value.value) + 40

def erase(value: Box[object], replacement: object) -> None:
    value.value = replacement
    gc_collect()

def main() -> str:
    gc_set_threshold(1)
    original = Box[bool](True)
    copy = Box[int](int(original.value))
    alias: Box[int] = copy
    update(alias)
    child = Child(2)
    update(child)
    erased = Box[object](original)
    erase(erased, child)
    return repr((original.value, copy.value, alias is copy,
                 read(original), read(copy), read(child),
                 reverse(original), reverse(copy), reverse(child), erased.value is child))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_inherited_scalar_storage_error_has_constructor_location():
    with pytest.raises(LLVMUnsupported, match=r"LLVM field Child.value changes type at line 3$"):
        transpile_llvm('''
class Base:
    def __init__(self):
        self.value = 1
class Child(Base):
    def __init__(self):
        self.value = True
def main() -> int:
    return Base().value + int(Child().value)
''')


@pytest.mark.parametrize("boundary", ["parameter", "field"])
@pytest.mark.parametrize("shape", ["tuple[Item]", "tuple[Item, ...]", "tuple[tuple[Item]]"])
def test_tuple_declarations_cannot_narrow_inherited_storage(boundary, shape):
    child_shape = shape.replace("Item", "Child")
    nested = shape == "tuple[tuple[Item]]"
    index = "[0][0]" if nested else "[0]"
    item = "((Item(3),),)" if nested else "(Item(3),)"
    child = "((Child(3),),)" if nested else "(Child(3),)"
    declarations = f'''
class Base:
    def total(self, items: {shape}) -> int:
        return items{index}.value
class Sub(Base):
    def total(self, items: {child_shape}) -> int:
        return items{index}.extra
def main() -> int:
    Child(9)
    box: Base = Sub()
    return box.total({item})
''' if boundary == "parameter" else f'''
class Base:
    def __init__(self):
        self.items: {shape} = {item}
class Sub(Base):
    def __init__(self):
        super().__init__()
        self.items: {child_shape} = {child}
    def total(self) -> int:
        return self.items{index}.extra
def main() -> int:
    box = Sub()
    base: Base = box
    base.items = {item}
    return box.total()
'''
    with pytest.raises(LLVMUnsupported, match="tuple views require matching concrete item storage"):
        transpile_llvm('''
class Item:
    def __init__(self, value: int): self.value = value
class Child(Item):
    def __init__(self, value: int):
        super().__init__(value)
        self.extra = 5
''' + declarations)


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_declarations_preserve_safe_value_flow(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Item:
    def __init__(self, value: int): self.value = value
class Child(Item):
    def __init__(self, value: int):
        super().__init__(value)
        self.extra = 5
class Base:
    def __init__(self):
        self.items: tuple[Item, ...] = (Item(1),)
    def total(self, items: tuple[Child, ...]) -> int:
        return items[0].extra
    def make(self) -> tuple[Item, ...]: return (Item(2),)
class Sub(Base):
    def __init__(self):
        super().__init__()
        self.items: tuple[Item, ...] = (Child(3),)
    def total(self, items: tuple[Item, ...]) -> int:
        gc_collect()
        return items[0].value
    def make(self) -> tuple[Child, ...]: return (Child(4),)
def main() -> str:
    gc_set_threshold(1)
    box = Sub()
    base: Base = box
    base.items = (Item(8),)
    gc_collect()
    return str((base.total((Child(6),)), box.total((Item(7),)),
                base.make()[0].value, box.items[0].value,
                Base().total((Child(9),))))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("outer", "value", "read"), [
    ("list[{item}]", "[(Child(3),)]", "values[0][0].extra"),
    ("dict[str, {item}]", "{'a': (Child(3),)}", "values['a'][0].extra"),
    ("list[{item} | str]", "[(Child(3),)]", "0"),
    ("list[{item} | None]", "[(Child(3),)]", "0"),
    ("list[tuple[{item}]]", "[((Child(3),),)]", "values[0][0][0].extra"),
    ("list[frozenset[{item}]]", "[frozenset(((Child(3),),))]", "0"),
])
def test_mutable_aliases_cannot_widen_nested_tuple_items(outer, value, read):
    actual = outer.format(item="tuple[Child, ...]")
    expected = outer.format(item="tuple[Item, ...]")
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
class Item:
    def __init__(self, value: int): self.value = value
class Child(Item):
    def __init__(self, value: int):
        super().__init__(value)
        self.extra = 5
def main() -> int:
    values: {actual} = {value}
    alias: {expected} = values
    return {read}
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_frozenset_tuple_views_preserve_immutable_value_flow(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class Item:
    def __init__(self, value: int): self.value = value
class Child(Item):
    def __init__(self, value: int):
        super().__init__(value)
        self.extra = 5
def consume(values: frozenset[tuple[Item, ...]]) -> int:
    gc_collect()
    return next(iter(values))[0].value
def nested(values: tuple[frozenset[tuple[Item, ...]], ...]) -> int:
    return consume(values[0])
def main() -> str:
    gc_set_threshold(1)
    values: frozenset[tuple[Child, ...]] = frozenset(((Child(4),),))
    wide: frozenset[tuple[Item, ...]] = values
    return str((consume(values), nested((values,)), consume(wide),
                next(iter(values))[0].extra))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("order", ["int | bool", "bool | int"])
def test_plain_generic_union_keeps_specialization_without_subclass(tmp_path, optimize, order):
    first, second = order.split(" | ")
    result = LLVM().assert_matches_python(BOX + f'''
from pyjs.native import gc_collect, gc_set_threshold
def show(value: Box[{first}] | Box[{second}]) -> str:
    gc_collect()
    return repr(value.value)
def main() -> str:
    gc_set_threshold(1)
    integer = Box[int](257)
    boolean = Box[bool](True)
    return show(integer) + ":" + show(boolean)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_union_keeps_virtual_payload_without_record_subclass(tmp_path, optimize):
    result = LLVM().assert_matches_python(BOX + '''
from pyjs.native import gc_collect, gc_set_threshold
class Animal:
    def __init__(self, name: str):
        self.name = name
    def speak(self) -> str:
        return self.name
class Dog(Animal):
    def speak(self) -> str:
        return "woof " + self.name
def show(box: Box[Animal] | Box[Dog]) -> str:
    gc_collect()
    return box.value.speak()
def main() -> str:
    gc_set_threshold(1)
    return show(Box[Dog](Dog("rex"))) + "|" + show(Box[Animal](Animal("a")))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
