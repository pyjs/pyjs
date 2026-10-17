import ast

from pyjs import js
from pyjs.analysis.objects import CompilationExtension
from pyjs.javascript.source import analyze_source


@js
def extension_helper(value: int) -> int:
    return value


class RewriteReturn(ast.NodeTransformer):
    def visit_Return(self, node: ast.Return):
        replacement = ast.Return(
            value=ast.Call(
                func=ast.Name(id="__extension_helper", ctx=ast.Load()),
                args=[node.value],
                keywords=[],
            )
        )
        return ast.copy_location(replacement, node)


def test_compilation_extension_rewrites_functions_and_injects_imports():
    transformed = []

    class Extension(CompilationExtension):
        def transform_function(self, function, node, source):
            if function.__name__ != "main":
                return node, {}
            transformed.append(source)
            return RewriteReturn().visit(node), {"__extension_helper": extension_helper}

    source = analyze_source("return 1", wrap=True, extensions=(Extension(),)).javascript

    assert transformed
    assert "import { extension_helper as __extension_helper }" in source
    assert "return __extension_helper(1);" in source


def test_compilation_extension_can_return_the_original_function():
    source = analyze_source(
        "assert True", wrap=True, extensions=(CompilationExtension(),)
    ).javascript

    assert "__pyjsAssert__(true, undefined, $AssertionError);" in source
