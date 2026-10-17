import ast

import pytest

from pyjs.analysis.objects import _literal_state, _literal_value


@pytest.mark.parametrize("expression, expected", [
    ("frozenset()", frozenset()),
    ("frozenset({1, -2, 1})", frozenset({1, -2})),
    ('{"x": (frozenset(["a", "b"]), [1, -0.0])}', {"x": (frozenset({"a", "b"}), [1, -0.0])}),
    ("[set(), frozenset({False, 2})]", [set(), frozenset({False, 2})]),
])
def test_effect_free_literal_evaluation_preserves_structure(expression, expected):
    actual = _literal_value(ast.parse(expression, mode="eval").body, {})
    assert _literal_state(actual) == _literal_state(expected)


@pytest.mark.parametrize("expression", [
    "frozenset(range(3))", "frozenset({len('x')})", "set([1])",
    "frozenset({1}, {2})", "frozenset(items={1})", "frozenset(*[{1}])",
    "{**{'x': 1}}", "[x for x in [1]]",
])
def test_literal_evaluation_does_not_invoke_arbitrary_calls(expression):
    with pytest.raises((TypeError, ValueError)):
        _literal_value(ast.parse(expression, mode="eval").body, {})


def test_shadowed_literal_constructor_is_not_called():
    def frozenset(items):
        pytest.fail("literal validation must never invoke a user constructor")
    with pytest.raises(ValueError, match="nonliteral call"):
        _literal_value(ast.parse("frozenset({1})", mode="eval").body, {"frozenset": frozenset})


def test_shared_discovery_does_not_enable_frozenset_module_state_on_other_backends():
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.java import JVMUnsupported, transpile_jvm
    from pyjs.javascript.source import compile_source
    from pyjs.webassembly import transpile_webassembly

    # The outer list is already target-selected by JVM; nested frozen values
    # must reach its explicit storage boundary rather than crash reachability.
    source = "values: list[frozenset[int]] = [frozenset({1})]\ndef main() -> int:\n    return len(values)\n"
    with pytest.raises(JVMUnsupported, match="module collection state is not implemented"):
        transpile_jvm(source)
    with pytest.raises(CompilationError, match="not a client value"):
        transpile_webassembly(source)
    with pytest.raises(CompilationError, match="not a client value"):
        compile_source("from pyjs import js\n" + source.replace("def main", "@js\ndef main"))
