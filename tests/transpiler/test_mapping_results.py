import pytest

from pyjs import float32, int8
from pyjs.analysis.representation import annotation_representation
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["javascript", "native", "java", "webassembly"])
@pytest.mark.parametrize("operation", ["get", "setdefault", "pop"])
def test_mapping_result_infers_complete_nested_representation(environment, operation):
    options = {"environment": environment} if environment is not None else {}
    with analyze_source(f'''
        from pyjs import js, int8, float32
        @js
        def main(values: dict[str, tuple[int8, list[float32]]], fallback: tuple[int8, list[float32]]):
            return values.{operation}("key", fallback)
    ''', wrap=False, **options) as analysis:
        assert analysis.entry_point.return_representation == annotation_representation(tuple[int8, list[float32]])
