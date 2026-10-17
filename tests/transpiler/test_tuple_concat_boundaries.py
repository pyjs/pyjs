import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from pyjs.webassembly import transpile_webassembly


@pytest.mark.parametrize("compile", [transpile_jvm, transpile_webassembly], ids=["jvm", "wasm"])
@pytest.mark.parametrize("expression", ["left + right", "left.__add__(right)"])
@pytest.mark.parametrize("annotation", ["tuple[int, ...]", "tuple[int]"])
def test_shared_tuple_declaration_reports_backend_capability(compile, expression, annotation):
    source = f'''def combine(left: {annotation}, right: {annotation}) -> tuple[int, ...]:
    return {expression}
def main() -> int:
    return len(combine((1,), (2,)))
'''
    with pytest.raises(CompilationError, match="tuple concatenation is not implemented by this backend") as caught:
        compile(source)
    assert caught.value.lineno == 2
