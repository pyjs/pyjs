import ast
from textwrap import dedent

import pytest

from pyjs import int8
from pyjs.analysis.diagnostics import CompilationError, DiagnosticCode
from pyjs.analysis.ir import CollectionNew, FieldStore
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import at
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

SOURCE = dedent("""
    from pyjs import js
    @js
    class Row:
        def __init__(self, count: int):
            self.count = count
    @js
    def make(count: int) -> Row:
        return Row(count)
    def main() -> int:
        rows: list[Row] = []
        rows.append(make(0))
        rows[0].count = 5
        return rows[0].count
""")


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
def test_inherited_factory_field_waits_for_effective_initializer(environment):
    source = '''
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
        def main() -> int:
            value = make()
            value.count = 42
            return value.count
    '''
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        child = analysis.entry_point.scope.lookup("value").cls
        field = child.super._self.find_attrs("count")
        assert child._self.find_attrs("count") is field
        assert field.cls.generic_name == "int"
    if environment is None:
        at(source, """
            class Parent:

                def __init__(count: int) -> None:
                    self.count = count

            class Child(Parent):

            def make() -> Child:
                return Child(2)

            def main() -> int:
                value: Child = make()
                value.count = 42
                return value.count
        """, """
            export class Parent {

                constructor(count) {
                    this.count = count;
                }
            }

            export class Child extends Parent {
            }

            export function make() {
                return new Child(2);
            }

            export function main() {
                var value = make();
                value.count = 42;
                return value.count;
            }
        """)


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
@pytest.mark.parametrize("declared", [False, True], ids=["builtin-init", "inherited-init"])
def test_missing_inherited_field_points_only_to_application_initializer(environment, declared):
    initializer = "def __init__(self):\n        self.ready = True" if declared else "pass"
    source = f'''
from pyjs import js
@js
class Parent:
    {initializer}
@js
class Child(Parent):
    def read(self):
        return self.missing
def main():
    return Child().read()
'''
    with pytest.raises(CompilationError) as caught:
        with analyze_source(source, wrap=False, environment=environment, filename="inherited_missing.py"):
            pass
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == DiagnosticCode.UNDEFINED_ATTRIBUTE
    assert diagnostic.message == "Attribute 'missing' is not defined on 'Child'"
    assert diagnostic.help == ("Define self.missing in Child.__init__().",)
    primary = diagnostic.primary.span
    assert primary.source.filename.endswith("inherited_missing.py")
    assert primary.source.lines[primary.start_position.line].strip() == "return self.missing"
    assert len(diagnostic.secondary) == int(declared)
    if declared:
        note = diagnostic.secondary[0]
        assert note.message == "initialize instance attributes here"
        assert note.span.source.filename.endswith("inherited_missing.py")
        assert note.span.source.lines[note.span.start_position.line].strip() == "def __init__(self):"


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
@pytest.mark.parametrize("method", ["__init__", "put"])
@pytest.mark.parametrize("class_body", [False, True], ids=["initializer", "class-body"])
@pytest.mark.parametrize("annotation, field_type, initial, value", [
    ("object", object, "None", "'text'"),
    ("int8 | None", int8 | None, "None", "int8(7)"),
    ("list[list[int8]]", list[list[int8]], "[]", "[[int8(7)]]"),
])
def test_inherited_declared_field_keeps_storage(environment, method, class_body, annotation, field_type, initial, value):
    initialize = "super().__init__()" if method == "__init__" else "pass"
    source = f'''
        from pyjs import js, int8
        @js
        class Parent:
            {f"saved: {annotation}" if class_body else "pass"}
            def __init__(self):
                self.saved{'' if class_body else ': ' + annotation} = {initial}
        @js
        class Child(Parent):
            def {method}(self):
                {initialize}
                self.saved = {value}
        def main() -> Child:
            child = Child()
            {"child.put()" if method == "put" else "pass"}
            return child
    '''
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        child = analysis.entry_point.return_type
        declared = child.super._self.find_attrs("saved")
        # Storage identity/metadata is the contract: neither AST rendering nor
        # a successful assignment alone detects an accidental subclass slot.
        assert declared.has_declared_type
        assert declared.representation == annotation_representation(field_type)
        assert child._self.find_attrs("saved") is declared
        assert "saved" not in child._self.attrs


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
@pytest.mark.parametrize("method", ["__init__", "put"])
@pytest.mark.parametrize("class_body", [False, True], ids=["initializer", "class-body"])
def test_inherited_declared_field_rejects_incompatible_write(environment, method, class_body):
    initialize = "super().__init__()" if method == "__init__" else "pass"
    source = f'''
        from pyjs import js
        @js
        class Parent:
            {"saved: int | None" if class_body else "pass"}
            def __init__(self):
                self.saved{'' if class_body else ': int | None'} = None
        @js
        class Child(Parent):
            def {method}(self):
                {initialize}
                self.saved = 'invalid'
        def main() -> Child:
            child = Child()
            {"child.put()" if method == "put" else "pass"}
            return child
    '''
    with pytest.raises(CompilationError) as caught:
        with analyze_source(source, wrap=False, environment=environment, filename="inherited_field.py"):
            pass
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == DiagnosticCode.INCOMPATIBLE_ASSIGNMENT
    assert diagnostic.message == "Cannot assign str to 'saved' of type int|NoneType"
    span = diagnostic.primary.span
    assert span.source.filename.endswith("inherited_field.py")
    assert span.source.lines[span.start_position.line].strip() == "self.saved = 'invalid'"


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
def test_subclass_write_does_not_narrow_later_field_reads(environment):
    source = '''
        from pyjs import js
        @js
        class Box:
            def __init__(self):
                self.value = 3
        @js
        class Parent:
            def __init__(self):
                self.saved: Box | None = None
        @js
        class Child(Parent):
            def read(self) -> int:
                self.saved = Box()
                return self.saved.value
        def main() -> int:
            return Child().read()
    '''
    with pytest.raises(CompilationError, match="Attribute 'value' is not defined on every member"):
        with analyze_source(source, wrap=False, environment=environment):
            pass


def test_class_declared_field_keeps_parent_alias_writes_in_javascript():
    at('''
        @js
        class Parent:
            saved: int | None
            def __init__(self):
                self.saved = None
        @js
        class Child(Parent):
            def put(self):
                self.saved = 7
        def main() -> int | None:
            child = Child()
            child.put()
            alias: Parent = child
            alias.saved = None
            return child.saved
    ''', '''
        class Parent:

            def __init__() -> None:
                self.saved = None

        class Child(Parent):

            def put() -> None:
                self.saved = 7

        def main() -> int | None:
            child: Child = Child()
            child.[Child]put()
            alias: Parent = child
            alias.saved = None
            return child.saved
    ''', '''
        export class Parent {

            constructor() {
                this.saved = null;
            }
        }

        export class Child extends Parent {

            put() {
                this.saved = 7;
            }
        }

        export function main() {
            var child = new Child();
            child.put();
            var alias = child;
            alias.saved = null;
            return child.saved;
        }
    ''')


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
@pytest.mark.parametrize("annotation,value", [("int8", "int16(1)"), ("list[int8]", "[int16(1)]")])
def test_inherited_class_declarations_reject_different_numeric_widths(environment, annotation, value):
    source = f'''
        from pyjs import js, int8, int16
        @js
        class Parent:
            saved: {annotation}
        @js
        class Child(Parent):
            def __init__(self):
                self.saved = {value}
        def main() -> Child:
            return Child()
    '''
    with pytest.raises(CompilationError, match="different fixed-width numeric types"):
        with analyze_source(source, wrap=False, environment=environment):
            pass


@pytest.mark.parametrize("backend", ["native", "java", "webassembly"])
@pytest.mark.parametrize("annotation, initial, value", [
    ("list[int | str]", "[]", "[3]"),
    ("set[tuple[int] | str]", "{'old'}", "{(3,)}"),
    ("dict[str, list[int | str]]", "{}", "{'row': [3]}"),
    ("tuple[list[int | str]]", "([],)", "([3],)"),
])
def test_field_literal_ir_uses_destination_storage(backend, annotation, initial, value):
    from pyjs.java.analysis import JVM_ENVIRONMENT
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    environment = {"native": NATIVE_ENVIRONMENT, "java": JVM_ENVIRONMENT,
                   "webassembly": WEBASSEMBLY_ENVIRONMENT}[backend]
    source = f'''
        class Holder:
            def __init__(self):
                self.values: {annotation} = {initial}
        def main() -> int:
            holder = Holder()
            holder.values = {value}
            return len(holder.values)
    '''
    with analyze_source(dedent(source), wrap=False, environment=environment) as analysis:
        stores = [statement for block in analysis.entry_point.ir.blocks for statement in block.body
                  if isinstance(statement, FieldStore)]
        assert len(stores) == 1
        store = stores[0]
        assert isinstance(store.value, CollectionNew)
        assert store.value.value_type is store.target.obj.cls
        allocations = [node for node in ast.walk(store.value) if isinstance(node, CollectionNew)]
        if annotation.startswith("dict"):
            assert allocations[1].value_type is store.value.value_type.generic_types["V"]
        elif annotation.startswith("tuple"):
            assert allocations[1].value_type is next(iter(store.value.value_type.generic_types.values()))


def test_field_literal_context_preserves_rhs_first_javascript():
    at('''
        @js
        class Holder:
            def __init__(self):
                self.values: list[int | str] = []
        @js
        def target(holder: Holder) -> Holder:
            return holder
        def main() -> int:
            holder = Holder()
            target(holder).values = [3]
            holder.values.append('item')
            return len(holder.values)
    ''', '''
        class Holder:

            def __init__() -> None:
                self.values: list[int | str] = []

        def target(holder: Holder) -> Holder:
            return holder

        def main() -> int:
            holder: Holder = Holder()
            target(holder).values = [3]
            holder.values.[list__intUstr]append!('item')
            return holder.values.[list__intUstr]__len__!()
    ''', '''
        export class Holder {

            constructor() {
                this.values = [];
            }
        }

        export function target(holder) {
            return holder;
        }

        export function main() {
            var holder = new Holder();
            const $assignment_rhs0 = [3];
            target(holder).values = $assignment_rhs0;
            (holder.values.push('item'), null);
            return holder.values.length;
        }
    ''')


@pytest.mark.parametrize("annotation, initial, value, message", [
    ("list[int8]", "[]", "[int16(1)]", "different fixed-width numeric types"),
    ("set[tuple[int] | str]", "{'old'}", "{(1.5,)}", "Cannot assign"),
    ("dict[str, list[int | str]]", "{}", "{'row': [1.5]}", "Cannot assign"),
])
def test_field_literal_context_still_checks_types_and_representations(annotation, initial, value, message):
    source = f'''
        from pyjs import int8, int16
        class Holder:
            def __init__(self):
                self.values: {annotation} = {initial}
        def main() -> int:
            holder = Holder()
            holder.values = {value}
            return len(holder.values)
    '''
    with pytest.raises(CompilationError, match=message):
        with analyze_source(dedent(source), wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


def test_factory_field_assignment_keeps_typed_target_and_rhs_first_javascript():
    at(
        SOURCE.replace("rows[0].count = 5", "rows[0].count = make(7).count"),
        """
        class Row:

            def __init__(count: int) -> None:
                self.count = count

        def make(count: int) -> Row:
            return Row(count)

        def main() -> int:
            rows: list[Row] = []
            rows.[list__Row]append!(make(0))
            $get_list_item(rows, 0).count = make(7).count
            return $get_list_item(rows, 0).count
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Row {

            constructor(count) {
                this.count = count;
            }
        }

        export function make(count) {
            return new Row(count);
        }

        export function main() {
            var rows = [];
            (rows.push(make(0)), null);
            const $assignment_rhs0 = make(7).count;
            $get_list_item(rows, 0).count = $assignment_rhs0;
            return $get_list_item(rows, 0).count;
        }
        """,
    )


def test_factory_field_assignment_waits_for_constructor_in_ir_analysis():
    with analyze_source(SOURCE, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.types == dedent("""
            class Row:

                def __init__(count: int) -> None:
                    block entry:
                        store_field(self, count, count)
                        return None

            def make(count: int) -> Row:
                block entry:
                    return new[caller] Row(count)

            def main() -> int:
                block entry:
                    rows: list[Row] = new[local] list[Row]()
                    list_append(rows, make(0))
                    store_field(rows.[list__Row]__getitem__(0), count, 5)
                    return load_field(rows.[list__Row]__getitem__(0), count)
        """).strip()


def test_augmented_item_assignment_captures_receiver_index_and_old_value():
    at(
        "values = [3]\nvalues[0] += 2",
        """
        values: list[int] = [3]
        $assignment1: list[int] = values
        $assignment2: int = 0
        $assignment3: int = $get_list_item($assignment1, $assignment2).[int]__add__!(2)
        $set_list_item($assignment1, $assignment2, $assignment3)
        """,
        """
        import { get_list_item as $get_list_item, set_list_item as $set_list_item } from './pyjs.python.js';

        var values = [3];
        var $assignment1 = values;
        var $assignment2 = 0;
        var $assignment3 = $get_list_item($assignment1, $assignment2) + 2;
        $set_list_item($assignment1, $assignment2, $assignment3);
        """,
    )


def test_augmented_class_fields_keep_static_receivers():
    at(
        """
        from typing import ClassVar

        @js
        class Counter:
            total: ClassVar[int] = 0

            def __init__(self):
                Counter.total += 1

            @classmethod
            def bump(cls) -> int:
                cls.total += 2
                return cls.total

        def main() -> int:
            Counter()
            return Counter.bump()
        """,
        """
        class Counter:
            total: __static__ = 0

            def __init__() -> None:
                Counter.total = Counter.total.[int]__add__!(1)

            def bump() -> int:
                this.total = this.total.[int]__add__!(2)
                return this.total

        def main() -> int:
            Counter()
            return Counter.[Counter]bump()
        """,
        """
        export class Counter {
            static total = 0;

            constructor() {
                Counter.total = Counter.total + 1;
            }

            static bump() {
                this.total = this.total + 2;
                return this.total;
            }
        }

        export function main() {
            new Counter();
            return Counter.bump();
        }
        """,
    )


@pytest.mark.parametrize("environment", [{}, {"environment": NATIVE_ENVIRONMENT}], ids=["JS", "IR"])
@pytest.mark.parametrize("receiver", ["rows[0]", "make(0)"])
@pytest.mark.parametrize("prefix", ["", "copied = "])
@pytest.mark.parametrize("assignment,code,message", [
    ("count = 'bad'", DiagnosticCode.INCOMPATIBLE_ASSIGNMENT, "Cannot assign str to 'count' of type int"),
    ("missing = 5", DiagnosticCode.UNDEFINED_ATTRIBUTE, "Attribute 'missing' is not defined on 'Row'"),
])
def test_factory_field_assignment_has_located_type_and_missing_field_errors(environment, receiver, prefix, assignment, code, message):
    statement = f"{prefix}{receiver}.{assignment}"
    source = SOURCE.replace("rows[0].count = 5", statement)
    with pytest.raises(CompilationError) as caught:
        with analyze_source(source, wrap=False, filename="field_assignment.py", **environment):
            pass
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == code
    assert diagnostic.message == message
    span = diagnostic.primary.span
    assert span.source.filename.endswith("field_assignment.py")
    assert span.source.lines[span.start_position.line].strip() == statement
