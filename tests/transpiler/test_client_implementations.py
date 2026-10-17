import ast
import sys

import pytest

from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT
from tests.backend_semantics import CLIENT_IMPLEMENTATIONS_SOURCE
from tests.semantics.helpers import run_javascript, run_python


@pytest.fixture
def client_module(tmp_path, monkeypatch):
    name = "client_selection_probe"
    (tmp_path / f"{name}.py").write_text(CLIENT_IMPLEMENTATIONS_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    previous = sys.modules.pop(name, None)
    yield
    sys.modules.pop(name, None)
    if previous is not None:
        sys.modules[name] = previous


@pytest.mark.parametrize("environment", [None, NATIVE_ENVIRONMENT, JVM_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT],
                         ids=["js", "native", "jvm", "wasm"])
@pytest.mark.parametrize("imported", [False, True])
def test_client_body_selection_follows_backend_through_imports(client_module, environment, imported):
    source = CLIENT_IMPLEMENTATIONS_SOURCE
    if imported:
        source = '''
            from pyjs import js
            import client_selection_probe as module
            from client_selection_probe import plain
            @js
            def main() -> int:
                return plain() + module.selected_partial() + module.Choice().read()
        '''
        if environment is None:
            source = source.replace("import client_selection_probe as module", "from client_selection_probe import selected_partial, Choice")
            source = source.replace("module.", "")
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        functions = {function.name: function for function in analysis.entry_point.compilation_objects
                     if hasattr(function, "original_node") and isinstance(function.original_node, ast.FunctionDef)}
        js = environment is None
        assert ast.unparse(functions["plain"].original_node.body[-1]) == f"return {29 if js else 17}"
        assert ast.unparse(functions["read"].original_node.body[-1]) == f"return {67 if js else 53}"
        assert ast.unparse(functions["selected_partial"].original_node.body[-1]) == (
            "return add_one(40)" if js else "return 37")


def test_client_implementations_keep_javascript_and_python_bodies_distinct():
    source = CLIENT_IMPLEMENTATIONS_SOURCE.replace("def main() -> int:", "def value() -> int:")
    source += "\n@js\ndef main() -> None:\n    print(value())\n"
    python = run_python(source + "\nmain()\n")
    javascript, _ = run_javascript(source)
    assert python.returncode == javascript.returncode == 0
    assert python.stdout == "107\n"
    assert javascript.stdout == "137\n"
    assert python.stderr == javascript.stderr == ""
