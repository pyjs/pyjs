import ast

import pytest

from pyjs.analysis.ir import (
    FieldLoad,
    FieldStore,
    IRLoweringTransformer,
    build_program_ir,
    validate_program_ir,
)
from pyjs.analysis.objects import Attribute
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("receiver", ["choose(first, second, flag)", "(first if flag else second)",
                                      "[first, second][0]", "First(3)", "type(4)"])
def test_value_producing_receivers_lower_to_fields(environment, receiver):
    with analyze_source(f'''
class First:
    def __init__(self, value: int):
        self.value = value
class Second:
    def __init__(self, value: int):
        self.padding = 0
        self.value = value
class type:
    def __init__(self, value: int):
        self.value = value
def choose(first: First, second: Second, flag: bool) -> First | Second:
    return first if flag else second
def main(flag: bool) -> int:
    first = First(1)
    second = Second(2)
    {receiver}.value = 5
    return {receiver}.value
''', wrap=False, environment=environment) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        nodes = [node for block in analysis.entry_point.ir.blocks for node in ast.walk(block)]
        assert [node.target.attr for node in nodes if isinstance(node, FieldStore)] == ["value"]
        assert [node.attribute.attr for node in nodes if isinstance(node, FieldLoad)] == ["value"]


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
def test_returned_class_objects_are_not_instance_field_receivers(environment):
    with analyze_source('''
class Box:
    count = 7
def owner() -> type[Box]:
    return Box
def main() -> type[Box]:
    return owner()
''', wrap=False, environment=environment) as analysis:
        # Attribute lookup on returned type[T] is currently rejected before IR.
        # Exercise the classifier with real analyzed class-result metadata so
        # widening that lookup later cannot reinterpret a class as an instance.
        call = analysis.entry_point.ir.blocks[0].body[-1].value
        box = analysis.entry_point.container.search("Box")
        attribute = Attribute(box.find_attrs("count"), value=call, attr="count", ctx=ast.Load())
        assert not IRLoweringTransformer.is_instance_field(attribute)
