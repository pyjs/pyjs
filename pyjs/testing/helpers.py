import difflib
import textwrap
from importlib import import_module
from io import StringIO
from pathlib import Path

import pytest

from pyjs.transpiler import analyze_source
from pyjs.transpiler.analyzer import analyze_module
from pyjs.transpiler.transpiler import Transpiler
from pyjs.transpiler.utils import write_types

WIDTH = 80
TESTS_DIR = Path(__file__).parent


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


def analyze_line(line):
    analysis = _analyze(line)
    type_info = analysis.types
    if not analysis.wrapped:
        return type_info
    return "\n".join(line.strip() for line in type_info.splitlines()[1:])


def transpile_line(line):
    analysis = _analyze(line)
    if not analysis.wrapped:
        return analysis.javascript
    return "\n".join(line.strip() for line in analysis.javascript.splitlines()[1:-1])


def analyze_file(module_name, write=False, no_assert=False):
    __tracebackhide__ = True
    entry_point, _ = analyze_module(import_module(f"tests.transpiler.cases.{module_name}"))
    module = entry_point.container
    actual = write_types(module.node).splitlines()

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
    entry_point, _ = analyze_module(import_module(f"tests.transpiler.cases.{module_name}"))
    module = entry_point.container
    actual = Transpiler(module.scope.search("main")).visit(module.node).splitlines()

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
    assert_analysis(py, expected_py)
    assert_transpile(py, expected_js)


def assert_analysis2x_transpile(py, expected_py, expected_js):
    """assert analysis, round trip analysis and transpile"""
    __tracebackhide__ = True
    assert_analysis_round_trip(py, expected_py)
    assert_transpile(py, expected_js)


a = assert_analysis
aa = assert_analysis_round_trip
at = assert_analysis_transpile
aat = assert_analysis2x_transpile
