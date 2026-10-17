import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.testing.helpers import analyze_module_source, assert_module_transpile
from pyjs.webassembly import transpile_webassembly


def test_application_type_namesake_is_not_runtime_introspection():
    assert_module_transpile('''
        from pyjs import js
        @js
        class type: pass
        @js
        def main() -> bool:
            return type() is type()
    ''', '''
        export class type {
        }

        export function main() {
            return new type() === new type();
        }
    ''')


@pytest.mark.parametrize("transpile", [transpile_jvm, transpile_webassembly])
def test_shared_native_issubclass_has_a_located_unsupported_backend_boundary(transpile):
    with pytest.raises(CompilationError, match="issubclass is not implemented by this backend") as caught:
        transpile("def main() -> int:\n    return int(issubclass(int, int))\n", filename="type_query.py")
    assert "type_query.py" in str(caught.value)


def test_tuple_isinstance_literal_bindings_keep_complete_javascript_output():
    assert_module_transpile('''
        from pyjs import js
        @js
        def main():
            print(isinstance(7, (str, int)))
            print(isinstance("yes", (int, str)))
            print(isinstance(1, ()))
    ''', '''
        export function main() {
            console.log(((($value) => (typeof $value === 'string') || ((value)=>typeof value==='boolean'||Number.isInteger(value))($value))(7) ? 'True' : 'False'));
            console.log(((($value) => ((value)=>typeof value==='boolean'||Number.isInteger(value))($value) || (typeof $value === 'string'))('yes') ? 'True' : 'False'));
            console.log(((($value) => false)(1) ? 'True' : 'False'));
        }
    ''')


def test_failed_structural_membership_does_not_prove_an_optional_value_is_none():
    with pytest.raises(CompilationError, match="Function returns NoneType \\| Shape, not NoneType") as caught:
        with analyze_module_source('''
            from pyjs import js
            @js
            class Shape:
                __pyjs_structural__ = True
                def area(self) -> int: return 0
            @js
            def main(value: Shape | None) -> None:
                if isinstance(value, Shape):
                    return None
                return value
        ''', filename="structural_flow.py"):
            pass
    assert "structural_flow.py" in str(caught.value)
