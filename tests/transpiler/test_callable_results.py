"""A bound union method carries every result arm into its callable value."""

import pytest

from pyjs import int8
from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.objects import UnionType
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import UNION_METHOD_RESULT_TYPES


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("direct", [False, True], ids=["extracted", "direct"])
def test_union_method_retains_result_metadata(environment, reverse, direct):
    options = {"environment": environment} if environment is not None else {}
    members = "TextResult | NumericResult" if reverse else "NumericResult | TextResult"
    source = UNION_METHOD_RESULT_TYPES
    source += f'''
@js
def main(source: {members}):
    callback = source.value
    return {"source.value()" if direct else "callback"}
'''
    with analyze_source(source, wrap=False, **options) as analysis:
        result_type = analysis.entry_point.return_type
        if not direct:
            result_type = result_type.return_type
        assert isinstance(result_type, UnionType)
        assert {member.name for member in result_type.types} == {"int", "str"}
        expected = annotation_representation(str | int8 if reverse else int8 | str)
        if direct:
            assert analysis.entry_point.return_representation == expected
        else:
            assert analysis.entry_point.return_type.return_representation == expected
            assert analysis.entry_point.return_representation.result == expected


@pytest.mark.parametrize("expression", ["source.value", "source.value()"])
@pytest.mark.parametrize("other", ["int", "int16"])
def test_union_method_rejects_conflicting_numeric_result_layouts(expression, other):
    with pytest.raises(CompilationError, match="Method 'value' results"):
        analyze_source(f'''
from pyjs import js, int8, int16
@js
class Narrow:
    def value(self) -> int8:
        return int8(1)
@js
class Wide:
    def value(self) -> {other}:
        return {other}(1)
@js
def main(source: Narrow | Wide):
    return {expression}
''', wrap=False)
