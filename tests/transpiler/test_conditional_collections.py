import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java.analysis import JVM_ENVIRONMENT
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.testing.helpers import assert_module_analysis_transpile
from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

SOURCE = '''
def main(flag: bool, values: list[int]) -> list[int]:
    result = values if flag else []
    return result
'''


@pytest.mark.parametrize("environment,name", [
    (JVM_ENVIRONMENT, "conditional"),
    (NATIVE_ENVIRONMENT, "conditional_done_value"),
    (WEBASSEMBLY_ENVIRONMENT, "conditional"),
])
def test_fresh_empty_branch_is_concrete_before_ir_allocation(environment, name):
    with analyze_source(SOURCE, wrap=False, environment=environment) as result:
        assert result.types == (
            "def main(flag: bool, values: list__int) -> list[int]:\n"
            "    block entry:\n"
            "        branch flag:\n"
            "            true -> conditional_true\n"
            "            false -> conditional_false\n"
            "    block conditional_true:\n"
            "        jump conditional_done(values)\n"
            "    block conditional_false:\n"
            "        jump conditional_done(new[caller] list[int]())\n"
            f"    block conditional_done({name}: list[int]):\n"
            f"        result: list[int] = {name}\n"
            "        return result"
        )


def test_javascript_retains_the_same_semantic_result_type():
    assert_module_analysis_transpile(SOURCE,
            "def main(flag: bool, values: list__int) -> list[int]:\n"
            "    result: list[int] = values if flag else []\n"
            "    return result",
            "export function main(flag, values) {\n"
            "    var result = flag ? values : [];\n"
            "    return result;\n"
            "}", wrap=False)


@pytest.mark.parametrize("environment", [JVM_ENVIRONMENT, NATIVE_ENVIRONMENT, WEBASSEMBLY_ENVIRONMENT])
def test_nested_empty_shapes_must_match_the_sibling(environment):
    source = (
        "def main(flag: bool, values: list[list[int]]) -> list[list[int]]:\n"
        "    return [{}] if flag else values\n"
    )
    with pytest.raises(CompilationError) as caught:
        with analyze_source(source, wrap=False, environment=environment):
            pass
    assert str(caught.value) == (
        "Function returns list[object] | list[list[int]], not list[list[int]] "
        "[PYJS1105] (_pyjs_source_.py, line 1)"
    )
