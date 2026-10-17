import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_inherited_constants_preserve_runtime_class_and_receiver_effects(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            retries = 40
            label = "base"
            enabled = True
            ratio = -1.5
            def total(self) -> int:
                return self.retries + 2
        class Child(Base):
            retries = 7
            label = "child"
            def parent_label(self) -> str:
                return super().label
        class Other:
            label = "other"
        def build(child: bool, events: list[str], fail: bool) -> Base:
            events.append("build")
            gc_collect()
            if fail:
                raise ValueError("receiver failed")
            if child:
                return Child()
            return Base()
        def read(value: Base) -> str:
            return value.label + str(value.total())
        def union(value: Base | Other) -> str:
            return value.label
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values: list[str] = []
            for child in [False, True]:
                values.append(build(child, events, False).label)
                values.append(read(build(child, events, False)))
            try:
                build(False, events, True).label
            except ValueError as error:
                events.append(str(error))
            return repr((values, events, Child.retries, Child.ratio, Child.enabled,
                         Child().parent_label(), union(Child()), union(Other())))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_string_constant_without_instance_has_no_late_type_dependency(optimize):
    result = LLVM().assert_matches_python('''
        class Base:
            label = "ship"
        class Child(Base):
            pass
        def main() -> str:
            return Child.label
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_class_constants_prepare_float_formatting_without_other_float_sources(optimize):
    result = LLVM().assert_matches_python('''
        class First:
            value = 2.5
        class Second:
            value = 3.5
        def read(value: First | Second) -> str:
            return repr(value.value)
        def main() -> str:
            return read(First()) + read(Second())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("declarations, expression", [
    ("class Base:\n    value: float = 2", "Base.value"),
    ("class Base:\n    value = 2\nclass Child(Base):\n    value = True", "read(Child())"),
])
def test_class_constants_do_not_silently_change_scalar_kinds(declarations, expression):
    with pytest.raises(LLVMUnsupported, match="explicit numeric conversion"):
        transpile_llvm(declarations + f'''
def read(value: Base) -> int:
    return value.value
def main() -> str:
    return repr({expression})
''')


@pytest.mark.parametrize("statement", ["Base.value = 2", "del Base.value", "Base.value += 2"])
def test_class_constant_writes_are_located_compile_errors(statement):
    with pytest.raises(CompilationError, match="class constants are read-only") as caught:
        transpile_llvm(f'''
            class Base:
                value = 1
            def main() -> int:
                {statement}
                return 0
        ''')
    assert caught.value.lineno is not None


@pytest.mark.parametrize("value", ["[1, 2]", 'b"ab"', "None"])
def test_unmodeled_class_values_keep_the_shared_diagnostic(value):
    with pytest.raises(CompilationError, match="Attribute 'value' is not defined"):
        transpile_llvm(f'''
            class Base:
                value = {value}
            def main() -> int:
                Base.value
                return 0
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_class_constant_receivers_are_evaluated_once_inside_generators(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            label = "base"
        class Child(Base):
            label = "child"
        def make(events: list[int]) -> Base:
            events.append(len(events))
            gc_collect()
            return Child()
        def values(events: list[int]) -> Iterator[str]:
            for index in range(3):
                yield make(events).label
                gc_collect()
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result = list(values(events))
            return repr((result, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("body, message", [
    ("def __init__(self):\n        self.value = 9", "class constants are read-only"),
    ("@property\n    def value(self) -> int:\n        return 9", "scalar declarations"),
    ('def __getattribute__(self, name: str) -> int:\n        return 9', "ordinary attribute lookup"),
])
def test_runtime_constant_lookup_rejects_unmodeled_shadowing(body, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm('''
class Base:
    value = 2
class Child(Base):
    BODY
def read(value: Base) -> int:
    return value.value
def main() -> int:
    return read(Child())
'''.replace("BODY", body))


def test_class_constant_does_not_bypass_custom_metaclass_lookup():
    with pytest.raises(LLVMUnsupported, match="ordinary metaclass lookup"):
        transpile_llvm('''
            class Meta(type):
                def __getattribute__(cls, name: str):
                    if name == "value":
                        return 7
                    return super().__getattribute__(name)
            class Base(metaclass=Meta):
                value = 2
            def main() -> int:
                return Base.value
        ''')


@pytest.mark.parametrize("value", ["None", "[3]", 'b"ab"'])
@pytest.mark.parametrize("receiver", ["Child", "super()", "parent"])
def test_unmodeled_overrides_never_fall_back_to_inherited_constants(value, receiver):
    with pytest.raises(LLVMUnsupported, match="overrides must remain scalar declarations") as caught:
        transpile_llvm(f'''
            class Base:
                value = 2
            class Child(Base):
                value = {value}
            class Grandchild(Child):
                def read(self) -> str:
                    parent = super()
                    return repr({receiver}.value)
            def main() -> str:
                return Grandchild().read()
        ''')
    assert "Source location:" in " ".join(caught.value.__notes__)


def test_mixed_constant_and_instance_field_union_has_an_explicit_boundary():
    with pytest.raises(LLVMUnsupported, match="union reads cannot mix class constants and instance fields"):
        transpile_llvm('''
            class Constant:
                value = 3
            class Field:
                def __init__(self):
                    self.value = 9
            def read(value: Constant | Field) -> int:
                return value.value
            def main() -> str:
                return repr((read(Constant()), read(Field())))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_constructor_constant_reads_keep_effects_and_failures(optimize):
    result = LLVM().assert_matches_python('''
        class Record:
            value = 5
            def __init__(self, events: list[int], fail: bool):
                events.append(1)
                if fail:
                    raise ValueError("construction")
        def main() -> str:
            events: list[int] = []
            value = Record(events, False).value
            try:
                Record(events, True).value
            except ValueError as error:
                return repr((value, events, str(error)))
            return "missing exception"
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_temporary_factory_sentinel_prepares_identity_helpers_without_object_slots(optimize):
    result = LLVM().assert_matches_python('''
        from dataclasses import dataclass, field
        @dataclass
        class Record:
            values: list[int] = field(default_factory=list)
        def main() -> int:
            first = Record()
            second = Record()
            first.values.append(2)
            return len(first.values) - 1 + len(second.values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
