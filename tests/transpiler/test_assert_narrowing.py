import ast

import pytest

from pyjs.analysis.analyzer import JS_ENVIRONMENT
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import at
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import ASSERT_NARROWING_CONTRACT


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_assertions_remain_in_the_analyzed_body_after_narrowing(environment):
    with analyze_source(ASSERT_NARROWING_CONTRACT.source, wrap=False, environment=environment) as analysis:
        for name in ("present", "negated", "truthy", "both", "checked", "narrow"):
            function = analysis.entry_point.container.search(name)
            assert isinstance(function.body[0], ast.Assert)
            assert isinstance(function.body[-1], ast.Return)
            assert function.return_type.name == "int"


def test_assert_narrowing_preserves_complete_javascript_runtime_checks():
    at('''
        def main(value: int | str | None) -> int:
            assert value is not None, "required"
            assert isinstance(value, int), "integer"
            return value + 1
    ''', '''
        def main(value: int | str | None) -> int:
            assert value.[object]__is_not__!(None), 'required'
            assert isinstance(value, int), 'integer'
            return value.[int]__add__!(1)
    ''', '''
        import { AssertionError as $AssertionError } from './pyjs.python.js';

        export function main(value) {
            if (!(value != null)) {
                throw new $AssertionError(String('required'));
            }
            if (!(((value)=>typeof value==='boolean'||Number.isInteger(value))(value))) {
                throw new $AssertionError(String('integer'));
            }
            return value + 1;
        }
    ''')


def test_assertion_truth_conversion_remains_in_the_typed_tree():
    at('''
        def main(values: list[int], detail: str):
            assert values, detail
    ''', '''
        def main(values: list__int, detail: str) -> None:
            assert values.[list__int]__bool__!(), detail
    ''', '''
        import { AssertionError as $AssertionError } from './pyjs.python.js';

        export function main(values, detail) {
            if (!(values.length)) {
                throw new $AssertionError(String(detail));
            }
        }
    ''')


def test_assertion_short_circuit_keeps_truth_at_each_operand():
    at('''
        def main(left: list[int], right: list[int]):
            assert left or right
    ''', '''
        def main(left: list__int, right: list__int) -> None:
            assert left.[list__int]__bool__!() or right.[list__int]__bool__!()
    ''', '''
        import { AssertionError as $AssertionError } from './pyjs.python.js';

        export function main(left, right) {
            if (!(left.length || right.length)) {
                throw new $AssertionError("");
            }
        }
    ''')


def test_empty_literal_truth_is_false_without_container_type_arguments():
    at('''
        def main():
            assert []
            if {}:
                return 1
            return 0
    ''', '''
        def main() -> int:
            assert False
            if False:
                return 1
            return 0
    ''', '''
        import { AssertionError as $AssertionError } from './pyjs.python.js';

        export function main() {
            if (!(false)) {
                throw new $AssertionError("");
            }
            if (false) {
                return 1;
            }
            return 0;
        }
    ''')


@pytest.mark.parametrize("environment", [JS_ENVIRONMENT, NATIVE_ENVIRONMENT])
@pytest.mark.parametrize("body", [
    "assert value is not None or allowed",
    "assert value is not None\n    value = None",
    "try:\n        assert value is not None\n    except AssertionError:\n        pass",
    "for item in [1]:\n        assert value is not None",
])
def test_assert_proofs_do_not_escape_unproved_or_invalidated_paths(environment, body):
    with pytest.raises(CompilationError, match="upper"):
        analyze_source(f'''
from pyjs import js
@js
def read(value: str | None, allowed: bool) -> str:
    {body}
    return value.upper()
def main() -> str:
    return read(None, True)
''', wrap=False, environment=environment)
