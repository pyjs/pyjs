import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.objects import Function
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.comparison_fixtures import COMPARISON_PAIRS, declining_pair


@pytest.mark.parametrize("operator, forward, reflected", COMPARISON_PAIRS)
def test_native_dynamic_negotiation_retains_only_required_application_methods(operator, forward, reflected):
    with analyze_source(declining_pair(operator, forward, reflected), wrap=False,
                        environment=NATIVE_ENVIRONMENT) as analysis:
        reached = {(function.cls.name, function.name) for function in analysis.entry_point.compilation_objects
                   if isinstance(function, Function) and function.cls is not None
                   and function.cls.name in {"Left", "Right"}}
        assert reached == {("Left", forward), ("Right", reflected)}


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["llvm", "jvm", "wasm"])
@pytest.mark.parametrize("alias", ["NotImplementedType", "Declined"])
def test_singleton_annotation_resolves_to_the_backend_model(environment, alias):
    with analyze_source(f'''
from types import NotImplementedType as {alias}
def main(value: {alias}) -> {alias}:
    return value
''', wrap=False, environment=environment) as analysis:
        function = analysis.entry_point
        expected = environment.builtins.search("NotImplementedType")
        assert function.return_type is expected
        assert function.params[0].annotation.obj is expected


@pytest.mark.parametrize("transpile, error, message", [
    (transpile_jvm, JVMUnsupported, "unsupported JVM value type NotImplementedType"),
    (transpile_webassembly, WebAssemblyUnsupported, "WebAssembly value type NotImplementedType is not implemented"),
])
def test_singleton_annotation_does_not_imply_other_backend_runtime_support(transpile, error, message):
    with pytest.raises(error, match=message):
        transpile('''
from types import NotImplementedType
def main(value: NotImplementedType) -> NotImplementedType:
    return value
''')


@pytest.mark.parametrize("transpile", [transpile_jvm, transpile_webassembly])
def test_other_backends_keep_a_located_singleton_name_boundary(transpile):
    with pytest.raises(CompilationError, match="Name 'NotImplemented' is not defined") as caught:
        transpile("def main() -> int:\n    return int(NotImplemented is None)")
    assert caught.value.lineno == 2
