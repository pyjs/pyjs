import pytest

from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import analyze_module_source
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import EMPTY_LITERAL_SUM_CONTRACT
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("expression, expected, bits", [
    ("sum([])", "int", None),
    ("sum([], 5)", "int", None),
    ("sum((), start=True)", "bool", None),
    ("sum([], start=0.5)", "float", None),
    ("sum([], int8(120))", "int", 8),
    ("sum((), start=int64(1152921504606846976))", "int", 64),
    ("sum([], float32(1.25))", "float", 32),
])
def test_empty_literal_sum_preserves_start_type_and_representation(environment, expression, expected, bits):
    with analyze_module_source(f'''
        from pyjs import int8, int64, float32
        def main():
            return {expression}
    ''', environment=environment) as analysis:
        function = analysis.entry_point
        assert function.return_type.generic_name == expected
        representation = function.return_representation
        numeric = representation.numeric if representation is not None else None
        assert (numeric.bits if numeric is not None else None) == bits


def test_javascript_empty_literal_sum_matches_python():
    assert_semantics(EMPTY_LITERAL_SUM_CONTRACT.print_source + "\nmain()\n")
