import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.source import compile_source

from .helpers import assert_semantics


@pytest.mark.parametrize("target", ["local", "attribute", "item", "typed_dict", "json_object"])
@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("class_name", ["Bag", "Object"])
def test_application_iadd_preserves_aliases_and_writes_back_result(target, replacement, class_name):
    declarations = {
        "local": ("value = original", "value"),
        "attribute": ("holder = Holder(original)", "holder.value"),
        "item": ("items = [original]", "items[0]"),
        "typed_dict": ('record = Record(value=original)', 'record["value"]'),
        "json_object": ('record = ObjectRecord(value=original)', 'record["value"]'),
    }
    setup, expression = declarations[target]
    source = f'''
        from typing import TypedDict
        from pyjs import js
        from pyjs.javascript import JSONObject
        @js
        class Bag:
            def __init__(self, count: int):
                self.count = count
            def __iadd__(self, amount: int) -> "Bag":
                self.count += amount
                return {"Bag(self.count + 10)" if replacement else "self"}
            def __add__(self, amount: int) -> "Bag":
                return Bag(self.count + amount + 100)
        @js
        class Holder:
            def __init__(self, value: Bag):
                self.value = value
        class Record(TypedDict):
            value: Bag
        class ObjectRecord(JSONObject):
            value: Bag
        def main():
            original = Bag(1)
            {setup}
            {expression} += 2
            print(original is {expression}, original.count, {expression}.count)
        main()
    '''
    assert_semantics(source.replace("Bag", class_name))


@pytest.mark.parametrize("operator,method", [
    ("+=", "__iadd__"), ("-=", "__isub__"), ("*=", "__imul__"),
    ("/=", "__itruediv__"), ("//=", "__ifloordiv__"), ("%=", "__imod__"),
    ("**=", "__ipow__"), ("&=", "__iand__"), ("|=", "__ior__"),
    ("^=", "__ixor__"), ("<<=", "__ilshift__"), (">>=", "__irshift__"),
])
def test_inplace_only_method_is_sufficient(operator, method):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Value:
            def __init__(self):
                self.count = 0
            def {method}(self, amount: int) -> "Value":
                self.count = amount + 40
                return self
        def main():
            value = Value()
            value {operator} 2
            print(value.count)
        main()
    ''')


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("reflected", [False, True])
def test_subclass_inplace_precedes_binary_fallback(inherited, reflected):
    base_method = ('''def __iadd__(self, other: Operand) -> "Base":
                print("base inplace")
                return self''' if inherited else "pass")
    ordinary = ("pass" if reflected else '''def __add__(self, other: Operand) -> "Base":
                print("add")
                return Base()''')
    assert_semantics(f'''
        from pyjs import js
        @js
        class Operand:
            def __radd__(self, other: "Base") -> "Base":
                print("reflected")
                return Base()
        @js
        class Base:
            {base_method}
            {ordinary}
        @js
        class Child(Base):
            def __iadd__(self, other: Operand) -> Base:
                print("child inplace")
                return self
        @js
        def update(value: Base):
            alias = value
            value += Operand()
            print(value is alias)
        def main():
            update(Base())
            update(Child())
        main()
    ''')


def test_property_inplace_evaluation_and_exception_writeback():
    assert_semantics('''
        from pyjs import js
        @js
        class Bag:
            def __iadd__(self, value: int) -> "Bag":
                print("inplace", value)
                if value == 0:
                    raise ValueError("rejected")
                return self
        @js
        class Holder:
            def __init__(self):
                self.saved = Bag()
            @property
            def value(self) -> Bag:
                print("getter")
                return self.saved
            @value.setter
            def value(self, new: Bag):
                print("setter")
                self.saved = new
        @js
        def receiver(holder: Holder) -> Holder:
            print("receiver")
            return holder
        @js
        def argument(value: int) -> int:
            print("rhs")
            if value < 0:
                raise ValueError("argument")
            return value
        def main():
            holder = Holder()
            receiver(holder).value += argument(2)
            try:
                receiver(holder).value += argument(0)
            except ValueError:
                print("caught")
            try:
                receiver(holder).value += argument(-1)
            except ValueError:
                print("caught rhs")
        main()
    ''')


@pytest.mark.parametrize("declaration", [
    "__iadd__ = None", "__iadd__ = __add__",
    '@staticmethod\n            def __iadd__(amount: int) -> "Value":\n                return Value()',
])
def test_unmodeled_inplace_descriptors_diagnose(declaration):
    source = f'''
        from pyjs import js
        @js
        class Value:
            def __add__(self, amount: int) -> "Value":
                return self
            {declaration}
        def main():
            value = Value()
            value += 1
    '''
    with pytest.raises(CompilationError, match="in-place operators require an ordinary application method"):
        with compile_source(source):
            pass


def test_subclass_with_incompatible_inplace_result_diagnoses():
    source = '''
        from pyjs import js
        @js
        class Base:
            def __add__(self, amount: int) -> "Base":
                return self
        @js
        class Child(Base):
            def __iadd__(self, amount: int) -> str:
                return "changed type"
        @js
        def update(value: Base) -> Base:
            value += 1
            return value
        def main():
            update(Child())
    '''
    with pytest.raises(CompilationError, match="in-place overrides must preserve"):
        with compile_source(source):
            pass


@pytest.mark.parametrize("default", ["", " = 7"])
def test_inplace_keeps_awaits_in_caller_and_captures_old_field_value(default):
    assert_semantics('''
        from pyjs import js
        import asyncio
        @js
        class Bag:
            def __init__(self, count: int):
                self.count = count
            def __iadd__(self, amount: int) -> "Bag":
                self.count += amount
                return self
        @js
        async def receiver(values: list[Bag]) -> list[Bag]:
            print("receiver")
            return values
        @js
        async def index() -> int:
            print("index")
            return 0
        @js
        async def argument(values: list[Bag]) -> int:
            print("rhs")
            values[0] = Bag(100)
            return 2
        @js
        async def main():
            original = Bag(1)
            values = [original]
            (await receiver(values))[await index()] += await argument(values)
            print(values[0] is original, values[0].count, original.count)
        asyncio.run(main())
    '''.replace("amount: int)", f"amount: int{default})"))


def test_generic_inplace_method_and_inherited_implementation():
    assert_semantics('''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
            def __iadd__(self, value: T) -> "Box[T]":
                self.value = value
                return self
        @js
        class Child(Box[int]):
            pass
        def main():
            word = Box("before")
            alias = word
            word += "after"
            number: Box[int] = Child(1)
            number += 2
            print(word is alias, alias.value, number.value)
        main()
    ''')


def test_not_implemented_inplace_result_is_not_silently_rebound():
    source = '''
        from pyjs import js
        @js
        class Value:
            def __iadd__(self, amount: int) -> object:
                return NotImplemented
            def __add__(self, amount: int) -> "Value":
                return self
        def main():
            value: object = Value()
            value += 2
    '''
    with pytest.raises(CompilationError, match="NotImplemented"):
        with compile_source(source):
            pass


def test_augmented_matrix_multiplication_keeps_explicit_boundary():
    source = '''
        from pyjs import js
        @js
        class Matrix:
            def __imatmul__(self, other: "Matrix") -> "Matrix":
                return self
        def main():
            value = Matrix()
            value @= value
    '''
    with pytest.raises(CompilationError, match="augmented assignment does not support MatMult"):
        with compile_source(source):
            pass


@pytest.mark.parametrize("base_method,child_method", [
    ("__add__", "optional"),
    ("required", "optional"),
    ("optional", "required"),
    ("optional", "optional"),
    ("optional", "inherited"),
])
@pytest.mark.parametrize("positional_only", [False, True])
@pytest.mark.parametrize("child_operand", ["amount", "__proto__"])
def test_inplace_defaulted_operands_follow_runtime_method_abi(
    base_method, child_method, positional_only, child_operand,
):
    base_name = "__add__" if base_method == "__add__" else "__iadd__"
    base_default = " = 7" if base_method == "optional" else ""
    child_default = " = 11" if child_method == "optional" else ""
    positional = ", /" if positional_only else ""
    child = "pass" if child_method == "inherited" else f'''
            def __iadd__(self, {child_operand}: int{child_default}{positional}) -> Base:
                self.count += {child_operand}
                return self
    '''.strip()
    assert_semantics(f'''
        from pyjs import js
        @js
        class Base:
            def __init__(self):
                self.count = 1
            def {base_name}(self, other: int{base_default}) -> "Base":
                self.count += other
                return self
        @js
        class Child(Base):
            {child}
        @js
        def update(value: Base):
            alias = value
            value += 2
            print(value is alias, value.count)
        def main():
            update(Base())
            update(Child())
            direct: Base = Child()
            direct += 2
            print(direct.count)
        main()
    ''')
