"""Implicit object calls must not bind an instance field as a class method."""

import pytest

from pyjs.analysis.diagnostics import CompilationError, format_compilation_error
from pyjs.java import transpile_jvm
from pyjs.native.llvm import transpile_llvm
from pyjs.testing.helpers import (
    analyze_module_source,
    assert_module_transpile,
    diagnostic_text,
)
from pyjs.webassembly import transpile_webassembly


def callable_field_source(*, field_type="int", method=True, inherited=False, explicit=False):
    declaration = "    def __call__(self, value: int) -> str: return 'method:' + str(value)\n" if method else ""
    subclass = "@js\nclass Child(Value):\n    pass\n" if inherited else ""
    receiver = "Child" if inherited else "Value"
    argument = '"four"' if field_type == "str" else "4"
    call = f"value.__call__({argument})" if explicit else "value(3)"
    return f'''from collections.abc import Callable
from pyjs import js
@js
def replacement(value: {field_type}) -> str: return "field:" + str(value)
@js
class Value:
    def __init__(self):
        self.__call__: Callable[[{field_type}], str] = replacement
{declaration}{subclass}@js
def main() -> str:
    value = {receiver}()
    return {call}
'''


@pytest.mark.parametrize("backend", ["javascript", "llvm", "jvm", "webassembly"])
@pytest.mark.parametrize("field_type,method,inherited", [
    ("int", True, False), ("str", True, False),
    ("int", True, True), ("int", False, False),
])
def test_implicit_callable_fields_have_a_located_boundary(backend, field_type, method, inherited):
    source = callable_field_source(field_type=field_type, method=method, inherited=inherited)
    with pytest.raises(CompilationError) as caught:
        if backend == "javascript":
            analyze_module_source(source, filename="shadow.py", wrap=False)
        else:
            {"llvm": transpile_llvm, "jvm": transpile_jvm,
             "webassembly": transpile_webassembly}[backend](source, filename="shadow.py")
    assert format_compilation_error(caught.value) == diagnostic_text(
        "shadow.py", len(source.splitlines()), "return value(3)", "       ^^^^^",
        "pyjs.CompilationError: Implicit calls through non-method __call__ attributes "
        "are not supported [PYJS2001]",
        "help: Call a callable instance field explicitly with value.__call__(...).",
    )


def test_explicit_callable_field_keeps_its_own_signature_and_javascript():
    from tests.semantics.helpers import assert_semantics

    source = callable_field_source(field_type="str", explicit=True)
    assert_module_transpile(source, '''
        export function replacement(value) {
            return 'field:' + value;
        }

        export class Value {

            constructor() {
                this.__call__ = replacement;
            }
        }

        export function main() {
            var value = new Value();
            return value.__call__('four');
        }
    ''', wrap=False)
    assert_semantics(source.replace("def main() -> str:", "def evaluate() -> str:") + '''
@js
def main() -> None:
    print(evaluate())
main()
''')
