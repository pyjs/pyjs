import difflib
import textwrap
from io import StringIO
from pathlib import Path

import pytest

from pyjs.analysis.diagnostics import CompilationError, format_compilation_error
from pyjs.javascript.source import analyze_source, compile_source
from pyjs.javascript.transpiler import Transpiler, bundle_import

WIDTH = 80
TESTS_DIR = Path(__file__).parents[2] / "tests" / "transpiler"


def diff_side_by_side(msg, first, second):
    out = StringIO()
    out.write(msg + "\n")
    differ = difflib.Differ()
    for line in differ.compare(first, second):
        padded_line = f"{line[2:]:<{WIDTH // 2}}"
        if line.startswith(" "):
            out.write(f"{padded_line} | {padded_line}\n")
        elif line.startswith("-"):
            out.write(f"\033[94m{padded_line}\033[0m |\n")
        elif line.startswith("+"):
            out.write(f"{'':<{WIDTH // 2}} | \033[93m{padded_line}\033[0m\n")
        elif line.startswith("?"):
            pass
    return out.getvalue()


def _analyze(line):
    source = f"from pyjs import js\n{textwrap.dedent(line)}"
    return analyze_source(source)


def _analysis_types(analysis):
    type_info = analysis.types
    if not analysis.wrapped:
        return type_info
    return "\n".join(line.strip() for line in type_info.splitlines()[1:])


def _analysis_javascript(analysis):
    if not analysis.wrapped:
        return analysis.javascript
    lines = analysis.javascript.splitlines()
    wrapper = lines.index("export function main() {")
    lines = [*lines[:wrapper], *lines[wrapper + 1 : -1]]
    return "\n".join(line.strip() for line in lines)


def analyze_line(line):
    with _analyze(line) as analysis:
        return _analysis_types(analysis)


def transpile_line(line):
    with _analyze(line) as analysis:
        return _analysis_javascript(analysis)


def analyze_file(module_name, write=False, no_assert=False):
    __tracebackhide__ = True
    source_file = TESTS_DIR / "cases" / f"{module_name}.py"
    with analyze_source(
        source_file.read_text(),
        filename=str(source_file),
        module_name=f"tests.cases.{module_name}",
    ) as analysis:
        actual = analysis.types.splitlines()

    if no_assert:
        print(f"Transpiled {module_name}.run:")
        print("-" * WIDTH)
        for line in actual:
            print(line)
        print("-" * WIDTH)
        pytest.fail("no_assert=True, just printing the output.")

    js_file = TESTS_DIR / "cases" / f"{module_name}.types"
    expected = []
    if js_file.exists():
        with js_file.open() as js_src:
            expected = js_src.read().splitlines()

    if expected != actual:
        if write:
            with js_file.open("w") as js_src:
                js_src.write("\n".join(actual) + "\n")
                return
        pytest.fail(diff_side_by_side("Type trees do not match:", expected, actual))

    if expected == actual and write:
        pytest.fail("Assertion is correct but remember to remove write=True argument.")


def transpile_file(module_name, write=False, no_assert=False):
    __tracebackhide__ = True
    source_file = TESTS_DIR / "cases" / f"{module_name}.py"
    with analyze_source(
        source_file.read_text(),
        filename=str(source_file),
        module_name=f"tests.cases.{module_name}",
    ) as analysis:
        actual = analysis.javascript.splitlines()

    if no_assert:
        print(f"Transpiled {module_name}.run:")
        print("-" * WIDTH)
        for line in actual:
            print(line)
        print("-" * WIDTH)
        pytest.fail("no_assert=True, just printing the output.")

    js_file = TESTS_DIR / "cases" / f"{module_name}.js"
    expected = []
    if js_file.exists():
        with js_file.open() as js_src:
            expected = js_src.read().splitlines()

    if expected != actual:
        if write:
            with js_file.open("w") as js_src:
                js_src.write("\n".join(actual) + "\n")
                return
        pytest.fail(diff_side_by_side("Type trees do not match:", expected, actual))

    if expected == actual and write:
        pytest.fail("Assertion is correct but remember to remove write=True argument.")


def assert_analysis(py, expected):
    """assert analysis of expression"""
    __tracebackhide__ = True
    actual = analyze_line(py)
    assert textwrap.dedent(expected).strip() == actual


def assert_analysis_round_trip(py, expected_py):
    """assert analysis and round trip analysis"""
    __tracebackhide__ = True
    assert_analysis(py, expected_py)
    assert_analysis(expected_py, expected_py)


def assert_transpile(py, expected):
    """assert transpilation of expression"""
    __tracebackhide__ = True
    actual = transpile_line(py)
    assert textwrap.dedent(expected).strip() == actual


def assert_analysis_transpile(py, expected_py, expected_js):
    """assert analysis and transpile"""
    __tracebackhide__ = True
    with _analyze(py) as analysis:
        actual_py = _analysis_types(analysis)
        actual_js = _analysis_javascript(analysis)
    assert textwrap.dedent(expected_py).strip() == actual_py
    assert textwrap.dedent(expected_js).strip() == actual_js


def assert_analysis2x_transpile(py, expected_py, expected_js):
    """assert analysis, round trip analysis and transpile"""
    __tracebackhide__ = True
    assert_analysis_transpile(py, expected_py, expected_js)
    assert_analysis(expected_py, expected_py)


def analyze_module_source(py, **kwargs):
    return analyze_source(textwrap.dedent(py), **kwargs)


def assert_module_transpile(py, expected_js, **kwargs):
    __tracebackhide__ = True
    with analyze_module_source(py, **kwargs) as analysis:
        actual = analysis.javascript
    assert textwrap.dedent(expected_js).strip() == actual


def assert_module_analysis_transpile(py, expected_py, expected_js, **kwargs):
    __tracebackhide__ = True
    with analyze_module_source(py, **kwargs) as analysis:
        assert textwrap.dedent(expected_py).strip() == analysis.types
        assert textwrap.dedent(expected_js).strip() == analysis.javascript


def assert_bundle_module_transpile(py, expected_js, **kwargs):
    __tracebackhide__ = True
    with analyze_module_source(py, **kwargs) as analysis:
        actual = Transpiler(
            analysis.entry_point,
            bundle_import,
            lambda name: f"__export_js__.{name} = {name};",
        ).visit(analysis.entry_point.container.node)
    assert textwrap.dedent(expected_js).strip() == actual


def assert_compiled_sources(py, expected_sources, **kwargs):
    __tracebackhide__ = True
    with compile_source(textwrap.dedent(py), **kwargs) as compilation:
        actual = compilation.sources
    expected = {
        name: textwrap.dedent(source).strip()
        for name, source in expected_sources.items()
    }
    assert expected == actual


def assert_diagnostic(py, expected, **kwargs):
    __tracebackhide__ = True
    with pytest.raises(CompilationError) as caught:
        analyze_module_source(py, **kwargs)
    actual = format_compilation_error(caught.value)
    expected = textwrap.dedent(expected).strip("\n") + "\n"
    assert expected == actual
    return caught.value.diagnostic


def assert_compilation_diagnostic(py, expected, **kwargs):
    __tracebackhide__ = True
    with pytest.raises(CompilationError) as caught:
        compile_source(textwrap.dedent(py), **kwargs)
    actual = format_compilation_error(caught.value)
    expected = textwrap.dedent(expected).strip("\n") + "\n"
    assert expected == actual
    return caught.value.diagnostic


def diagnostic_text(
    filename: str,
    line: int,
    source: str,
    underline: str,
    error: str,
    *details: str,
) -> str:
    lines = [
        f'  File "{filename}", line {line}',
        f"    {source}",
        f"    {underline}",
        error,
        *details,
    ]
    return "\n".join(lines) + "\n"


a = assert_analysis
aa = assert_analysis_round_trip
at = assert_analysis_transpile
aat = assert_analysis2x_transpile
ad = assert_diagnostic
