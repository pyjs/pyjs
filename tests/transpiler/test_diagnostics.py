import ast
import linecache
import sys

import pytest

from pyjs.analysis.diagnostics import (
    CompilationError,
    SourceFile,
    SourceFragment,
    format_compilation_error,
)
from pyjs.analysis.source import create_module
from pyjs.javascript.source import analyze_source
from pyjs.testing.helpers import (
    ad,
    assert_compilation_diagnostic,
    assert_module_transpile,
    diagnostic_text,
)


@pytest.mark.parametrize('separator', ['\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'])
@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
def test_source_spans_follow_python_physical_lines(separator, newline):
    lines = ['"""before' + separator + 'after"""' + newline,
             'label = "🐍"; result = missing' + newline]
    text = ''.join(lines)
    source = SourceFile.from_text('example.py', text)
    node = next(node for node in ast.walk(ast.parse(text))
                if isinstance(node, ast.Name) and node.id == 'missing')
    span = SourceFragment(source).span(node)
    assert source.lines == lines
    assert source.line_text(2) == lines[1]
    assert text.encode()[span.start:span.end] == b'missing'
    assert span.start_position.line == 1
    assert span.end_position.line == 1
    assert source.character_column(2, span.start_position.column) == lines[1].index('missing')
    assert source.character_column(2, span.end_position.column) == lines[1].index('missing') + 7


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
@pytest.mark.parametrize('expression', [
    'str(\n    )', '[\n        "🐍",\n    ]', '{\n        "🐍": 42,\n    }',
    '(\n        "🐍",\n    )', '("🐍"\n        + "x"\n    )',
])
def test_multiline_expression_spans_match_cpython(expression, newline):
    text = ('def answer():\n    value = ' + expression + '\n    other = 3\n').replace('\n', newline)
    source = SourceFile.from_text('example.py', text)
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.expr):
            continue
        span = SourceFragment(source).span(node)
        assert text.encode()[span.start:span.end].decode() == ast.get_source_segment(text, node)
        assert (span.start_position.line, span.start_position.column) == (node.lineno - 1, node.col_offset)
        assert (span.end_position.line, span.end_position.column) == (node.end_lineno - 1, node.end_col_offset)


@pytest.mark.parametrize(("call", "expected"), [
    ('Child("wrong")', diagnostic_text(
        "constructor.py", 9, 'return Child("wrong")', "             ^^^^^^^",
        "pyjs.CompilationError: Argument 'count' to Base.__init__ expects int, got str [PYJS1104]",
        "help: Pass a value compatible with int.",
    )),
    ("Child()", diagnostic_text(
        "constructor.py", 9, "return Child()", "       ^^^^^^^",
        "pyjs.CompilationError: __init__() is missing required argument(s): 'count' [PYJS1104]",
        "help: Pass every required argument.",
    )),
    ("Base(1, 2)", diagnostic_text(
        "constructor.py", 9, "return Base(1, 2)", "               ^",
        "pyjs.CompilationError: __init__() received too many positional arguments [PYJS1104]",
        "help: Pass at most 1 positional arguments.",
    )),
])
def test_custom_element_constructor_arguments_are_checked(call, expected):
    ad(
        f'''\
        from pyjs.web.domx import CustomElement
        class Base(CustomElement):
            def __init__(self, count: int):
                super().__init__()
                self.count = count
        class Child(Base):
            pass
        def main():
            return {call}
        ''',
        expected,
        filename="constructor.py",
        wrap=False,
    )


def test_undefined_name_points_to_the_name():
    diagnostic = ad(
        """\
        def main():
            print(missing)
        """,
        diagnostic_text(
            "unknown.py",
            2,
            "print(missing)",
            "      ^^^^^^^",
            "pyjs.CompilationError: Name 'missing' is not defined [PYJS1001]",
        ),
        filename="unknown.py",
    )

    assert diagnostic.to_dict() == {
        "code": "PYJS1001",
        "severity": "error",
        "message": "Name 'missing' is not defined",
        "primary": {
            "file": "unknown.py",
            "start": {"line": 1, "column": 10},
            "end": {"line": 1, "column": 17},
            "message": None,
        },
        "secondary": [],
        "notes": [],
        "help": [],
    }


def test_undefined_name_suggests_a_close_visible_name():
    ad(
        """\
        def main():
            total = 3
            print(ttoal)
        """,
        diagnostic_text(
            "typo.py",
            3,
            "print(ttoal)",
            "      ^^^^^",
            "pyjs.CompilationError: Name 'ttoal' is not defined [PYJS1001]",
            "help: Did you mean 'total'?",
        ),
        filename="typo.py",
    )


def test_module_constant_suggests_an_inferred_js_binding():
    ad(
        """\
        from pyjs import js

        LIMIT = 3

        @js
        def current() -> int:
            return LIMIT

        print(current())
        """,
        diagnostic_text(
            "constant.py",
            5,
            "return LIMIT",
            "       ^^^^^",
            "pyjs.CompilationError: Name 'LIMIT' is a Python value, not a "
            "client value [PYJS1004]",
            "help: Import JS from pyjs and declare it as a client value: "
            "LIMIT: JS = 3.",
        ),
        filename="constant.py",
    )


def test_external_library_definition_does_not_suggest_editing_it():
    ad(
        """\
        from pathlib import Path

        print(Path(".").name)
        """,
        diagnostic_text(
            "external.py",
            4,
            "print(Path('.').name)",
            "      ^^^^",
            "pyjs.CompilationError: Class 'Path' is not available to client "
            "code [PYJS1002]",
            "help: 'Path' comes from external module 'pathlib'. Use a supported "
            "PyJS API or add a client binding for that library.",
        ),
        filename="external.py",
    )


@pytest.mark.parametrize(
    ("source", "underline", "message", "help_text"),
    [
        (
            'print(b"abc")',
            "      ^^^^^^",
            "bytes literals are not supported",
            "Use str for text or a supported typed-array API for binary data.",
        ),
        (
            "print(1 + 2j)",
            "          ^^",
            "complex number literals are not supported",
            "Represent the real and imaginary components explicitly.",
        ),
        (
            "print(...)",
            "      ^^^",
            "ellipsis values are not supported",
            "Use None or an explicit client-side sentinel value.",
        ),
    ],
)
def test_unsupported_literals_have_located_diagnostics(
    source,
    underline,
    message,
    help_text,
):
    ad(
        source,
        diagnostic_text(
            "literal.py",
            1,
            source,
            underline,
            f"pyjs.CompilationError: {message} [PYJS2001]",
            f"help: {help_text}",
        ),
        filename="literal.py",
    )


def test_calling_a_non_callable_expression_has_a_located_diagnostic():
    ad(
        """\
        def main():
            (1 + 2)()
        """,
        diagnostic_text(
            "not_callable.py",
            2,
            "(1 + 2)()",
            " ^^^^^",
            "pyjs.CompilationError: Value of type int is not callable "
            "[PYJS1104]",
            "help: Call a function, class, or typed Callable value.",
        ),
        filename="not_callable.py",
    )


def test_missing_module_member_has_a_located_diagnostic():
    ad(
        """\
        import math

        def main():
            math.not_a_member(1)
        """,
        diagnostic_text(
            "module_member.py",
            4,
            "math.not_a_member(1)",
            "^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Module 'math' has no attribute 'not_a_member' [PYJS1003]",
        ),
        filename="module_member.py",
    )


def test_calling_a_module_has_a_located_diagnostic():
    ad(
        """\
        import math

        def main():
            math()
        """,
        diagnostic_text(
            "module_call.py",
            4,
            "math()",
            "^^^^",
            "pyjs.CompilationError: Module 'math' is not callable [PYJS1104]",
            "help: Call a function or class defined by the module instead.",
        ),
        filename="module_call.py",
    )


def test_context_manager_unpacking_has_a_located_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        class Pair:
            def __enter__(self) -> tuple[int, int]:
                return 1, 2

            def __exit__(
                self,
                kind: object,
                value: object,
                trace: object,
            ) -> None:
                pass

        @js
        def main() -> None:
            with Pair() as (left, right):
                print(left + right)
        """,
        diagnostic_text(
            "with_unpack.py",
            18,
            "with Pair() as (left, right):",
            "               ^^^^^^^^^^^^^",
            "pyjs.CompilationError: context-manager result unpacking is not "
            "supported [PYJS2001]",
            "help: Bind the result to one name, then unpack it in the with block.",
        ),
        filename="with_unpack.py",
    )


def test_undefined_name_uses_character_columns_after_unicode():
    diagnostic = ad(
        """\
        def main():
            print("é", missing)
        """,
        diagnostic_text(
            "unicode.py",
            2,
            'print("é", missing)',
            "           ^^^^^^^",
            "pyjs.CompilationError: Name 'missing' is not defined [PYJS1001]",
        ),
        filename="unicode.py",
    )

    assert diagnostic.to_dict() == {
        "code": "PYJS1001",
        "severity": "error",
        "message": "Name 'missing' is not defined",
        "primary": {
            "file": "unicode.py",
            "start": {"line": 1, "column": 15},
            "end": {"line": 1, "column": 22},
            "message": None,
        },
        "secondary": [],
        "notes": [],
        "help": [],
    }


def test_python_function_without_js_decorator_points_to_its_definition():
    ad(
        """\
        from pyjs import js

        def helper():
            return 1

        def main():
            print(helper())
        """,
        diagnostic_text(
            "decorator.py",
            7,
            "print(helper())",
            "      ^^^^^^",
            "pyjs.CompilationError: Function 'helper' is not available to "
            "client code [PYJS1002]",
            "note: decorator.py:3:5: defined here without client compilation enabled",
            "help: Decorate 'helper' with @js.",
        ),
        filename="decorator.py",
    )


def test_missing_decorator_suggests_importing_js_when_needed():
    ad(
        """\
        class Helper:
            pass

        def main():
            Helper()
        """,
        diagnostic_text(
            "class_decorator.py",
            5,
            "Helper()",
            "^^^^^^",
            "pyjs.CompilationError: Class 'Helper' is not available to client code "
            "[PYJS1002]",
            "note: class_decorator.py:1:7: defined here without client compilation "
            "enabled",
            "help: Import js from pyjs and decorate 'Helper' with @js.",
        ),
        filename="class_decorator.py",
    )


def test_imported_python_function_points_to_its_source_definition():
    module_name = "_pyjs_diagnostic_provider"
    create_module(
        "def helper():\n    return 1\n",
        filename="provider.py",
        module_name=module_name,
    )
    try:
        ad(
            f"""\
            from {module_name} import helper

            def main():
                helper()
            """,
            diagnostic_text(
                "consumer.py",
                4,
                "helper()",
                "^^^^^^",
                "pyjs.CompilationError: Function 'helper' is not available to "
                "client code [PYJS1002]",
                "note: provider.py:1:5: defined here without client compilation "
                "enabled",
                "help: Import js from pyjs and decorate 'helper' with @js.",
            ),
            filename="consumer.py",
            module_name="_pyjs_diagnostic_consumer",
        )
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("_pyjs_diagnostic_consumer", None)


def test_nojs_definition_suggests_removing_the_exclusion():
    ad(
        """\
        from pyjs import nojs

        @nojs
        def helper():
            return 1

        def main():
            helper()
        """,
        diagnostic_text(
            "nojs.py",
            8,
            "helper()",
            "^^^^^^",
            "pyjs.CompilationError: Function 'helper' is not available to client code "
            "[PYJS1002]",
            "note: nojs.py:4:5: defined here without client compilation enabled",
            "help: Remove @nojs from 'helper' if it should run in the browser.",
        ),
        filename="nojs.py",
    )


def test_python_module_value_suggests_an_explicit_client_binding():
    ad(
        """\
        server_value = "server only"

        def main():
            print(server_value)
        """,
        diagnostic_text(
            "binding.py",
            4,
            "print(server_value)",
            "      ^^^^^^^^^^^^",
            "pyjs.CompilationError: Name 'server_value' is a Python value, not a "
            "client value [PYJS1004]",
            "help: Import JS from pyjs and annotate the existing assignment "
            "with JS so its value is available to client code.",
        ),
        filename="binding.py",
    )


def test_undefined_self_attribute_points_to_init():
    ad(
        """\
        from pyjs import js

        @js
        class App:
            def __init__(self):
                self.ready = True

            def run(self):
                print(self.missing)

        def main():
            App().run()
        """,
        diagnostic_text(
            "attribute.py",
            9,
            "print(self.missing)",
            "      ^^^^^^^^^^^^",
            "pyjs.CompilationError: Attribute 'missing' is not defined on 'App' "
            "[PYJS1003]",
            "note: attribute.py:5:9: initialize instance attributes here",
            "help: Define self.missing in App.__init__().",
        ),
        filename="attribute.py",
    )


def test_undefined_self_attribute_suggests_a_close_attribute():
    ad(
        """\
        from pyjs import js

        @js
        class App:
            def __init__(self):
                self.label = "ready"

            def run(self):
                print(self.lable)

        def main():
            App().run()
        """,
        diagnostic_text(
            "attribute_typo.py",
            9,
            "print(self.lable)",
            "      ^^^^^^^^^^",
            "pyjs.CompilationError: Attribute 'lable' is not defined on 'App' "
            "[PYJS1003]",
            "note: attribute_typo.py:5:9: initialize instance attributes here",
            "help: Did you mean 'self.label'?",
        ),
        filename="attribute_typo.py",
    )


def test_undefined_self_attribute_without_init_still_explains_the_convention():
    ad(
        """\
        from pyjs import js

        @js
        class App:
            def run(self):
                print(self.missing)

        def main():
            App().run()
        """,
        diagnostic_text(
            "attribute_without_init.py",
            6,
            "print(self.missing)",
            "      ^^^^^^^^^^^^",
            "pyjs.CompilationError: Attribute 'missing' is not defined on 'App' "
            "[PYJS1003]",
            "help: Define self.missing in App.__init__().",
        ),
        filename="attribute_without_init.py",
    )


def test_assignment_can_establish_an_attribute_in_a_lifecycle_method():
    assert_module_transpile(
        """\
        from pyjs import js

        @js
        class App:
            def hydrate(self):
                self.value = "ready"

            def read(self):
                print(self.value)

        def main():
            app = App()
            app.hydrate()
            app.read()
        """,
        """
        export class App {

            hydrate() {
                this.value = 'ready';
            }

            read() {
                console.log(this.value);
            }
        }

        export function main() {
            var app = new App();
            app.hydrate();
            app.read();
        }
        """,
        filename="lifecycle.py",
    )


def test_annotation_can_declare_an_attribute_for_a_lifecycle_method():
    assert_module_transpile(
        """\
        from pyjs import js

        @js
        class App:
            value: str

            def hydrate(self):
                self.value = "ready"

            def read(self):
                print(self.value)

        def main():
            app = App()
            app.hydrate()
            app.read()
        """,
        """
        export class App {

            hydrate() {
                this.value = 'ready';
            }

            read() {
                console.log(this.value);
            }
        }

        export function main() {
            var app = new App();
            app.hydrate();
            app.read();
        }
        """,
        filename="annotated_lifecycle.py",
    )


def test_annotation_declared_attribute_rejects_an_incompatible_assignment():
    ad(
        """\
        from pyjs import js

        @js
        class App:
            value: str

            def hydrate(self):
                self.value = 1

        def main():
            App().hydrate()
        """,
        diagnostic_text(
            "annotated_lifecycle.py",
            8,
            "self.value = 1",
            "^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign int to 'value' of type str "
            "[PYJS1103]",
            "help: Assign a value compatible with str or change the annotation for "
            "'value'.",
        ),
        filename="annotated_lifecycle.py",
    )


def test_annotation_declaration_ignores_a_same_named_class_method():
    assert_module_transpile(
        """\
        from pyjs import js

        @js
        class App:
            values: list[int]

            def list(self):
                self.values = [1]

            def read(self):
                print(self.values[0])

        def main():
            app = App()
            app.list()
            app.read()
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class App {

            list() {
                this.values = [1];
            }

            read() {
                console.log($get_list_item(this.values, 0));
            }
        }

        export function main() {
            var app = new App();
            app.list();
            app.read();
        }
        """,
        filename="annotation_method_collision.py",
    )


def test_nested_attribute_assignment_waits_for_the_owner_initializer():
    assert_module_transpile(
        """\
        from pyjs import js

        @js
        class App:
            def __init__(self):
                self.timer: int | None = None

        @js
        class Listener:
            def __init__(self, app: App):
                self.app = app

            def connect(self):
                self.app.timer = 1

        def main():
            Listener(App()).connect()
        """,
        """
        export class App {

            constructor() {
                this.timer = null;
            }
        }

        export class Listener {

            constructor(app) {
                this.app = app;
            }

            connect() {
                this.app.timer = 1;
            }
        }

        export function main() {
            new Listener(new App()).connect();
        }
        """,
        filename="nested_assignment.py",
    )


def test_parameter_without_type_annotation_points_to_the_parameter():
    ad(
        """\
        def main(value):
            print(value)
        """,
        diagnostic_text(
            "parameter.py",
            1,
            "def main(value):",
            "         ^^^^^",
            "pyjs.CompilationError: Parameter 'value' requires a type annotation "
            "[PYJS1101]",
            "help: Annotate 'value' with the value type expected by this function.",
        ),
        filename="parameter.py",
    )


def test_instance_method_requires_a_self_receiver():
    ad(
        """\
        from pyjs import js

        @js
        class Counter:
            def increment(value: int) -> int:
                return value + 1

        def main():
            Counter().increment()
        """,
        diagnostic_text(
            "method_receiver.py",
            5,
            "def increment(value: int) -> int:",
            " " * 14 + "^" * 10,
            "pyjs.CompilationError: PyJS instance methods require a first "
            "parameter named 'self' [PYJS2001]",
            "help: Add or rename the first parameter to self, or decorate the "
            "method with @staticmethod.",
        ),
        filename="method_receiver.py",
    )


def test_instance_method_requires_a_receiver_parameter():
    ad(
        """\
        from pyjs import js

        @js
        class Counter:
            def increment() -> int:
                return 1

        def main():
            Counter().increment()
        """,
        diagnostic_text(
            "missing_receiver.py",
            5,
            "def increment() -> int:",
            "^" * 23,
            "pyjs.CompilationError: PyJS instance methods require a first "
            "parameter named 'self' [PYJS2001]",
            "help: Add or rename the first parameter to self, or decorate the "
            "method with @staticmethod.",
        ),
        filename="missing_receiver.py",
    )


def test_class_method_requires_a_cls_receiver():
    ad(
        """\
        from pyjs import js

        @js
        class Counter:
            @classmethod
            def build(self) -> int:
                return 1

        def main():
            Counter.build()
        """,
        diagnostic_text(
            "class_receiver.py",
            6,
            "def build(self) -> int:",
            " " * 10 + "^" * 4,
            "pyjs.CompilationError: PyJS class methods require a first "
            "parameter named 'cls' [PYJS2001]",
            "help: Add or rename the first parameter to cls.",
        ),
        filename="class_receiver.py",
    )


def test_empty_collection_requires_an_explicit_type_annotation():
    ad(
        """\
        def main():
            values = []
        """,
        diagnostic_text(
            "collection.py",
            2,
            "values = []",
            "^^^^^^",
            "pyjs.CompilationError: Type of 'values' cannot be inferred [PYJS1101]",
            "help: Add an explicit type annotation for 'values'.",
        ),
        filename="collection.py",
    )


def test_empty_generic_constructor_requires_type_context():
    ad(
        """\
        def main():
            values = set()
        """,
        diagnostic_text(
            "generic_constructor.py",
            2,
            "values = set()",
            " " * 9 + "^" * 5,
            "pyjs.CompilationError: Type arguments for set() cannot be "
            "inferred [PYJS1101]",
            "help: Add an explicit specialized annotation that provides the "
            "missing types.",
        ),
        filename="generic_constructor.py",
    )


def test_generic_constructor_reports_a_missing_argument_before_inference():
    ad(
        """\
        from pyjs import js

        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value

        def main():
            Box()
        """,
        diagnostic_text(
            "generic_constructor.py",
            9,
            "Box()",
            "^^^^^",
            "pyjs.CompilationError: Invalid Box() constructor arguments: "
            "missing a required argument: 'value' [PYJS1104]",
            "help: Pass arguments accepted by Box.__init__().",
        ),
        filename="generic_constructor.py",
    )


def test_generic_constructor_reports_an_unexpected_keyword_before_inference():
    ad(
        """\
        from pyjs import js

        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value

        def main():
            Box(other=1)
        """,
        diagnostic_text(
            "generic_constructor.py",
            9,
            "Box(other=1)",
            "    ^^^^^^^",
            "pyjs.CompilationError: Box() got an unexpected keyword argument "
            "'other' [PYJS1104]",
            "help: Remove 'other' or pass a parameter accepted by "
            "Box.__init__().",
        ),
        filename="generic_constructor.py",
    )


def test_builtin_constructor_reports_a_positional_only_keyword():
    ad(
        """\
        def main():
            list(values=[1])
        """,
        diagnostic_text(
            "generic_constructor.py",
            2,
            "list(values=[1])",
            "     ^^^^^^^^^^",
            "pyjs.CompilationError: list() parameter 'values' is "
            "positional-only [PYJS1104]",
            "help: Pass 'values' as a positional argument.",
        ),
        filename="generic_constructor.py",
    )


@pytest.mark.parametrize("expression", ["type(value)", "type[int](value)"])
def test_runtime_type_introspection_has_a_located_diagnostic(expression):
    ad(
        f"""\
        def main(value: int):
            kind = {expression}
        """,
        diagnostic_text(
            "runtime_type.py",
            2,
            f"kind = {expression}",
            " " * 7 + "^" * len(expression),
            "pyjs.CompilationError: runtime type() introspection is not "
            "supported [PYJS2001]",
            "help: Use static annotations or a supported isinstance() check "
            "instead.",
        ),
        filename="runtime_type.py",
    )


def test_generic_return_requires_type_arguments():
    ad(
        """\
        def main() -> list:
            return []
        """,
        diagnostic_text(
            "return_type.py",
            1,
            "def main() -> list:",
            "              ^^^^",
            "pyjs.CompilationError: Return type 'list' requires type arguments "
            "[PYJS1101]",
            "help: Use list[...] to describe the returned values.",
        ),
        filename="return_type.py",
    )


def test_inline_interface_requires_a_return_annotation():
    ad(
        """\
        from pyjs import js

        @js
        def doubled(value: int): ...

        @doubled.inline
        def doubled(value, **kwargs):
            return f"({value} * 2)"

        def main():
            print(doubled(2))
        """,
        diagnostic_text(
            "inline_return.py",
            4,
            "def doubled(value: int): ...",
            "^" * 28,
            "pyjs.CompilationError: Function 'doubled' requires a return type "
            "annotation [PYJS1101]",
            "help: Add -> ReturnType so PyJS can type-check calls to this source "
            "or inline implementation.",
        ),
        filename="inline_return.py",
    )


def test_incompatible_attribute_assignment_reports_both_types():
    ad(
        """\
        from pyjs import js

        @js
        class App:
            def __init__(self):
                self.value: int = 1
                self.value = "wrong"

        def main():
            App()
        """,
        diagnostic_text(
            "assignment_type.py",
            7,
            'self.value = "wrong"',
            "^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign str to 'value' of type int "
            "[PYJS1103]",
            "help: Assign a value compatible with int or change the annotation for "
            "'value'.",
        ),
        filename="assignment_type.py",
    )


def test_isinstance_narrowing_does_not_leak_into_false_branch():
    ad(
        """\
        from pyjs.web.dom import Element
        from pyjs.web.html import HTMLInputElement

        def main(target: Element):
            if isinstance(target, HTMLInputElement):
                print(target.value)
            else:
                print(target.value)
        """,
        diagnostic_text(
            "false_narrowing.py",
            8,
            "print(target.value)",
            " " * 6 + "^" * 12,
            "pyjs.CompilationError: Attribute 'value' is not defined on "
            "'Element' [PYJS1003]",
            "help: Use an attribute supported by PyJS for 'Element' or "
            "implement an equivalent client helper.",
        ),
        filename="false_narrowing.py",
    )


def test_bare_container_isinstance_narrowing_does_not_leak_into_false_branch():
    ad(
        """\
        def main(value: object):
            if isinstance(value, set):
                value.add("ok")
            else:
                value.add("bad")
        """,
        diagnostic_text(
            "false_container_narrowing.py",
            5,
            'value.add("bad")',
            "^" * 9,
            "pyjs.CompilationError: Attribute 'add' is not defined on "
            "'object' [PYJS1003]",
            "help: Use an attribute supported by PyJS for 'object' or "
            "implement an equivalent client helper.",
        ),
        filename="false_container_narrowing.py",
    )


def test_unsupported_builtin_attribute_has_a_located_diagnostic():
    ad(
        """\
        def main():
            print("12".isdigit())
        """,
        diagnostic_text(
            "unsupported_builtin_attribute.py",
            2,
            'print("12".isdigit())',
            " " * 6 + "^" * 12,
            "pyjs.CompilationError: Attribute 'isdigit' is not defined on "
            "'str' [PYJS1003]",
            "help: Use an attribute supported by PyJS for 'str' or implement "
            "an equivalent client helper.",
        ),
        filename="unsupported_builtin_attribute.py",
    )


def test_misspelled_builtin_attribute_suggests_a_supported_member():
    ad(
        """\
        def main(value: str):
            print(value.uppper())
        """,
        diagnostic_text(
            "misspelled_builtin_attribute.py",
            2,
            "print(value.uppper())",
            " " * 6 + "^" * 12,
            "pyjs.CompilationError: Attribute 'uppper' is not defined on "
            "'str' [PYJS1003]",
            "help: Did you mean 'value.upper'?",
        ),
        filename="misspelled_builtin_attribute.py",
    )


def test_specialized_class_without_library_metadata_keeps_attribute_diagnostic():
    ad(
        """\
        from typing import Literal
        def main(value: Literal['x']):
            print(value.absent)
        """,
        diagnostic_text(
            "literal_attribute.py", 3, "print(value.absent)",
            " " * 6 + "^" * 12,
            "pyjs.CompilationError: Attribute 'absent' is not defined on "
            "'str' [PYJS1003]",
            "help: Use an attribute supported by PyJS for 'str' or implement "
            "an equivalent client helper.",
        ),
        filename="literal_attribute.py",
    )


def test_union_field_read_reports_members_missing_the_field():
    ad(
        """\
        from pyjs import js

        @js
        class Left:
            def __init__(self):
                self.value = "left"

        @js
        class Right:
            def __init__(self):
                self.other = "right"

        @js
        def read(item: Left | Right):
            print(item.value)

        def main():
            read(Left())
        """,
        diagnostic_text(
            "union_field.py",
            15,
            "print(item.value)",
            "      ^^^^^^^^^^",
            "pyjs.CompilationError: Attribute 'value' is not defined on every "
            "member of Left | Right [PYJS1003]",
            "help: Missing from Right. Narrow the value with isinstance() before "
            "accessing 'value'.",
        ),
        filename="union_field.py",
    )


def test_union_method_access_rejects_incompatible_inline_lowering():
    ad(
        """\
        from pyjs import js

        @js
        class Left:
            @js.inline("{self}.renderLeft()")
            def render(self) -> str:
                return "left"

        @js
        class Right:
            @js.inline("{self}.renderRight()")
            def render(self) -> str:
                return "right"

        @js
        def render(item: Left | Right) -> str:
            return item.render()

        def main():
            render(Left())
        """,
        diagnostic_text(
            "union_method.py",
            17,
            "return item.render()",
            "       ^^^^^^^^^^^",
            "pyjs.CompilationError: Method 'render' has incompatible client lowering "
            "on Left | Right [PYJS2001]",
            "help: Narrow the receiver with isinstance() before calling the "
            "definition on Right.",
        ),
        filename="union_method.py",
    )


def test_union_field_assignment_must_be_valid_for_every_member():
    ad(
        """\
        from pyjs import js

        @js
        class Left:
            def __init__(self):
                self.value = "left"

        @js
        class Right:
            def __init__(self):
                self.value = 3

        @js
        def update(item: Left | Right):
            item.value = "updated"

        def main():
            update(Left())
        """,
        diagnostic_text(
            "union_assignment.py",
            15,
            'item.value = "updated"',
            "^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign str to 'value' through Left | Right "
            "[PYJS1103]",
            "help: Right.value expects int. A union field assignment must be compatible "
            "with every possible receiver; narrow the receiver with isinstance() "
            "otherwise.",
        ),
        filename="union_assignment.py",
    )


def test_union_field_assignment_reports_a_missing_member():
    ad(
        """\
        from pyjs import js

        @js
        class Left:
            def __init__(self):
                self.value = "left"

        @js
        class Right:
            def __init__(self):
                self.other = "right"

        @js
        def update(item: Left | Right):
            item.value = "updated"

        def main():
            update(Left())
        """,
        diagnostic_text(
            "union_missing_field.py",
            15,
            'item.value = "updated"',
            "^^^^^^^^^^",
            "pyjs.CompilationError: Attribute 'value' is not defined on every "
            "member of Left | Right [PYJS1003]",
            "help: Missing from Right. Narrow the value with isinstance() before "
            "accessing 'value'.",
        ),
        filename="union_missing_field.py",
    )


def test_union_method_assignment_explains_that_narrowing_is_required():
    ad(
        """\
        from pyjs import js

        @js
        class Left:
            @js.inline("{self}.renderLeft()")
            def render(self) -> str:
                return "left"

        @js
        class Right:
            @js.inline("{self}.renderRight()")
            def render(self) -> str:
                return "right"

        @js
        def replace(item: Left | Right):
            item.render = "updated"

        def main():
            replace(Left())
        """,
        diagnostic_text(
            "union_method_assignment.py",
            17,
            'item.render = "updated"',
            "^^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign to method 'render' through "
            "Left | Right [PYJS1103]",
            "help: Narrow the receiver before replacing a method.",
        ),
        filename="union_method_assignment.py",
    )


def test_union_optional_field_rejects_none_when_one_member_requires_a_value():
    ad(
        """\
        from pyjs import js

        @js
        class OptionalValue:
            def __init__(self):
                self.value: int | None = None

        @js
        class RequiredValue:
            def __init__(self):
                self.value = 1

        @js
        def clear(item: OptionalValue | RequiredValue):
            item.value = None

        def main():
            clear(OptionalValue())
        """,
        diagnostic_text(
            "union_optional_assignment.py",
            15,
            "item.value = None",
            "^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign NoneType to 'value' through "
            "OptionalValue | RequiredValue [PYJS1103]",
            "help: RequiredValue.value expects int. A union field assignment must be "
            "compatible with every possible receiver; narrow the receiver with "
            "isinstance() otherwise.",
        ),
        filename="union_optional_assignment.py",
    )


def test_union_field_assignment_checks_every_possible_value_type():
    ad(
        """\
        from pyjs import js

        @js
        class TextValue:
            def __init__(self):
                self.value = "text"

        @js
        class CountValue:
            def __init__(self):
                self.value = 1

        @js
        def copy(
            target: TextValue | CountValue,
            source: TextValue | CountValue,
        ):
            target.value = source.value

        def main():
            copy(TextValue(), CountValue())
        """,
        diagnostic_text(
            "union_value_assignment.py",
            18,
            "target.value = source.value",
            "^^^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign str|int to 'value' through "
            "TextValue | CountValue [PYJS1103]",
            "help: TextValue.value expects str, CountValue.value expects int. A union "
            "field assignment must be compatible with every possible receiver; "
            "narrow the receiver with isinstance() otherwise.",
        ),
        filename="union_value_assignment.py",
    )


def test_optional_attribute_narrowing_still_rejects_unrelated_assignments():
    ad(
        """\
        from pyjs import js

        @js
        class Timer:
            def __init__(self):
                self.handle: int | None = None

            def clear(self):
                if self.handle is not None:
                    self.handle = "wrong"

        def main():
            Timer().clear()
        """,
        diagnostic_text(
            "optional_attribute.py",
            10,
            'self.handle = "wrong"',
            "^^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign str to 'handle' of type int|NoneType "
            "[PYJS1103]",
            "help: Assign a value compatible with int|NoneType or change the annotation "
            "for 'handle'.",
        ),
        filename="optional_attribute.py",
    )


def test_annotated_initializer_rejects_an_incompatible_value():
    ad(
        """\
        def main():
            value: str = 123
        """,
        diagnostic_text(
            "initializer.py",
            2,
            "value: str = 123",
            "             ^^^",
            "pyjs.CompilationError: Cannot assign int to a value of type str "
            "[PYJS1103]",
            "help: Assign a value compatible with str.",
        ),
        filename="initializer.py",
    )


@pytest.mark.parametrize(
    (
        "source",
        "line",
        "source_line",
        "underline",
        "actual",
        "expected",
    ),
    (
        (
            """\
            def main():
                source = 123
                value: str = source
            """,
            3,
            "value: str = source",
            " " * 13 + "^" * 6,
            "int",
            "str",
        ),
        (
            """\
            from pyjs import js

            @js
            class Source:
                def __init__(self):
                    self.value = 123

            def main():
                source = Source()
                value: str = source.value
            """,
            10,
            "value: str = source.value",
            " " * 13 + "^" * 12,
            "int",
            "str",
        ),
        (
            """\
            from pyjs import js

            @js
            def load() -> int:
                return 123

            def main():
                value: str = load()
            """,
            8,
            "value: str = load()",
            " " * 13 + "^" * 6,
            "int",
            "str",
        ),
        (
            """\
            from pyjs import js

            @js
            def load() -> list[int]:
                return [123]

            def main():
                values: list[str] = load()
            """,
            8,
            "values: list[str] = load()",
            " " * 20 + "^" * 6,
            "list[int]",
            "list[str]",
        ),
    ),
)
def test_annotated_initializers_validate_resolved_expression_types(
    source,
    line,
    source_line,
    underline,
    actual,
    expected,
):
    ad(
        source,
        diagnostic_text(
            "resolved_initializer.py",
            line,
            source_line,
            underline,
            f"pyjs.CompilationError: Cannot assign {actual} to a value of "
            f"type {expected} [PYJS1103]",
            f"help: Assign a value compatible with {expected}.",
        ),
        filename="resolved_initializer.py",
    )


def test_cast_is_the_explicit_annotated_initializer_boundary():
    assert_module_transpile(
        """\
        from typing import cast

        def main():
            raw: object = "ready"
            value: str = cast(str, raw)
            print(value.upper())
        """,
        """
        export function main() {
            var raw = 'ready';
            var value = raw;
            console.log(value.toUpperCase());
        }
        """,
        filename="cast_initializer.py",
    )


def test_isinstance_does_not_over_narrow_a_broad_union_member():
    ad(
        """\
        from pyjs import js

        @js
        def narrow(value: object | list[int]):
            if isinstance(value, list):
                precise: list[int] = value
        """,
        diagnostic_text(
            "broad_narrowing.py",
            6,
            "precise: list[int] = value",
            " " * 21 + "^" * 5,
            "pyjs.CompilationError: Cannot assign list[object] to a value of "
            "type list[int] [PYJS1103]",
            "help: Assign a value compatible with list[int].",
        ),
        filename="broad_narrowing.py",
    )


def test_annotated_initializer_accepts_subclasses_and_optional_values():
    assert_module_transpile(
        """\
        from pyjs import js

        @js
        class Base:
            pass

        @js
        class Child(Base):
            pass

        def main():
            value: Base | None = Child()
            value = None
        """,
        """
        export class Base {
        }

        export class Child extends Base {
        }

        export function main() {
            var value = new Child();
            value = null;
        }
        """,
        filename="compatible_initializer.py",
    )


def test_function_call_rejects_an_incompatible_positional_argument():
    ad(
        """\
        from pyjs import js

        @js
        def render(count: int) -> None:
            pass

        def main():
            render("three")
        """,
        diagnostic_text(
            "call_argument.py",
            8,
            'render("three")',
            "       ^^^^^^^",
            "pyjs.CompilationError: Argument 'count' to render expects int, got str "
            "[PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="call_argument.py",
    )


def test_method_call_rejects_an_incompatible_generic_item():
    ad(
        """\
        def main():
            values: list[int] = []
            values.append("wrong")
        """,
        diagnostic_text(
            "method_argument.py",
            3,
            'values.append("wrong")',
            "              ^^^^^^^",
            "pyjs.CompilationError: Argument 'item' to list.append expects int, "
            "got str [PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="method_argument.py",
    )


def test_function_call_rejects_an_incompatible_keyword_argument():
    ad(
        """\
        from pyjs import js

        @js
        def render(*, count: int) -> None:
            pass

        def main():
            render(count="three")
        """,
        diagnostic_text(
            "keyword_argument.py",
            8,
            'render(count="three")',
            "             ^^^^^^^",
            "pyjs.CompilationError: Argument 'count' to render expects int, got str "
            "[PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="keyword_argument.py",
    )


def test_function_call_rejects_an_incompatible_vararg():
    ad(
        """\
        from pyjs import js

        @js
        def total(*values: int) -> int:
            return 0

        def main():
            total(1, "two")
        """,
        diagnostic_text(
            "vararg.py",
            8,
            'total(1, "two")',
            "         ^^^^^",
            "pyjs.CompilationError: Argument 'values' to total expects int, got str "
            "[PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="vararg.py",
    )


def test_function_call_rejects_an_incompatible_keyword_vararg():
    ad(
        """\
        from pyjs import js

        @js
        def configure(**values: int) -> None:
            pass

        def main():
            configure(retries="three")
        """,
        diagnostic_text(
            "keyword_vararg.py",
            8,
            'configure(retries="three")',
            "                  ^^^^^^^",
            "pyjs.CompilationError: Argument 'values' to configure expects int, "
            "got str [PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="keyword_vararg.py",
    )


def test_structural_callback_rejects_an_object_without_the_required_method():
    ad(
        """\
        from pyjs import js
        from pyjs.web.events import EventTarget

        @js
        class InvalidListener:
            pass

        def main(target: EventTarget):
            target.addEventListener("click", InvalidListener())
        """,
        diagnostic_text(
            "listener.py",
            9,
            'target.addEventListener("click", InvalidListener())',
            "                                 ^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Argument 'callback' to "
            "EventTarget.addEventListener expects callable|EventListener|NoneType, "
            "got InvalidListener [PYJS1104]",
            "help: Pass a value compatible with "
            "callable|EventListener|NoneType.",
        ),
        filename="listener.py",
    )


def test_non_exception_handler_points_to_the_invalid_type():
    ad(
        """\
        def main():
            try:
                print("try")
            except str:
                print("invalid")
        """,
        diagnostic_text(
            "invalid_except.py",
            4,
            "except str:",
            "       ^^^",
            "pyjs.CompilationError: except handler requires an exception class "
            "[PYJS1104]",
            "help: Catch Exception or a subclass of Exception.",
        ),
        filename="invalid_except.py",
    )


def test_diagnostic_keeps_the_source_snapshot_that_was_compiled():
    try:
        analyze_source(
            "def main():\n    print(original_name)\n",
            filename="snapshot.py",
        )
    except CompilationError as error:
        try:
            linecache.cache["snapshot.py"] = (
                36,
                None,
                ["def main():\n", "    print(changed_name)\n"],
                "snapshot.py",
            )
            assert format_compilation_error(error) == (
                '  File "snapshot.py", line 2\n'
                "    print(original_name)\n"
                "          ^^^^^^^^^^^^^\n"
                "pyjs.CompilationError: Name 'original_name' is not defined "
                "[PYJS1001]\n"
            )
        finally:
            linecache.cache.pop("snapshot.py", None)
    else:
        raise AssertionError("Expected compilation to fail")


def test_inline_not_implemented_has_a_located_compilation_diagnostic():
    assert_compilation_diagnostic(
        """\
        from pyjs import js

        @js
        def lower(value: int) -> int: ...

        @lower.inline
        def lower(value, **kwargs):
            return NotImplemented

        def main():
            lower(1)
        """,
        diagnostic_text(
            "inline_not_implemented.py",
            11,
            "lower(1)",
            "^^^^^^^^",
            "pyjs.CompilationError: Inline implementation for 'lower' cannot "
            "lower this call [PYJS2001]",
            "help: Use supported argument types or provide a runtime "
            "implementation for this operation.",
        ),
        filename="inline_not_implemented.py",
    )


def test_inline_generator_must_return_source_text():
    assert_compilation_diagnostic(
        """\
        from pyjs import js

        @js
        def lower(value: int) -> int: ...

        @lower.inline
        def lower(value, **kwargs):
            return 42

        def main():
            lower(1)
        """,
        diagnostic_text(
            "invalid_inline_result.py",
            11,
            "lower(1)",
            "^^^^^^^^",
            "pyjs.CompilationError: Inline implementation for 'lower' returned "
            "int, not str [PYJS2002]",
            "help: Return JavaScript source text from the inline generator.",
        ),
        filename="invalid_inline_result.py",
    )


def test_async_constructor_has_a_located_compilation_diagnostic():
    assert_compilation_diagnostic(
        """\
        from pyjs import js

        @js
        class Resource:
            async def __init__(self):
                pass

        def main():
            Resource()
        """,
        diagnostic_text(
            "async_constructor.py",
            5,
            "async def __init__(self):",
            "^^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: constructors cannot be async [PYJS2001]",
            "help: Move asynchronous setup to a separate method.",
        ),
        filename="async_constructor.py",
    )


def test_unsupported_unary_operation_has_a_located_compilation_diagnostic():
    assert_compilation_diagnostic(
        """\
        def main():
            print(~"value")
        """,
        diagnostic_text(
            "unary_operation.py",
            2,
            'print(~"value")',
            "      ^^^^^^^^",
            "pyjs.CompilationError: Unary operator '~' is not supported for str "
            "[PYJS2001]",
            "help: Define __invert__(self) for this client-side type.",
        ),
        filename="unary_operation.py",
    )


def test_unsupported_comparisons_have_located_compilation_diagnostics():
    ad(
        """\
        def main():
            print("a" < 1)
        """,
        diagnostic_text(
            "ordering.py",
            2,
            'print("a" < 1)',
            " " * 6 + "^" * 7,
            "pyjs.CompilationError: Operator '<' is not supported for str "
            "and int [PYJS1104]",
            "help: Use operands with compatible types or define the "
            "corresponding __lt__() method.",
        ),
        filename="ordering.py",
    )
    ad(
        """\
        def main():
            print(1 in 2)
        """,
        diagnostic_text(
            "membership.py",
            2,
            "print(1 in 2)",
            " " * 6 + "^" * 6,
            "pyjs.CompilationError: Operator 'in' is not supported for int "
            "and int [PYJS1104]",
            "help: Use operands with compatible types or define the "
            "corresponding __contains__() method.",
        ),
        filename="membership.py",
    )


def test_runtime_tuple_isinstance_has_a_located_compilation_diagnostic():
    assert_compilation_diagnostic(
        """\
        def main(value: object):
            if isinstance(value, tuple):
                print(value)
        """,
        diagnostic_text(
            "tuple_isinstance.py",
            2,
            "if isinstance(value, tuple):",
            "                     ^^^^^",
            "pyjs.CompilationError: isinstance() does not support unsubscripted "
            "'tuple' [PYJS2001]",
            "help: Test against a concrete runtime class.",
        ),
        filename="tuple_isinstance.py",
    )


def test_tuple_isinstance_rejects_non_type_members():
    assert_compilation_diagnostic(
        """\
        def main(value: object):
            print(isinstance(value, (int, 42)))
        """,
        diagnostic_text(
            "tuple_isinstance_member.py",
            2,
            "print(isinstance(value, (int, 42)))",
            "                              ^^",
            "pyjs.CompilationError: Argument 'obj_type' to isinstance expects "
            "type[object], got int [PYJS1104]",
            "help: Pass a value compatible with type[object].",
        ),
        filename="tuple_isinstance_member.py",
    )


def test_qualified_type_annotations_have_a_located_compilation_diagnostic():
    assert_compilation_diagnostic(
        """\
        from pyjs import js
        from pyjs.web import dom

        @js
        def consume(elements: list[dom.Element]) -> None:
            pass

        def main():
            consume([])
        """,
        diagnostic_text(
            "qualified_annotation.py",
            5,
            "def consume(elements: list[dom.Element]) -> None:",
            "                           ^^^^^^^^^^^",
            "pyjs.CompilationError: Qualified type annotations are not "
            "supported [PYJS2001]",
            "help: Import 'Element' directly and use it as the annotation.",
        ),
        filename="qualified_annotation.py",
    )


def test_invalid_type_argument_syntax_has_located_compilation_diagnostics():
    ad(
        """\
        from pyjs import js

        @js
        def consume(value: list[1 + 2]) -> None:
            pass

        def main():
            consume([])
        """,
        diagnostic_text(
            "invalid_type_argument.py",
            4,
            "def consume(value: list[1 + 2]) -> None:",
            " " * 24 + "^" * 5,
            "pyjs.CompilationError: '1 + 2' is not a supported type "
            "annotation [PYJS2001]",
            "help: Use a class, union, or supported generic type annotation.",
        ),
        filename="invalid_type_argument.py",
    )
    ad(
        """\
        from pyjs import js

        @js
        def consume(value: int[str]) -> None:
            pass

        def main():
            consume(1)
        """,
        diagnostic_text(
            "non_generic_type.py",
            4,
            "def consume(value: int[str]) -> None:",
            " " * 19 + "^" * 3,
            "pyjs.CompilationError: Type 'int' does not accept type arguments "
            "[PYJS2001]",
            "help: Use 'int' without square brackets.",
        ),
        filename="non_generic_type.py",
    )
    ad(
        """\
        from pyjs import js

        @js
        def consume(value: list[int, str]) -> None:
            pass

        def main():
            consume([])
        """,
        diagnostic_text(
            "generic_arity.py",
            4,
            "def consume(value: list[int, str]) -> None:",
            " " * 24 + "^" * 8,
            "pyjs.CompilationError: list expects 1 type argument, got 2 "
            "[PYJS1104]",
            "help: Parameterize list with 1 type argument.",
        ),
        filename="generic_arity.py",
    )


def test_unsupported_statement_syntax_has_located_diagnostics():
    ad(
        """\
        def main():
            value = 1
            match value:
                case 1:
                    print("one")
        """,
        diagnostic_text(
            "match_statement.py",
            3,
            "match value:",
            "^" * 12,
            "pyjs.CompilationError: match statements are not supported "
            "[PYJS2001]",
            "help: Use typed if/elif branches instead.",
        ),
        filename="match_statement.py",
    )
    ad(
        """\
        def main():
            print(value := 1)
        """,
        diagnostic_text(
            "assignment_expression.py",
            2,
            "print(value := 1)",
            " " * 6 + "^" * 10,
            "pyjs.CompilationError: assignment expressions are not supported "
            "[PYJS2001]",
            "help: Assign the value in a separate statement before using it.",
        ),
        filename="assignment_expression.py",
    )


@pytest.mark.parametrize(
    (
        "source",
        "filename",
        "line",
        "source_line",
        "indicator",
        "message",
        "help_text",
    ),
    [
        (
            "def main():\n    import math\n",
            "local_import.py",
            2,
            "import math",
            "^" * 11,
            "function-local imports are not supported",
            "Move the import to module scope.",
        ),
        (
            "def main():\n    from math import pi\n",
            "local_import_from.py",
            2,
            "from math import pi",
            "^" * 19,
            "function-local imports are not supported",
            "Move the import to module scope.",
        ),
        (
            "def main():\n    class Local:\n        pass\n",
            "local_class.py",
            2,
            "class Local:",
            "^" * 12,
            "function-local class definitions are not supported",
            "Move the class to module scope and decorate it with @js.",
        ),
        (
            "def main():\n    global value\n",
            "global_declaration.py",
            2,
            "global value",
            "^" * 12,
            "global declarations are not supported",
            "Pass the value explicitly or store it on a client-side object.",
        ),
        (
            "async def main():\n    async for value in [1]:\n        pass\n",
            "async_for.py",
            2,
            "async for value in [1]:",
            "^" * 23,
            "async for statements are not supported",
            "Await values explicitly inside a supported loop.",
        ),
        (
            "async def main():\n    async with value:\n        pass\n",
            "async_with.py",
            2,
            "async with value:",
            "^" * 17,
            "async with statements are not supported",
            "Call and await the resource lifecycle explicitly.",
        ),
        (
            "def main():\n    try:\n        pass\n    except* ValueError:\n"
            "        pass\n",
            "exception_group.py",
            2,
            "try:",
            "^" * 4,
            "except* handlers are not supported",
            "Use ordinary try/except with supported exception types.",
        ),
        (
            "def main():\n    type Value = int\n",
            "type_statement.py",
            2,
            "type Value = int",
            "^" * 16,
            "type statements inside client functions are not supported",
            "Define the type alias at module scope.",
        ),
        (
            'def main():\n    print(t"value")\n',
            "template_string.py",
            2,
            'print(t"value")',
            " " * 6 + "^" * 8,
            "template string literals are not supported",
            "Use an f-string when interpolation is sufficient.",
        ),
    ],
)
def test_unsupported_scope_and_async_syntax_has_located_diagnostics(
    source,
    filename,
    line,
    source_line,
    indicator,
    message,
    help_text,
):
    ad(
        source,
        diagnostic_text(
            filename,
            line,
            source_line,
            indicator,
            f"pyjs.CompilationError: {message} [PYJS2001]",
            f"help: {help_text}",
        ),
        filename=filename,
    )


def test_nonlocal_declaration_has_a_located_diagnostic():
    ad(
        """\
        from pyjs import js

        @js
        def outer():
            value = 1

            def inner():
                nonlocal value

            inner()

        def main():
            outer()
        """,
        diagnostic_text(
            "nonlocal_declaration.py",
            8,
            "nonlocal value",
            "^" * 14,
            "pyjs.CompilationError: nonlocal declarations are not supported "
            "[PYJS2001]",
            "help: Pass the value explicitly or store it on a client-side "
            "object.",
        ),
        filename="nonlocal_declaration.py",
    )


def test_starred_non_iterable_has_a_located_compilation_diagnostic():
    assert_compilation_diagnostic(
        """\
        def main():
            values = [*1]
        """,
        diagnostic_text(
            "starred_non_iterable.py",
            2,
            "values = [*1]",
            "           ^",
            "pyjs.CompilationError: Type 'int' is not iterable [PYJS1104]",
            "help: Define a client-side __iter__(self) -> Iterator[T] method or "
            "iterate over a supported collection.",
        ),
        filename="starred_non_iterable.py",
    )


def test_dunder_builtin_rejects_an_unsupported_receiver():
    ad(
        """\
        def main():
            print(len(1))
        """,
        diagnostic_text(
            "dunder_receiver.py",
            2,
            "print(len(1))",
            "          ^",
            "pyjs.CompilationError: len() is not supported for int [PYJS1104]",
            "help: Pass a value that defines __len__().",
        ),
        filename="dunder_receiver.py",
    )


def test_dunder_builtin_validates_the_custom_return_type():
    ad(
        """\
        from pyjs import js

        @js
        class Bad:
            def __len__(self) -> str:
                return "bad"

        def main():
            print(len(Bad()))
        """,
        diagnostic_text(
            "dunder_return.py",
            9,
            "print(len(Bad()))",
            "          ^^^^^",
            "pyjs.CompilationError: Bad.__len__() returns str, expected int "
            "[PYJS1105]",
            "help: Change __len__() to return int.",
        ),
        filename="dunder_return.py",
    )
