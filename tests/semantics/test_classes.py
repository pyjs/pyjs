import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.source import compile_source
from tests.backend_semantics import (
    APPLICATION_GENERIC_UNION_ORDER_CONTRACT,
    INHERITED_FACTORY_FIELD_CONTRACT,
    PROPERTY_FIELD_OVERRIDE_CONTRACT,
    PROPERTY_GETTER_CONTRACT,
)

from .helpers import assert_semantics, run_python


def test_shared_property_getter_contract():
    assert_semantics(PROPERTY_GETTER_CONTRACT.print_source + "\nmain()\n")


def test_inherited_factory_field_contract():
    assert_semantics(INHERITED_FACTORY_FIELD_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("parameter", ["T", "T: Base"])
@pytest.mark.parametrize("expression", ["repr(value)", "value.__repr__()", "f'{value!r}'"])
@pytest.mark.parametrize("method", [False, True], ids=["function", "method"])
def test_generic_receivers_retain_inherited_builtin_overrides(parameter, expression, method):
    declaration = (f'''class Reader:
            def render[{parameter}](self, value: T) -> str:
                return {expression}''' if method else
                   f'''def render[{parameter}](value: T) -> str:
            return {expression}''')
    assert_semantics(f'''
        from pyjs import js
        @js
        class Base:
            pass
        @js
        class Child(Base):
            def __repr__(self) -> str:
                return 'child'
        @js
        {declaration}
        @js
        def main() -> None:
            print({"Reader().render" if method else "render"}(Child()))
        main()
    ''')


@pytest.mark.parametrize("receiver,child,argument", [
    ("Box[T]", "Child(Box[int])", "1"),
    ("Box[T]", "Child[T](Box[T])", "1"),
    ("Box[list[T]]", "Child(Box[list[int]])", "[1]"),
])
@pytest.mark.parametrize("expression", ["repr(value)", "value.__repr__()", "f'{value!r}'"])
@pytest.mark.parametrize("before", [False, True], ids=["inline-child", "existing-child"])
def test_parameterized_generic_receivers_retain_builtin_overrides(receiver, child, argument, expression, before):
    body = (f"value = Child({argument})\n            print(render(value))" if before else
            f"print(render(Child({argument})))")
    assert_semantics(f'''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
        @js
        class {child}:
            def __repr__(self) -> str:
                return 'boxed-child'
        @js
        def render[T](value: {receiver}) -> str:
            return {expression}
        @js
        def main() -> None:
            {body}
        main()
    ''')


def test_application_generic_union_orders_keep_instance_methods():
    assert_semantics(APPLICATION_GENERIC_UNION_ORDER_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="JS prints booleans in declared int fields with JavaScript spelling")
@pytest.mark.parametrize("class_body", [False, True], ids=["initializer", "class-body"])
def test_boolean_values_in_inherited_integer_fields_keep_python_printing(class_body):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Parent:
            {"value: int" if class_body else "pass"}
            def __init__(self):
                self.value{'' if class_body else ': int'} = 0
        @js
        class Child(Parent):
            def put(self):
                self.value = True
        @js
        def main():
            child = Child()
            child.put()
            print(child.value, child.value + 1)
        main()
    ''')


@pytest.mark.parametrize("first,second,value", [
    ("int | str", "str | int", "1"),
    ("str | int", "int | str", "1"),
    ("int | None", "None | int", "None"),
    ("None | int", "int | None", "None"),
])
def test_generic_union_order_keeps_properties_and_extracted_methods(first, second, value):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
            def get(self) -> T:
                return self.value
            @property
            def item(self) -> T:
                return self.value
            @item.setter
            def item(self, value: T):
                self.value = value
        @js
        def read(box: Box[{first}]) -> bool:
            method = box.get
            box.item = {value}
            return box.item == method()
        @js
        def main():
            first = Box[{first}]({value})
            second = Box[{second}]({value})
            print(read(first))
            print(read(second))
        main()
    ''')


def test_property_field_override_keeps_unsupported_analysis_boundary():
    oracle = run_python(PROPERTY_FIELD_OVERRIDE_CONTRACT.source + "\nassert main() == 0\n")
    assert oracle.returncode == 0, oracle.stderr
    with pytest.raises(CompilationError, match="Function returns str.*NoneType, not str"):
        compile_source(PROPERTY_FIELD_OVERRIDE_CONTRACT.source)


def test_generic_classmethod_factory_matches_python():
    assert_semantics('''
        from pyjs import js
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
            @classmethod
            def create(cls, value: T) -> 'Box[T]':
                return cls(value)
            def get(self) -> T:
                return self.value
        @js
        def main():
            explicit = Box[str]('direct')
            print(explicit.get())
            print(Box.create('ok').get())
            print(Box.create(42).get())
        main()
    ''')


def test_properties_and_inherited_overrides_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Person:
            def __init__(self, first: str, last: str):
                self.first = first
                self.last = last

            @property
            def name(self) -> str:
                return self.first + " " + self.last

        @js
        class FormalPerson(Person):
            @property
            def name(self) -> str:
                return "Dr. " + self.last

        @js
        def print_name(person: Person):
            print(person.name)

        print_name(Person("Ada", "Lovelace"))
        print_name(FormalPerson("Grace", "Hopper"))
        """
    )


def test_property_setters_and_inherited_overrides_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Score:
            def __init__(self):
                self._value = 0

            @property
            def value(self) -> int:
                return self._value

            @value.setter
            def value(self, new_value: int):
                self._value = new_value

        @js
        class DoubledScore(Score):
            @property
            def value(self) -> int:
                return self._value * 2

            @value.setter
            def value(self, new_value: int):
                self._value = new_value + 1

        @js
        def update(score: Score | DoubledScore, value: int):
            score.value = value
            print(score.value)

        update(Score(), 4)
        update(DoubledScore(), 4)
        """
    )


def test_inherited_methods_read_polymorphic_class_fields():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Tool:
            label = "tool"

            def current_label(self) -> str:
                return self.label

            def override_label(self, label: str) -> None:
                self.label = label

        @js
        class IntermediateTool(Tool):
            label: str

        @js
        class SelectTool(IntermediateTool):
            label = "select"

        @js
        class DeclaredTool:
            label: str

            def current_label(self) -> str:
                return self.label

        @js
        class MoveTool(DeclaredTool):
            label = "move"

        print(Tool().current_label())
        print(SelectTool().current_label())
        tool: Tool = SelectTool()
        print(tool.label)
        tool.override_label("instance")
        print(tool.label)
        print(MoveTool().current_label())
        """
    )


def test_augmented_class_fields_and_inherited_classmethods_match_python():
    assert_semantics("""
        from typing import ClassVar
        from pyjs import js

        @js
        class Counter:
            total: ClassVar[int] = 0

            def __init__(self):
                Counter.total += 1
                self.value = Counter.total

            @classmethod
            def bump(cls) -> int:
                cls.total += 2
                return cls.total

        @js
        class Child(Counter):
            pass

        first = Counter()
        second = Counter()
        print(first.value, second.value, Counter.total)
        print(Counter.bump(), Counter.bump())
        print(Child.bump(), Child.bump())
        print(Counter.total, Child.total)
    """)


def test_compatible_inherited_class_field_defaults_match_python():
    assert_semantics(
        """\
        from typing import ClassVar

        from pyjs import js

        @js
        class Declared:
            label: str

        @js
        class Child(Declared):
            label = "child"

        @js
        class Counted:
            count: ClassVar[int] = 1

        @js
        class MoreCounted(Counted):
            count = 2

        @js
        class Animal:
            def __init__(self, name: str):
                self.name = name

        @js
        class Dog(Animal):
            def bark(self) -> str:
                return self.name + " says woof"

        @js
        class AnimalHolder:
            animal: Animal

        @js
        class PlainDogHolder(AnimalHolder):
            animal = Dog("Fido")

        @js
        class Holder[T: Animal]:
            animal: T

        @js
        class DogHolder(Holder[Dog]):
            animal = Dog("Spot")

        print(Child().label)
        print(MoreCounted().count)
        print(PlainDogHolder().animal.name)
        print(DogHolder().animal.bark())
        """
    )


def test_common_fields_on_union_typed_values_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class TextValue:
            def __init__(self):
                self.value = "ready"
                self.shared = "text"

        @js
        class CountValue:
            def __init__(self):
                self.value = 3
                self.shared = "count"

        @js
        class TextBox:
            def __init__(self):
                self.item = TextValue()

        @js
        class CountBox:
            def __init__(self):
                self.item = CountValue()

        @js
        def read(item: TextValue | CountValue):
            return item.value

        @js
        def read_shared(item: TextValue | CountValue):
            return item.shared

        @js
        def read_nested(box: TextBox | CountBox):
            return box.item.value

        print(read(TextValue()))
        print(read(CountValue()))
        print(read_shared(TextValue()))
        print(read_shared(CountValue()))
        print(read_nested(TextBox()))
        print(read_nested(CountBox()))
        """
    )


def test_common_methods_on_union_typed_values_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class TextValue:
            def render(self, prefix: str) -> str:
                return prefix + "text"

        @js
        class CountValue:
            def render(self, prefix: object) -> int:
                print(prefix)
                return 3

        @js
        def render(item: TextValue | CountValue):
            return item.render("value: ")

        print(render(TextValue()))
        print(render(CountValue()))
        """
    )


def test_union_equality_uses_runtime_custom_dunder_methods():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Match:
            def __init__(self, key: str):
                self.key = key

            def __eq__(self, other: object) -> bool:
                return isinstance(other, Match) and self.key == other.key

            def __ne__(self, other: object) -> bool:
                return False

        @js
        def compare(left: Match | None, right: Match | None):
            print(left == right, left != right)

        compare(Match("same"), Match("same"))
        compare(Match("left"), Match("right"))
        compare(None, Match("value"))
        compare(None, None)
        """
    )


def test_union_binary_operators_dispatch_custom_dunder_methods():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Label:
            def __add__(self, value: int) -> str:
                return "label-" + str(value)

        @js
        class Count:
            def __add__(self, value: int) -> int:
                return value + 2

        @js
        def combine(value: Label | Count) -> str | int:
            return value + 3

        print(combine(Label()))
        print(combine(Count()))
        """
    )


def test_optional_truth_tests_use_custom_dunder_methods():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Enabled:
            def __init__(self, value: bool):
                self.value = value

            def __bool__(self) -> bool:
                return self.value

        @js
        class Sized:
            def __init__(self, size: int):
                self.size = size

            def __len__(self) -> int:
                return self.size

        @js
        def label(value: Enabled | Sized | None) -> str:
            if value:
                return "yes"
            return "no"

        @js
        def expression(value: Enabled | Sized | None) -> str:
            return "yes" if value else "no"

        @js
        def items(values: list[int] | None) -> str:
            return "yes" if values else "no"

        print(label(Enabled(True)), label(Enabled(False)))
        print(expression(Sized(1)), expression(Sized(0)))
        print(label(None), expression(None))
        print(items(None), items([]), items([1]))
        """
    )


def test_writes_to_common_fields_on_union_typed_values_match_python():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class Left:
            def __init__(self):
                self.value = 1

        @js
        class Right:
            def __init__(self):
                self.value: int | None = 2

        @js
        def update(item: Left | Right, value: int):
            item.value = value

        @js
        def increment(item: Left | Right):
            if item.value is None:
                return
            item.value += 1

        left = Left()
        right = Right()
        update(left, 3)
        update(right, 4)
        increment(left)
        increment(right)
        print(left.value)
        print(right.value)
        """
    )
def test_narrowed_properties_still_invoke_the_getter():
    assert_semantics('''
        from pyjs import js

        @js
        class Value:
            def __init__(self):
                self.reads = 0
            @property
            def item(self) -> int | str:
                self.reads += 1
                return 1 if self.reads == 1 else 'changed'

        @js
        def inspect(value: Value) -> str:
            if isinstance(value.item, int):
                return str(value.item)
            return 'unexpected'

        @js
        def main():
            value = Value()
            print(inspect(value), value.reads)

        main()
    ''')
