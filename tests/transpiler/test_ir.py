import ast
import sys
from textwrap import dedent

import pytest

from pyjs.analysis.ir import (
    Branch,
    CollectionNew,
    IRValidationError,
    IteratorCreate,
    IteratorNext,
    Jump,
    ProgramIR,
    build_program_ir,
    validate_program_ir,
)
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.representation import (
    array_representation,
    compound_representation,
    direct_representation,
)
from pyjs.analysis.source import analyze_source
from pyjs.decorators import (
    ParameterLifetime,
    analysis_metadata,
    configure_parameter_lifetimes,
    integer_index_parameters,
    parameter_lifetimes,
    preserves_numeric_format,
)
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.numeric import ArrayFormat, NumericFormat


def analyze_ir(source: str):
    return analyze_source(
        dedent(source),
        wrap=False,
        environment=NATIVE_ENVIRONMENT,
    )


@pytest.mark.parametrize("method", ["__hash__", "__repr__"])
@pytest.mark.parametrize("before", [False, True])
def test_inherited_builtin_methods_do_not_reach_unrelated_overrides(method, before):
    with analyze_ir(f'''
        class Unrelated:
            def {method}(self) -> {"int" if method == "__hash__" else "str"}:
                return missing_name()
            def keep(self) -> int:
                return 1
        def invoke(value: int) -> {"int" if method == "__hash__" else "str"}:
            return value.{method}()
        def main() -> int:
            {"value = Unrelated()" if before else "invoke(1)"}
            invoke(2)
            return {"value" if before else "Unrelated()"}.keep()
    ''') as analysis:
        program = build_program_ir(analysis.entry_point)
        methods = {(function.cls.name, function.name) for function in program.functions
                   if function.cls is not None}
        assert ("Unrelated", "keep") in methods
        assert ("Unrelated", method) not in methods
        validate_program_ir(program)


@pytest.mark.parametrize("before", [False, True])
@pytest.mark.parametrize("receiver", ["Base", "Base | None"])
def test_inherited_builtin_hash_retains_only_receiver_subclasses(receiver, before):
    with analyze_ir(f'''
        class Base:
            pass
        class Child(Base):
            def __hash__(self) -> int:
                return 7
            def unrelated(self) -> int:
                return missing_name()
        class Other:
            def __hash__(self) -> int:
                return missing_name()
        def invoke(value: {receiver}) -> int:
            return value.__hash__()
        def main() -> int:
            other = Other()
            {"child = Child()" if before else "invoke(Base())"}
            return invoke({"child" if before else "Child()"})
    ''') as analysis:
        program = build_program_ir(analysis.entry_point)
        methods = {(function.cls.name, function.name) for function in program.functions
                   if function.cls is not None}
        assert ("Child", "__hash__") in methods
        assert ("Other", "__hash__") not in methods
        assert ("Child", "unrelated") not in methods
        validate_program_ir(program)
    assert not analysis.entry_point.virtual_receiver_dependencies


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
@pytest.mark.parametrize("expression", ["value.__str__()", "getattr(value, '__str__')()",
                                        "getattr(value, '__str__', None)()"])
def test_inherited_builtin_reference_scope_is_shared_by_ir_backends(backend, expression):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(f'''
        class Base:
            pass
        class Child(Base):
            def __str__(self) -> str:
                return 'child'
        class Other:
            def __str__(self) -> str:
                return missing_name()
        def invoke(value: Base) -> str:
            return {expression}
        def main() -> str:
            Other()
            invoke(Base())
            return invoke(Child())
    ''', wrap=False, environment=environment) as analysis:
        methods = {(function.cls.name, function.name)
                   for function in build_program_ir(analysis.entry_point).functions
                   if function.cls is not None}
        assert ("Child", "__str__") in methods
        assert ("Other", "__str__") not in methods


@pytest.mark.parametrize("expression", ["str(value)", "value.__str__()", "str([value])", "repr([value])"])
def test_native_formatting_scopes_fallback_and_late_override_dependencies(expression):
    with analyze_ir(f'''
        class Base:
            pass
        class Child(Base):
            def __repr__(self) -> str:
                return 'child'
        class Other:
            def __repr__(self) -> str:
                return missing_name()
        def invoke(value: Base) -> str:
            return {expression}
        def main() -> str:
            Other()
            invoke(Base())
            return invoke(Child())
    ''') as analysis:
        methods = {(function.cls.name, function.name)
                   for function in build_program_ir(analysis.entry_point).functions
                   if function.cls is not None}
        assert ("Child", "__repr__") in methods
        assert ("Other", "__repr__") not in methods


@pytest.mark.parametrize("expression", [
    'repr([factory.get()().name() for factory in factories])',
    '"|".join(factory.get()().name() for factory in factories)',
])
def test_callable_result_is_not_an_exact_constructor_receiver(expression):
    with analyze_ir(f'''
from collections.abc import Callable
class Base:
    def name(self) -> str:
        return "base"
class Child(Base):
    def name(self) -> str:
        return "child"
    def unrelated(self) -> str:
        return missing_name()
def make() -> Base:
    return Child()
class Factory:
    def get(self) -> Callable[[], Base]:
        return make
def main() -> str:
    unused = Child()
    factories = [Factory()]
    return {expression}
''') as analysis:
        program = build_program_ir(analysis.entry_point)
        assert {function.cls.name for function in program.functions
                if function.cls is not None and function.name == "name"} == {"Base", "Child"}
        assert not any(function.name == "unrelated" for function in program.functions)


def test_enum_class_member_and_instance_method_have_distinct_analysis():
    from pyjs.analysis.objects import Class, Function, Instance

    with analyze_ir('''
from enum import StrEnum
class Label(StrEnum):
    upper = 'upper'
def main() -> str:
    member = Label.upper
    return member.upper()
''') as analysis:
        function = analysis.entry_point
        label = function.container.search("Label")
        assert function.scope.names["member"].cls is label
        attributes = [node for block in function.ir.blocks
                      for statement in getattr(block, "body", ()) for node in ast.walk(statement)
                      if isinstance(node, ast.Attribute) and node.attr == "upper"]
        members = [node for node in attributes if isinstance(node.value.obj, Class)]
        methods = [node for node in attributes if isinstance(node.value.obj, Instance)]
        assert len(members) == len(methods) == 1
        assert isinstance(members[0].obj, Instance)
        assert members[0].obj.py_value is label.py_cls.upper
        assert isinstance(methods[0].obj, Function)
        assert methods[0].obj.cls.py_cls.__name__ == "_str"
        validate_program_ir(build_program_ir(function))


@pytest.mark.parametrize("reflected", [False, True])
@pytest.mark.parametrize("retaining", [False, True])
def test_runtime_binary_protocol_lifetimes_bind_selected_operand(reflected, retaining):
    source = '''
class Base:
    def __init__(self):
        self.saved: Base | None = None
    def __add__(self, other: "Base") -> "Base":
        return Base()
class Child(Base):
    def METHOD(self, other: Base) -> Base:
        RETAIN
        return self
def operate(left: Base, right: Base) -> Base:
    return left + right
def main() -> Base:
    return operate(Child(), Child())
'''.replace("METHOD", "__radd__" if reflected else "__add__").replace(
        "RETAIN", "self.saved = other" if retaining else "pass")
    with analyze_ir(source) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        module = analysis.entry_point.container
        assert module.search("Child").find("__radd__" if reflected else "__add__") in program.functions
        summary = module.search("operate").ir.lifetime
        owner, other = ("right", "left") if reflected else ("left", "right")
        assert summary.returned_parameters == frozenset({owner, other} if retaining else {owner})
        assert summary.parameter_containment == (((owner, other),) if retaining else ())


@pytest.mark.parametrize("reflected", [False, True])
@pytest.mark.parametrize("retaining", [False, True])
def test_introduced_inplace_protocol_lifetimes_bind_original_left_operand(reflected, retaining):
    source = '''
class Operand:
    REFLECTED
class Base:
    def __init__(self):
        self.saved: Operand | None = None
    ORDINARY
class Child(Base):
    def __iadd__(self, other: Operand) -> Base:
        RETAIN
        return self
def update(value: Base, other: Operand) -> Base:
    value += other
    return value
def main() -> Base:
    return update(Child(), Operand())
'''.replace("REFLECTED", 'def __radd__(self, other: "Base") -> "Base":\n        return Base()' if reflected else "pass").replace(
        "ORDINARY", 'def __add__(self, other: Operand) -> "Base":\n        return Base()' if not reflected else "pass").replace(
        "RETAIN", "self.saved = other" if retaining else "pass")
    with analyze_ir(source) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        module = analysis.entry_point.container
        assert module.search("Child").find("__iadd__") in program.functions
        summary = module.search("update").ir.lifetime
        assert summary.returned_parameters == frozenset({"value", "other"} if retaining else {"value"})
        assert summary.parameter_containment == ((("value", "other"),) if retaining else ())


def test_inherited_browser_constructor_supplies_empty_literal_context():
    with analyze_ir('''
        from pyjs.web.domx import CustomElement
        class Base(CustomElement):
            def __init__(self, values: list[str]):
                super().__init__()
                self.values = values
        class Child(Base):
            pass
        def main() -> int:
            return len(Child([]).values)
    ''') as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        child = next(layout for layout in program.classes if layout.value_type.name == "Child")
        assert child.constructor.cls.name == "Base"
        assert child.constructor in program.functions
        allocations = [node for block in analysis.entry_point.ir.blocks
                       for statement in getattr(block, "body", ())
                       for node in ast.walk(statement) if isinstance(node, CollectionNew)]
        assert len(allocations) == 1
        assert allocations[0].value_type.generic_types["V"].name == "str"


@pytest.mark.parametrize("before", [False, True])
def test_virtual_accessors_reach_overrides_through_builtin_intermediate(before):
    with analyze_ir(f'''
        from pyjs.web.domx import CustomElement
        class Base(CustomElement):
            pass
        class Child(Base):
            @property
            def textContent(self) -> str:
                return "child"
            @textContent.setter
            def textContent(self, value: str | None) -> None:
                pass
            def unrelated(self) -> str:
                return missing_name()
        class Unused(CustomElement):
            @property
            def textContent(self) -> str:
                return missing_name()
        def update(item: Base) -> str:
            item.textContent = None
            return item.textContent
        def main() -> str:
            {"first = Child()" if before else "update(Base())"}
            return update({"first" if before else "Child()"})
    ''') as analysis:
        program = build_program_ir(analysis.entry_point)
        accessors = {(function.cls.name, function.name, function.is_property_setter)
                     for function in program.functions if function.cls is not None
                     and function.name == "textContent"}
        assert accessors == {
            (owner, "textContent", setter)
            for owner in ("WebElement", "Child") for setter in (False, True)
        }
        assert not any(function.name == "unrelated" for function in program.functions)
        assert not any(layout.value_type.name == "Unused" for layout in program.classes)


@pytest.mark.parametrize("base_method", ["pass", "def __len__(self) -> int: return 1"])
@pytest.mark.parametrize("receiver", ["Parent", "Parent | None", "Parent | str"])
def test_native_length_retains_late_subclass_protocol_only(base_method, receiver):
    with analyze_ir(f'''
        class Parent:
            {base_method}
        class Child(Parent):
            def __len__(self) -> int:
                return 2
            def __bool__(self) -> bool:
                return False
            def unrelated(self) -> int:
                return 5
        def measure(value: {receiver}) -> int:
            return len(value)
        def main() -> int:
            measure(Parent())
            return measure(Child())
    ''') as analysis:
        functions = build_program_ir(analysis.entry_point).functions
        methods = {(function.cls.name, function.name) for function in functions if function.cls is not None}
        assert ("Child", "__len__") in methods
        assert (("Parent", "__len__") in methods) is (base_method != "pass")
        assert ("Child", "__bool__") not in methods
        assert ("Child", "unrelated") not in methods


@pytest.mark.parametrize("consumer, uses_truth", [
    ("any(values)", True),
    ("all(values)", True),
    ("len(list(filter(None, values)))", True),
    ("len(list(filterfalse(None, values)))", True),
    ("len(list(compress([1], selectors=values)))", True),
    ("len(list(filter(lambda value: True, values)))", False),
    ("len(list(takewhile(lambda value: True, values)))", False),
])
def test_native_item_truth_retains_only_required_subclass_protocols(consumer, uses_truth):
    with analyze_ir(f'''
        from itertools import compress, filterfalse, takewhile
        class Parent:
            def __len__(self) -> int:
                return 1
        class Child(Parent):
            def __bool__(self) -> bool:
                return False
            def unrelated(self) -> int:
                return 5
        def main() -> int:
            values: list[Parent] = [Child()]
            {consumer}
            return 0
    ''') as analysis:
        functions = build_program_ir(analysis.entry_point).functions
        methods = {(function.cls.name, function.name) for function in functions if function.cls is not None}
        assert (("Child", "__bool__") in methods) is uses_truth
        assert ("Child", "unrelated") not in methods


@pytest.mark.parametrize("consumer", ["len(values[0])", "bool(values[0])"])
def test_native_protocol_retains_signature_only_receiver_method(consumer):
    with analyze_source(f'''
        class Sized:
            def __init__(self, value: int):
                self.value = value
            def __len__(self) -> int:
                return self.value
            def unrelated(self) -> int:
                return 10
        def main(values: list[Sized]) -> int:
            return int({consumer})
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        functions = build_program_ir(analysis.entry_point).functions
        methods = {(function.cls.name, function.name) for function in functions if function.cls is not None}
        assert ("Sized", "__len__") in methods
        assert ("Sized", "__init__") not in methods
        assert ("Sized", "unrelated") not in methods


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
def test_nullable_assignment_keeps_old_read_proof_and_full_written_storage(backend):
    from pyjs import int64
    from pyjs.analysis.analyzer import analyzed_value_type
    from pyjs.analysis.representation import annotation_representation
    from pyjs.analysis.value_representation import analyzed_representation
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source('''
        from pyjs import int64
        def replace(value: int64 | None, other: int64 | None) -> int64 | None:
            if value is not None:
                before = value
                value = other
            return value
        def main() -> int:
            replace(None, int64(1))
            return 0
    ''', wrap=False, environment=environment) as analysis:
        assert analysis.types == dedent('''\
            def replace(value: int | None, other: int | None) -> int | None:
                block entry:
                    branch value.[object]__is_not__(None):
                        true -> if_true
                        false -> if_done
                block if_true:
                    before: int = value
                    value = other
                    jump if_done
                block if_done:
                    return value

            def main() -> int:
                block entry:
                    replace(None, int(1))
                    return 0
        ''').rstrip()
        function = analysis.entry_point.container.search("replace")
        old = function.ir.blocks[1].body[0].value
        returned = function.ir.blocks[-1].body[-1].value
        assert analyzed_value_type(old).generic_name == "int"
        assert analyzed_representation(old) == annotation_representation(int64)
        assert analyzed_representation(returned) == annotation_representation(int64 | None)


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
@pytest.mark.parametrize("literal", ["[int8(1)]", "(int8(1),)", "{int8(1)}", "{'value': int8(1)}"])
def test_collection_ir_retains_literal_representation(backend, literal):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(f"from pyjs import int8\ndef main() -> int:\n    values = {literal}\n    return len(values)",
                        wrap=False, environment=environment) as analysis:
        allocations = [node for block in analysis.entry_point.ir.blocks for statement in block.body
                       for node in ast.walk(statement) if isinstance(node, CollectionNew)]
        assert len(allocations) == 1
        expected = analysis.entry_point.scope.lookup("values").representation
        assert expected is not None
        assert allocations[0].representation == expected


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
def test_frozenset_operations_preserve_represented_items(backend):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(dedent('''
        from pyjs import int8

        def main() -> int8:
            values = frozenset([int8(1), int8(2)])
            copied = values.copy()
            combined = values | {int8(3)}
            method = values.union([int8(4)])
            optional: frozenset[int8] | None = combined
            return sum(method, int8(0))
    '''), wrap=False, environment=environment) as analysis:
        represented_set = compound_representation(arguments=(
            direct_representation(NumericFormat("integer", 8, True), None),
        ))
        for name in ("values", "copied", "combined", "method"):
            value = analysis.entry_point.scope.lookup(name)
            assert value.cls.generic_name == "frozenset"
            assert value.representation == represented_set


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
def test_set_literal_uses_its_declared_union_item_layout(backend):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(dedent('''
        def main() -> int:
            values: set[int | str] = {1}
            values.add('word')
            return len(values)
    '''), wrap=False, environment=environment) as analysis:
        allocations = [node for block in analysis.entry_point.ir.blocks for statement in block.body
                       for node in ast.walk(statement) if isinstance(node, CollectionNew)]
        assert len(allocations) == 1
        expected = analysis.entry_point.scope.lookup("values").cls
        assert allocations[0].value_type is expected
        assert {member.name for member in expected.generic_types["V"].types} == {"int", "str"}


@pytest.mark.parametrize("kind, literal", [("list", "[int8(1)]"), ("set", "{int8(1)}"),
                                           ("dict", '{"key": int8(1)}')])
def test_native_collection_copies_preserve_nested_representations(kind, literal):
    with analyze_ir(f'''
        from pyjs import int8
        def main() -> int:
            values = {literal}
            copied = values.copy()
            return len(copied)
    ''') as analysis:
        values = analysis.entry_point.scope.lookup("values")
        copied = analysis.entry_point.scope.lookup("copied")
        assert copied.cls.generic_name == kind
        assert copied.representation == values.representation
        assert copied.representation is not None


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
def test_set_ordering_does_not_retain_member_ordering_methods(backend):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source('''
class Key:
    def __hash__(self) -> int:
        return 1
    def __eq__(self, other: Key) -> bool:
        return True
    def __lt__(self, other: Key) -> bool:
        return missing_name()
    def __gt__(self, other: Key) -> bool:
        return missing_name()
def compare(other: set[Key] | frozenset[Key]) -> bool:
    return {Key()} < other
def main() -> bool:
    return {Key()} < {Key()} and compare(frozenset({Key()}))
''', wrap=False, environment=environment) as analysis:
        methods = {function.name for function in build_program_ir(analysis.entry_point).functions
                   if function.cls is not None and function.cls.name == 'Key'}
        assert "__eq__" in methods
        if backend == "native":
            # LLVM retains hashing during literal construction; the other
            # backends do not implement this set runtime yet.
            assert "__hash__" in methods
        assert not methods & {"__lt__", "__gt__"}


@pytest.mark.parametrize("expression", ["left | right", "left.union(right)", "left.__or__(right)",
                                        "left == right", "left < right", "left.__eq__(right)"])
def test_mixed_set_kinds_validate_item_representations(expression):
    from pyjs.analysis.diagnostics import CompilationError

    with pytest.raises(CompilationError, match="incompatible.*representation") as caught, analyze_ir(f'''
        from pyjs import int8, int16
        def main() -> str:
            left = frozenset([int8(1)])
            right = {{int16(1)}}
            return str({expression})
    '''):
        pass
    assert caught.value.lineno == 6


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
@pytest.mark.parametrize("expression", ["left | right", "left.__or__(right)",
                                        "left.__ror__(right)", "left.__ior__(right)"])
def test_mapping_union_preserves_receiver_and_source_representations(backend, expression):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(dedent(f'''
        from pyjs import int8
        def main() -> int:
            left = {{1: int8(127)}}
            right = {{2: int8(-128)}}
            result = {expression}
            return len(result)
    '''), wrap=False, environment=environment) as analysis:
        expected = compound_representation(arguments=(None,
            direct_representation(NumericFormat("integer", 8, True), None),
        ))
        for name in ("left", "right", "result"):
            value = analysis.entry_point.scope.lookup(name)
            assert value.cls.generic_name == "dict"
            assert value.representation == expected


@pytest.mark.parametrize("first", ["remember('next')", "state.remember('next')"])
def test_lazy_module_imports_share_objects_in_both_resolution_orders(first):
    from pyjs.analysis.objects import DeferredDefinition, DeferredValue

    with analyze_ir(f'''
        import tests.native.persistent_values as state
        from tests.native.persistent_values import VALUES, ALIAS, remember

        def main() -> bool:
            {first}
            return VALUES is state.VALUES and ALIAS is VALUES
    ''') as analysis:
        module = analysis.entry_point.container
        state = module.search("state").target
        assert module.search("VALUES") is state.search("VALUES")
        assert module.search("ALIAS") is state.search("VALUES")
        assert module.search("remember") is state.search("remember")
        assert isinstance(state.scope.names["UNUSED"], DeferredValue)
        assert isinstance(state.scope.names["unrelated"], DeferredDefinition)
        assert sum(value.name == "VALUES" for value in analysis.entry_point.compilation_objects) == 1


@pytest.mark.parametrize("name", ["factory", "Record"])
def test_same_module_import_resolution_materializes_deferred_definitions(name):
    from pyjs.analysis.objects import (
        Class,
        DeferredDefinition,
        Function,
        resolve_imported,
    )

    with analyze_ir('''
        class Record:
            pass

        def factory() -> Record:
            return Record()

        def main() -> int:
            return 42
    ''') as analysis:
        module = analysis.entry_point.container
        deferred = module.scope.names[name]
        assert isinstance(deferred, DeferredDefinition)
        resolved = resolve_imported(deferred.py_obj, module)
        assert isinstance(resolved, Function if name == "factory" else Class)
        assert resolved is module.search(name)
        assert resolve_imported(deferred.py_obj, module) is resolved


def test_bound_callback_lifetime_retains_its_receiver():
    with analyze_ir('''
        from typing import Callable

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def add(self, number: int) -> int:
                return self.value + number

        def bind(value: Counter) -> Callable[[int], int]:
            return value.add

        def create() -> Callable[[int], int]:
            return bind(Counter(40))

        def main() -> int:
            callback = create()
            return callback(2)
    ''') as analysis:
        module = analysis.entry_point.container
        assert module.search("bind").ir.lifetime.returned_parameters == frozenset({"value"})
        assert module.search("create").ir.lifetime.allocations[0].boundary is LifetimeBoundary.CALLER


def test_chained_comparison_temporaries_preserve_operand_lifetimes():
    with analyze_ir('''
        class Box:
            def __init__(self, value: int):
                self.value = value

        class Keeper:
            def __init__(self, saved: list[Box]):
                self.saved = saved

            def __eq__(self, other: Box) -> bool:
                self.saved.append(other)
                return True

        def compare(keeper: Keeper, sentinel: Box) -> bool:
            return keeper == Box(7) is not sentinel

        def main() -> int:
            saved: list[Box] = []
            compare(Keeper(saved), Box(0))
            return saved[0].value
    ''') as analysis:
        allocations = analysis.entry_point.container.search("compare").ir.lifetime.allocations
        assert {allocation.operation.value_type.name: allocation.boundary for allocation in allocations} == {
            "Box": LifetimeBoundary.CALLER,
        }


def test_iterator_advance_preserves_the_loop_location_with_destructuring():
    with analyze_ir("def main() -> int:\n    for left, right in [(1, 2)]:\n        pass\n    return 0\n") as analysis:
        advances = [statement for block in analysis.entry_point.ir.blocks
                    for statement in block.body if isinstance(statement, IteratorNext)]
        assert len(advances) == 1
        assert (advances[0].lineno, advances[0].col_offset, advances[0].end_lineno) == (2, 4, 3)


def test_iterator_creation_retains_protocol_and_virtual_override():
    with analyze_ir('''
        from collections.abc import Iterator

        class Values:
            def __iter__(self) -> Iterator[int]:
                return iter([1])
            def unused(self) -> int:
                return 99

        class Derived(Values):
            def __iter__(self) -> Iterator[int]:
                return iter([2])

        def total(values: Values) -> int:
            result = 0
            for value in values:
                result += value
            return result

        def main() -> int:
            return total(Derived())
    ''') as analysis:
        module = analysis.entry_point.container
        program = build_program_ir(analysis.entry_point)
        methods = tuple(module.search(name).find_attrs("__iter__") for name in ("Values", "Derived"))
        assert all(method in program.functions for method in methods)
        assert module.search("Values").find_attrs("unused") not in program.functions
        creations = [statement for block in module.search("total").ir.blocks
                     for statement in block.body if isinstance(statement, IteratorCreate)]
        assert len(creations) == 1
        assert creations[0].runtime_methods == methods[:1]
        validate_program_ir(program)


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
@pytest.mark.parametrize("expression", ["iter([int8(1)])", "iter(pull, int8(0))"])
def test_shared_native_iterator_declaration_is_analyzer_neutral(backend, expression):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(dedent(f'''
        from pyjs import int8

        def pull() -> int8:
            return int8(1)

        def main() -> int8:
            cursor = {expression}
            return next(cursor)
    '''), wrap=False, environment=environment) as analysis:
        cursor = analysis.entry_point.scope.lookup("cursor")
        assert cursor.type.generic_name == "Iterator"
        assert cursor.representation == compound_representation(
            arguments=(direct_representation(NumericFormat("integer", 8, True), None),),
        )
    # This checks the shared declaration only, not runtime iterator support in
    # JVM/WASM: those emitters keep their existing unsupported boundaries.


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
@pytest.mark.parametrize("expression", ["iter()", "iter(pull, 1, 2)"])
def test_shared_iterator_arity_errors_precede_protocol_validation(backend, expression):
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with pytest.raises(CompilationError) as caught, analyze_source(dedent(f'''
        def pull() -> int:
            return 1

        def main() -> int:
            return next({expression})
    '''), wrap=False, environment=environment):
        pass
    assert "[PYJS1104]" in str(caught.value)
    assert "iter() requires one or two positional arguments" in str(caught.value)


def test_iterator_acquisition_tracks_virtual_receiver_retention():
    with analyze_ir('''
        from collections.abc import Iterator

        class Values:
            def __init__(self, saved: list[Values]):
                self.saved = saved
                self.value = 7
            def __iter__(self) -> Iterator[int]:
                return iter([self.value])

        class Retained(Values):
            def __iter__(self) -> Iterator[int]:
                self.saved.append(self)
                return iter([self.value])

        def consume(values: Values) -> None:
            for value in values:
                pass

        def remember(saved: list[Values]) -> None:
            consume(Retained(saved))

        def main() -> int:
            saved: list[Values] = []
            remember(saved)
            return saved[0].value
    ''') as analysis:
        module = analysis.entry_point.container
        assert module.search("remember").ir.lifetime.allocations[0].boundary is not LifetimeBoundary.LOCAL
        assert module.search("consume").ir.lifetime.external_parameters == frozenset({"values"})


@pytest.mark.parametrize("comparison, boundary", [
    ("left == right", LifetimeBoundary.CALLER),
    ("left != right", LifetimeBoundary.CALLER),
    ("left == right is not left", LifetimeBoundary.CALLER),
    ("left != right is not left", LifetimeBoundary.CALLER),
    ("left.__eq__(right)", LifetimeBoundary.LOCAL),
])
def test_reflected_comparison_lifetimes_bind_both_operands(comparison, boundary):
    with analyze_ir(f'''
        class Base:
            def __init__(self, value: int):
                self.value = value

            def __eq__(self, other: "Base") -> bool:
                return True

        class Child(Base):
            def __init__(self, saved: list[Base]):
                super().__init__(1)
                self.saved = saved

            def __eq__(self, other: Base) -> bool:
                self.saved.append(other)
                return True

        def retain(right: Base) -> bool:
            left = Base(7)
            return {comparison}

        def main() -> int:
            saved: list[Base] = []
            retain(Child(saved))
            return len(saved)
    ''') as analysis:
        module = analysis.entry_point.container
        assert module.search("Child").find("__eq__").ir.lifetime.parameter_containment == (("self", "other"),)
        [allocation] = module.search("retain").ir.lifetime.allocations
        assert allocation.boundary is boundary


@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
@pytest.mark.parametrize("retaining", [False, True])
@pytest.mark.parametrize("receiver", ["Base", "Middle"])
def test_late_comparison_protocol_lifetimes_stay_in_the_receiver_family(method, retaining, receiver):
    with analyze_ir(f'''
        class Base:
            def __init__(self, value: int):
                self.value = value
            def __eq__(self, other: "Base") -> bool:
                return False

        class Middle(Base):
            pass

        class Child(Middle):
            def __init__(self, saved: list[Base]):
                super().__init__(1)
                self.saved = saved
            def {method}(self, other: Base) -> bool:
                {"self.saved.append(other)" if retaining else "pass"}
                return True

        class Unrelated:
            def __init__(self, saved: list[Base]):
                self.saved = saved
            def {method}(self, other: Base) -> bool:
                self.saved.append(other)
                return True

        def retain(right: {receiver}) -> bool:
            left = {receiver}(7)
            return left != right

        def main() -> int:
            saved: list[Base] = []
            retain(Child(saved))
            Unrelated(saved).{method}(Base(9))
            return len(saved)
    ''') as analysis:
        module = analysis.entry_point.container
        lifetime = module.search("retain").ir.lifetime
        [allocation] = lifetime.allocations
        expected = LifetimeBoundary.CALLER if retaining else LifetimeBoundary.LOCAL
        assert allocation.boundary is expected
        dependencies = dict(lifetime.call_dependencies)
        child_method = module.search("Child").find(method)
        unrelated_method = module.search("Unrelated").find(method)
        assert child_method in dependencies
        assert unrelated_method in analysis.entry_point.compilation_objects
        assert unrelated_method not in dependencies


@pytest.mark.parametrize("body", [
    "items = create()\n    return contains(items)",
    "return contains(create())",
])
def test_collection_equality_reaches_default_object_overrides_in_either_order(body):
    with analyze_ir(dedent('''
        class Base:
            pass

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                return True

        class Unused(Base):
            def __eq__(self, other: Base) -> bool:
                return False

        def contains(items: list[Base]) -> bool:
            return Base() in items

        def create() -> list[Base]:
            return [Child()]
    ''') + '\ndef main() -> bool:\n    ' + body + '\n') as analysis:
        module = analysis.entry_point.container
        reached = analysis.entry_point.compilation_objects
        method = module.search("Child").find("__eq__")
        assert method in reached
        assert method.ir is not None
        assert module.search("Unused").find("__eq__") not in reached


@pytest.mark.parametrize("contract, boundary", [
    ("BORROWED", LifetimeBoundary.LOCAL),
    ("EXTERNAL", LifetimeBoundary.EXTERNAL),
])
@pytest.mark.parametrize("comparison", ["left != right", "right.__ne__(left)"])
def test_reached_protocol_declarations_supply_lifetime_contracts(contract, boundary, comparison):
    # This is an analysis contract for external backends, not an implementation
    # of the probe operation. No native emitter is asked to execute its body.
    with analyze_ir(f'''
        from pyjs.decorators import native_operation, ParameterLifetime
        class Base:
            def __init__(self, value: int):
                self.value = value
            def __eq__(self, other: "Base") -> bool:
                return True
        class Child(Base):
            @native_operation("probe", self=ParameterLifetime.BORROWED,
                              other=ParameterLifetime.{contract})
            def __ne__(self, other: Base) -> bool: ...
        def retain(right: Base) -> bool:
            left = Base(7)
            return {comparison}
        def main() -> int:
            retain(Child(1))
            return 0
    ''') as analysis:
        module = analysis.entry_point.container
        method = module.search("Child").find("__ne__")
        assert method in analysis.entry_point.compilation_objects
        assert method.ir.lifetime is None
        [allocation] = module.search("retain").ir.lifetime.allocations
        assert allocation.boundary is boundary


def test_integer_index_contract_composes_with_shared_analysis_metadata():
    @integer_index_parameters("count")
    @preserves_numeric_format
    def repeat(value, count):
        return value * count

    assert analysis_metadata(repeat, "integer_index_parameters") == ("count",)
    assert analysis_metadata(repeat, "preserves_numeric_format") is True


@pytest.mark.parametrize(
    "parameters",
    ((), ("",), ("count", "count"), ("missing",)),
)
def test_integer_index_contract_rejects_invalid_parameters(parameters):
    def repeat(value, count):
        return value * count

    with pytest.raises(TypeError, match="integer-index parameters"):
        integer_index_parameters(*parameters)(repeat)


def test_normal_analysis_keeps_the_python_shaped_tree():
    with analyze_source(
        dedent(
            """
            def main() -> str:
                return "high level"
            """
        ),
        wrap=False,
    ) as analysis:
        assert analysis.entry_point.ir is None
        assert "block entry" not in analysis.types
        assert "return 'high level'" in analysis.types


def test_analysis_preserves_backend_neutral_numeric_formats():
    with analyze_ir(
        """
        from pyjs import float32, int8, int16, int32, int64

        type Byte = int8
        type Sample = float32

        class Reading:
            value: int16

            def __init__(self, value: int16) -> None:
                self.value = value

        def main(value: Byte, *, scale: Sample) -> int64:
            local: int64 = int64(value + 1)
            return int64(Reading(int16(local)).value)
        """
    ) as analysis:
        function = analysis.entry_point
        program = build_program_ir(function)
        reading = next(
            layout for layout in program.classes if layout.value_type.name == "Reading"
        )

        assert function.params[0].representation.numeric == NumericFormat(
            "integer",
            8,
            True,
        )
        assert not hasattr(function.params[0], "numeric_format")
        assert function.kwonlyargs[0].representation.numeric == NumericFormat(
            "float",
            32,
        )
        assert function.return_numeric_format == NumericFormat("integer", 64, True)
        assert function.scope.lookup("local").representation.numeric == NumericFormat(
            "integer",
            64,
            True,
        )
        assert not hasattr(function.scope.lookup("local"), "numeric_format")
        assert reading.fields[0].numeric_format == NumericFormat(
            "integer",
            16,
            True,
        )


def test_analysis_preserves_backend_neutral_static_array_layouts():
    with analyze_ir(
        """
        from pyjs import StaticArray, float32, int16

        type Samples = StaticArray[float32, 4]

        class Reading:
            samples: Samples

            def __init__(self, samples: Samples) -> None:
                self.samples = samples

        def main(values: StaticArray[int16, 3]) -> Samples:
            samples: Samples = [
                float32(values[0]),
                float32(values[1]),
                0.0,
                1.0,
            ]
            return Reading(samples).samples
        """
    ) as analysis:
        function = analysis.entry_point
        program = build_program_ir(function)
        reading = next(
            layout for layout in program.classes if layout.value_type.name == "Reading"
        )

        assert function.params[0].representation.array == ArrayFormat(
            3,
            item_numeric=NumericFormat("integer", 16, True),
        )
        assert not hasattr(function.params[0], "array_format")
        assert function.return_array_format == ArrayFormat(
            4,
            item_numeric=NumericFormat("float", 32),
        )
        assert reading.fields[0].array_format == function.return_array_format


def test_annotated_static_array_fields_keep_their_ir_layout():
    with analyze_ir(
        """
        from typing import Annotated

        from pyjs import StaticArray, int8

        class Reading:
            samples: Annotated[StaticArray[int8, 2], "samples"]

            def __init__(
                self,
                samples: Annotated[StaticArray[int8, 2], "samples"],
            ) -> None:
                self.samples = samples

        def main(values: StaticArray[int8, 2]) -> int:
            return Reading(values).samples[0]
        """
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        reading = next(
            layout for layout in program.classes if layout.value_type.name == "Reading"
        )

        assert reading.fields[0].array_format == ArrayFormat(
            2,
            item_numeric=NumericFormat("integer", 8, True),
        )


def test_analysis_preserves_recursive_compound_representations():
    with analyze_ir(
        """
        from pyjs import int8

        class Reading:
            samples: dict[str, list[int8]]

            def __init__(self, samples: dict[str, list[int8]]) -> None:
                self.samples = samples

        def main(values: list[int8], value: int8 | None) -> list[int8]:
            if value is not None:
                values.append(value)
            Reading({"samples": values})
            return values
        """
    ) as analysis:
        function = analysis.entry_point
        program = build_program_ir(function)
        reading = next(
            layout for layout in program.classes if layout.value_type.name == "Reading"
        )
        byte = NumericFormat("integer", 8, True)

        assert function.params[0].representation.arguments[0].numeric == byte
        assert function.params[1].representation.kind == "union"
        assert function.params[1].representation.arguments[0].numeric == byte
        assert function.return_representation.arguments[0].numeric == byte
        field = reading.fields[0].representation
        assert field.arguments[0] is None
        assert field.arguments[1].arguments[0].numeric == byte
        validate_program_ir(program)


def test_ir_validator_checks_compound_static_array_items():
    with analyze_ir(
        """
        from pyjs import StaticArray, int8

        def main(values: StaticArray[list[int8], 1]) -> int:
            return values[0][0]
        """
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        parameter = analysis.entry_point.params[0]
        parameter.representation = array_representation(
            parameter.representation.array,
            compound_representation(
                arguments=(direct_representation(NumericFormat("float", 32), None),)
            ),
        )

        with pytest.raises(IRValidationError) as caught:
            validate_program_ir(program)

        assert str(caught.value) == (
            "main parameter values item member 0 has float storage for int"
        )


def test_ir_analysis_renders_the_exact_conditional_graph():
    with analyze_ir(
        """
        def choose(changed: bool) -> str:
            if changed:
                return "changed"
            return "default"

        def main() -> str:
            return choose(True)
        """
    ) as analysis:
        assert (
            analysis.types
            == dedent(
                """
            def choose(changed: bool) -> str:
                block entry:
                    branch changed:
                        true -> if_true
                        false -> if_done
                block if_true:
                    return 'changed'
                block if_done:
                    return 'default'

            def main() -> str:
                block entry:
                    return choose(True)
            """
            ).strip()
        )


def test_ir_loop_edges_preserve_break_and_for_else_behavior():
    with analyze_ir(
        """
        def main(count: int = 5) -> int:
            total = 0
            for index in range(count):
                if index == 3:
                    break
                total = total + index
            else:
                return total
            return -1
        """
    ) as analysis:
        assert (
            analysis.types
            == dedent(
                """
            def main(count: int=5) -> int:
                block entry:
                    total: int = 0
                    iterator = iter(range(count))
                    jump for_next
                block for_next:
                    branch_next iterator:
                        item index: int -> for_body
                        done -> for_else
                block for_body:
                    branch index.[int]__eq__(3):
                        true -> if_true
                        false -> if_done
                block if_true:
                    jump for_done
                block if_done:
                    total = total.[int]__add__(index)
                    jump for_next
                block for_else:
                    return total
                block for_done:
                    return -1
            """
            ).strip()
        )


def test_ir_analysis_does_not_analyze_unreachable_functions():
    with analyze_ir(
        """
        def unused(value: bool) -> str:
            return "yes" if value else "no"

        def main() -> int:
            return 42
        """
    ) as analysis:
        unused = analysis.entry_point.container.search("unused")

        assert unused.ir is None
        assert "unused" not in analysis.types


def test_ir_lazily_reaches_ordinary_imported_definitions(tmp_path, monkeypatch):
    module_name = "pyjs_ir_imported_helper"
    helper = tmp_path / f"{module_name}.py"
    helper.write_text(
        dedent(
            """
            class Counter:
                def __init__(self, value: int):
                    self.value = value


            def increment(value: int) -> int:
                return value + 1


            def unused(value: int) -> int:
                return value * 100
            """
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)

    with analyze_ir(
        f"""
        from {module_name} import Counter, increment, unused

        def main() -> int:
            counter = Counter(40)
            return increment(counter.value)
        """
    ) as analysis:
        package = analysis.entry_point.container.container
        imported = package[module_name]
        program = build_program_ir(analysis.entry_point)

        assert imported.search("increment") in program.functions
        assert any(
            layout.value_type is imported.search("Counter")
            for layout in program.classes
        )
        assert imported.search("unused").ir is None
        assert imported.search("unused") not in program.functions


def test_ir_defers_unreached_module_aliases(tmp_path, monkeypatch):
    helper_name = "pyjs_ir_module_helper"
    unused_name = "pyjs_ir_unused_module"
    (tmp_path / f"{helper_name}.py").write_text(
        "def increment(value: int) -> int:\n    return value + 1\n"
    )
    (tmp_path / f"{unused_name}.py").write_text(
        "def unused() -> int:\n    return 100\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(helper_name, None)
    sys.modules.pop(unused_name, None)

    with analyze_ir(
        f"""
        import {helper_name}
        import {unused_name}

        def main() -> int:
            return {helper_name}.increment(41)
        """
    ) as analysis:
        package = analysis.entry_point.container.container

        assert helper_name in package
        assert unused_name not in package


def test_ir_lowers_objects_collections_and_fields_without_runtime_layout():
    with analyze_ir(
        """
        class Item:
            def __init__(self, name: str):
                self.name = name

            @property
            def label(self) -> str:
                return self.name

            @label.setter
            def label(self, value: str) -> None:
                self.name = value


        def main() -> str:
            item = Item("first")
            item.name = "second"
            item.label = "third"
            values = [item]
            values.append(Item(item.name))
            pair = (item, "label")
            lookup = {"first": item}
            unique = {"first"}
            left, right = ("left", "right")
            return item.label
        """
    ) as analysis:
        assert (
            analysis.types
            == dedent(
                """
            class Item:

                def __init__(name: str) -> None:
                    block entry:
                        store_field(self, name, name)
                        return None

                @property
                def label() -> str:
                    block entry:
                        return load_field(self, name)

                @label.setter
                def label(value: str) -> None:
                    block entry:
                        store_field(self, name, value)
                        return None

            def main() -> str:
                block entry:
                    item: Item = new[external] Item('first')
                    store_field(item, name, 'second')
                    item.label = 'third'
                    values: list[Item] = new[local] list[Item](item)
                    list_append(values, new[local] Item(load_field(item, name)))
                    pair: tuple[Item, str] = new[local] tuple[Item, str](item, 'label')
                    lookup: dict[str, Item] = new[local] dict[str, Item]('first': item)
                    unique: set[str] = new[local] set[str]('first')
                    $assignment5: tuple[str, str] = new[local] tuple[str, str]('left', 'right')
                    $assignment9: int = len($assignment5)
                    branch $assignment9.[int]__lt__(2):
                        true -> if_true
                        false -> if_done
                block if_true:
                    raise ValueError(f"not enough values to unpack (expected 2, got {format($assignment9, '')})")
                block if_done:
                    branch $assignment9.[int]__gt__(2):
                        true -> if_true_2
                        false -> if_done_2
                block if_true_2:
                    raise ValueError(f"too many values to unpack (expected 2, got {format($assignment9, '')})")
                block if_done_2:
                    $assignment10: str = $assignment5.[tuple__str_str]__getitem__(0)
                    $assignment11: str = $assignment5.[tuple__str_str]__getitem__(1)
                    left: str = $assignment10
                    right: str = $assignment11
                    return item.label
            """
            ).strip()
        )


def test_ir_super_selects_the_existing_receiver_without_allocating_a_base():
    with analyze_ir(
        """
        class Base:
            def __init__(self, value: int):
                self.value = value

        class Child(Base):
            def __init__(self, value: int, extra: int):
                super().__init__(value)
                self.extra = extra

        def main() -> int:
            Child(2, 3)
            return 1
        """
    ) as analysis:
        assert "super().[Base]__init__(value)" in analysis.types
        assert "new[local] Base" not in analysis.types


def test_program_ir_preserves_only_reachable_class_layouts():
    with analyze_ir(
        """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Record:
            name: str
            enabled: bool = True

        @dataclass
        class Unused:
            value: str

        class Base:
            def __init__(self, value: str):
                self.value = value

        class Derived(Base):
            pass

        def main() -> tuple[Record, Derived]:
            return Record("ready"), Derived("inherited")
        """
    ) as analysis:
        module = analysis.entry_point.container
        record = module.search("Record")
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        layout = next(
            layout for layout in program.classes if layout.value_type is record
        )
        derived = module.search("Derived")
        derived_layout = next(
            layout for layout in program.classes if layout.value_type is derived
        )

        assert program.entry_point is analysis.entry_point
        assert layout.base.name == "object"
        assert [field.name for field in layout.fields] == ["name", "enabled"]
        assert [field.value_type.name for field in layout.fields] == ["str", "bool"]
        assert layout.constructor is record.find("__init__")
        assert layout.frozen
        assert analysis.entry_point in program.functions
        assert record.find("__init__") in program.functions
        assert derived_layout.base is module.search("Base")
        assert derived_layout.constructor is module.search("Base").find("__init__")
        assert derived_layout.constructor in program.functions
        assert not any(
            layout.value_type.name == "Unused" for layout in program.classes
        )


def test_program_ir_retains_nested_input_layouts_without_constructor_bodies():
    with analyze_ir(
        """
        class Detail:
            def __init__(self, label: str):
                self.label = label

        class Record:
            def __init__(self, detail: Detail):
                self.detail = detail

        class Unused:
            def __init__(self, value: int):
                self.value = value

        def main(values: list[Record]) -> str:
            return values[0].detail.label
        """
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        layouts = {
            layout.value_type.name: layout
            for layout in program.classes
            if layout.value_type.container is analysis.entry_point.container
        }
        assert {
            name: [(field.name, field.value_type.name) for field in layout.fields]
            for name, layout in layouts.items()
        } == {"Detail": [("label", "str")], "Record": [("detail", "Detail")]}
        assert all(layout.constructor not in program.functions for layout in layouts.values())


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
def test_program_ir_retains_local_annotation_layouts_without_reaching_constructors(backend):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    with analyze_source(dedent('''
        class Key:
            pass
        class Record:
            key: Key
            def __init__(self, key: Key):
                self.key = key
        class Unused:
            pass
        def main() -> int:
            records: list[Record] = []
            values: dict[Key, int] = {}
            return len(records) + len(values)
    '''), wrap=False, environment=environment) as analysis:
        program = build_program_ir(analysis.entry_point)
        validate_program_ir(program)
        layouts = {layout.value_type.name: layout for layout in program.classes
                   if layout.value_type.container is analysis.entry_point.container}
        assert set(layouts) == {"Key", "Record"}
        assert [(field.name, field.value_type.name) for field in layouts["Record"].fields] == [("key", "Key")]
        # Key inherits object.__init__, which other reached builtins may use.
        assert layouts["Record"].constructor not in program.functions


def test_program_ir_validator_rejects_missing_reachable_functions():
    with analyze_ir(
        """
        def helper() -> int:
            return 1

        def main() -> int:
            return helper()
        """
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        functions = tuple(
            function
            for function in program.functions
            if function.name != "helper"
        )

        with pytest.raises(IRValidationError, match="calls absent function helper"):
            validate_program_ir(
                ProgramIR(program.entry_point, program.classes, functions)
            )


def test_program_ir_validator_rejects_incorrect_jump_arity():
    with analyze_ir(
        """
        def choose(flag: bool, left: int, right: int) -> int:
            return left if flag else right

        def main() -> int:
            return choose(True, 1, 2)
        """
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        choose = analysis.entry_point.container.search("choose")
        jump = next(
            statement
            for block in choose.ir.blocks
            for statement in block.body
            if isinstance(statement, Jump)
        )
        jump.arguments.clear()

        with pytest.raises(IRValidationError, match="passes 0 arguments; expected 1"):
            validate_program_ir(program)


@pytest.mark.parametrize("terminator_type", [Branch, IteratorNext])
def test_program_ir_validator_rejects_arguments_on_implicit_edges(
    terminator_type,
):
    with analyze_ir(
        """
        def select(flag: bool) -> int:
            if flag:
                return 1
            return 2

        def iterate(values: list[int]) -> int:
            for value in values:
                return value
            return 0

        def main() -> int:
            return select(True) + iterate([3])
        """
    ) as analysis:
        program = build_program_ir(analysis.entry_point)
        terminator = next(
            statement
            for function in program.functions
            for block in function.ir.blocks
            if hasattr(block, "body")
            for statement in block.body
            if isinstance(statement, terminator_type)
        )
        target = terminator.true if isinstance(terminator, Branch) else terminator.body
        block = next(
            block
            for function in program.functions
            for block in function.ir.blocks
            if getattr(block, "name", None) == target
        )
        block.arguments.append(object())

        with pytest.raises(IRValidationError, match="cannot provide 1 arguments"):
            validate_program_ir(program)


def test_parameter_lifetime_contracts_are_validated_and_immutable():
    def relay(value):
        return value

    with pytest.raises(TypeError, match="invalid parameter lifetime contracts"):
        configure_parameter_lifetimes(relay, {"value": "returned"})
    with pytest.raises(TypeError, match="parameters do not exist: typo"):
        configure_parameter_lifetimes(
            relay,
            {"typo": ParameterLifetime.RETURNED},
        )

    configure_parameter_lifetimes(
        relay,
        {"value": ParameterLifetime.RETURNED},
    )
    contracts = parameter_lifetimes(relay)
    with pytest.raises(TypeError):
        contracts["value"] = ParameterLifetime.EXTERNAL


def test_ir_summarizes_allocation_and_parameter_lifetimes():
    with analyze_ir(
        """
        class Box:
            def __init__(self, value: list[str]):
                self.value = value

        def expose(value: list[str]) -> None:
            sink(value)

        def sink(value: list[str]) -> None:
            pass

        def relay(value: list[str]) -> list[str]:
            return value

        def choose_second(first: Box, second: Box) -> Box:
            return second

        def keyword_relay(
            **values: list[str],
        ) -> dict[str, list[str]]:
            return values

        def retain(target: list[str], value: str) -> None:
            target.append(value)

        def retain_lists(
            target: list[list[str]],
            value: list[str],
        ) -> None:
            target.append(value)

        def spread(*values: Box) -> None:
            pass

        def package() -> Box:
            values = ["packed"]
            return Box(values)

        def spread_case() -> int:
            item = Box(["spread"])
            values = [item]
            spread(*values)
            return 1

        def return_case() -> list[str]:
            values = ["returned"]
            alias = relay(values)
            return alias

        def starred_return_case() -> Box:
            first = Box(["first"])
            second = Box(["second"])
            values = [first, second]
            return choose_second(*values)

        def keyword_return_case() -> dict[str, list[str]]:
            value = ["keyword"]
            return keyword_relay(item=value)

        def retain_case() -> list[list[str]]:
            target: list[list[str]] = []
            value = ["retained"]
            retain_lists(target, value)
            return target

        def main() -> int:
            values = ["first"]
            sink(values)
            relay(values)
            retain(values, "second")
            expose(values)
            package()
            spread_case()
            return_case()
            starred_return_case()
            keyword_return_case()
            retain_case()
            return 1
        """
    ) as analysis:
        module = analysis.entry_point.container

        assert module.search("sink").ir.lifetime.parameters == {
            "value": LifetimeBoundary.LOCAL,
        }
        relay_lifetime = module.search("relay").ir.lifetime
        assert relay_lifetime.parameters == {
            "value": LifetimeBoundary.CALLER,
        }
        assert relay_lifetime.returned_parameters == frozenset({"value"})
        assert module.search("retain").ir.lifetime.parameters == {
            "target": LifetimeBoundary.LOCAL,
            "value": LifetimeBoundary.CALLER,
        }
        assert module.search("retain_lists").ir.lifetime.parameter_containment == (
            ("target", "value"),
        )
        assert module.search("expose").ir.lifetime.parameters == {
            "value": LifetimeBoundary.LOCAL,
        }
        assert module.search("Box").find("__init__").ir.lifetime.parameters == {
            "value": LifetimeBoundary.CALLER,
            "self": LifetimeBoundary.LOCAL,
        }
        assert [
            allocation.boundary
            for allocation in module.search("package").ir.lifetime.allocations
        ] == [
            LifetimeBoundary.CALLER,
            LifetimeBoundary.CALLER,
        ]
        assert [
            allocation.boundary
            for allocation in module.search("spread_case").ir.lifetime.allocations
        ] == [
            LifetimeBoundary.LOCAL,
            LifetimeBoundary.LOCAL,
            LifetimeBoundary.LOCAL,
        ]
        assert [
            allocation.boundary
            for allocation in module.search("return_case").ir.lifetime.allocations
        ] == [LifetimeBoundary.CALLER]
        assert [
            allocation.boundary
            for allocation in module.search(
                "starred_return_case"
            ).ir.lifetime.allocations
        ] == [
            LifetimeBoundary.CALLER,
            LifetimeBoundary.CALLER,
            LifetimeBoundary.CALLER,
            LifetimeBoundary.CALLER,
            LifetimeBoundary.LOCAL,
        ]
        assert [
            allocation.boundary
            for allocation in module.search(
                "keyword_return_case"
            ).ir.lifetime.allocations
        ] == [LifetimeBoundary.CALLER]
        assert [
            allocation.boundary
            for allocation in module.search("retain_case").ir.lifetime.allocations
        ] == [
            LifetimeBoundary.CALLER,
            LifetimeBoundary.CALLER,
        ]
        allocation = module.search("main").ir.lifetime.allocations[0]
        assert allocation.site == 1
        assert allocation.boundary is LifetimeBoundary.LOCAL
        assert allocation.reasons == set()


def test_ir_lifetimes_cover_constructor_dispatch_and_member_escape_paths():
    with analyze_ir(
        """
        class Box:
            def __init__(self, value: int):
                self.value = value


        class Retainer:
            def __init__(self, sink: list[Box], value: Box):
                sink.append(value)


        class Base:
            def __init__(self, value: Box):
                self.value = value

            def keep(self, value: Box) -> None:
                pass


        class Child(Base):
            def keep(self, value: Box) -> None:
                self.value = value


        def construct(sink: list[Box]) -> None:
            value = Box(1)
            Retainer(sink, value)


        def dispatch(target: Base) -> None:
            value = Box(2)
            target.keep(value)


        def first(values: list[Box]) -> Box:
            return values[0]


        def iterated(values: list[Box]) -> Box:
            for value in values:
                return value
            return values[0]


        def either(
            left: list[Box],
            right: list[Box],
        ) -> list[Box]:
            return left or right


        def main() -> tuple[list[Box], Base, Box, Box, list[Box]]:
            sink: list[Box] = []
            construct(sink)
            target: Base = Child(Box(3))
            dispatch(target)
            first_value = first([Box(4)])
            iterated_value = iterated([Box(5)])
            selected = either([Box(6)], [Box(7)])
            return sink, target, first_value, iterated_value, selected
        """
    ) as analysis:
        module = analysis.entry_point.container

        assert module.search("construct").ir.lifetime.allocations[0].boundary is (
            LifetimeBoundary.CALLER
        )
        assert module.search("dispatch").ir.lifetime.allocations[0].boundary is (
            LifetimeBoundary.CALLER
        )
        assert module.search("first").ir.lifetime.returned_parameters == frozenset(
            {"values"}
        )
        assert module.search("iterated").ir.lifetime.returned_parameters == frozenset(
            {"values"}
        )
        assert module.search("either").ir.lifetime.returned_parameters == frozenset(
            {"left", "right"}
        )


def test_ir_lifetimes_cover_destructuring_and_indexed_mutation():
    with analyze_ir(
        """
        class Box:
            def __init__(self, value: int):
                self.value = value


        def assigned(values: tuple[Box, Box]) -> Box:
            left, right = values
            return left


        def iterated(values: list[tuple[Box, Box]]) -> Box | None:
            for left, right in values:
                return right
            return None


        def nested(values: tuple[tuple[Box, Box], Box]) -> Box:
            (left, right), last = values
            return right


        def mutate(values: list[Box]) -> None:
            value = Box(1)
            values[0] = value


        def main() -> int:
            first = Box(2)
            second = Box(3)
            assigned((first, second))
            iterated([(first, second)])
            nested(((first, second), first))
            values = [first]
            mutate(values)
            return 0
        """
    ) as analysis:
        module = analysis.entry_point.container

        for name in ("assigned", "iterated", "nested"):
            assert module.search(name).ir.lifetime.returned_parameters == frozenset(
                {"values"}
            ), name
        allocation = module.search("mutate").ir.lifetime.allocations[0]
        assert allocation.boundary is LifetimeBoundary.CALLER
        assert "subscript store" in allocation.reasons


@pytest.mark.parametrize("bound_override", [False, True])
def test_ir_static_method_value_retains_possible_bound_override(bound_override):
    decorator = "" if bound_override else "@staticmethod"
    receiver = "self, " if bound_override else ""
    with analyze_ir(f'''
        from collections.abc import Callable
        class Base:
            @staticmethod
            def value(number: int) -> int:
                return number
        class Child(Base):
            {decorator}
            def value({receiver}number: int) -> int:
                return number + 1
        def bind(value: Base) -> Callable[[int], int]:
            return value.value
        def make() -> Callable[[int], int]:
            return bind(Child())
        def main() -> int:
            return make()(1)
    ''') as analysis:
        module = analysis.entry_point.container
        expected = frozenset({"value"}) if bound_override else frozenset()
        assert module.search("bind").ir.lifetime.returned_parameters == expected
        expected_boundary = LifetimeBoundary.CALLER if bound_override else LifetimeBoundary.LOCAL
        assert module.search("make").ir.lifetime.allocations[0].boundary is expected_boundary
