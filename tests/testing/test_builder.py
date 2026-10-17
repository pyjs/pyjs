import gc
import importlib
import sys
import weakref

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.javascript.sourcemap import SourceMap, TranspiledJavaScript
from pyjs.testing import builder as builder_module
from pyjs.testing.builder import (
    BrowserBundle,
    BrowserBundleBuilder,
    SelectedTest,
    compute_testing_signature,
    generate_entrypoint_source,
)
from pyjs.tooling.npm import NpmImport, NpmPackage


def test_project_import_cleanup_handles_nested_namespace_packages(tmp_path, monkeypatch):
    package = tmp_path / "ci_namespace" / "nested"
    package.mkdir(parents=True)
    (package / "value.py").write_text("value = 42\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    names = ("ci_namespace", "ci_namespace.nested", "ci_namespace.nested.value")
    try:
        original = importlib.import_module(names[-1])
        builder_module.clear_project_modules(tmp_path, [])
        assert all(name not in sys.modules for name in names)
        assert importlib.import_module(names[-1]) is not original
    finally:
        for name in reversed(names):
            sys.modules.pop(name, None)


def test_generate_entrypoint_source_binds_each_selected_test_directly():
    source = generate_entrypoint_source(
        "run-1",
        [
            SelectedTest(
                "tests/first.py::test_same_name",
                "tests.first",
                "test_same_name",
            ),
            SelectedTest(
                "tests/second.py::test_same_name",
                "tests.second",
                "test_same_name",
            ),
        ],
    )

    assert "from tests.first import test_same_name as __pyjs_test_0" in source
    assert "from tests.second import test_same_name as __pyjs_test_1" in source
    assert "'tests.first',\n            'test_same_name',\n            __pyjs_test_0," in source
    assert "'tests.second',\n            'test_same_name',\n            __pyjs_test_1," in source
    assert source.count("initialize_test_runtime('run-1', selected_tests)") == 1


def test_selected_test_payload_round_trip():
    selected = SelectedTest(
        "tests/test_example.py::test_value",
        "tests.test_example",
        "test_value",
        ("androidx",),
    )

    assert SelectedTest.from_payload(selected.to_payload()) == selected


def test_builder_compiles_an_in_memory_entrypoint(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    (project_root / "browser_example.py").write_text(
        """from pyjs import js


@js
def test_value():
    assert 1 == 1
""",
        encoding="utf-8",
    )
    builder = BrowserBundleBuilder(project_root, cache_dir)

    result = builder.build(
        [SelectedTest("browser_example.py::test_value", "browser_example", "test_value")],
        "run-1",
    )

    assert "test_value: __pyjs_test_0" in result.javascript
    assert "initialize_test_runtime('run-1'" in result.javascript
    assert "sourceURL" not in result.javascript
    assert "sourceMappingURL" not in result.javascript
    source_map = result.source_map.to_dict()
    assert (project_root / "browser_example.py").as_posix() in source_map["sources"]
    assert result.css == ""
    assert not builder.entrypoint_path.exists()
    assert not (project_root / "js_main.py").exists()
    assert not (project_root / "js_main.main.js").exists()


def test_builder_preserves_reachable_npm_imports(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    (project_root / "browser_example.py").write_text(
        """from pyjs import js


@js
def test_value():
    assert 1 == 1
""",
        encoding="utf-8",
    )
    imports = (
        NpmImport(NpmPackage("example-package", "1.2.3"), "$example"),
    )
    monkeypatch.setattr(
        builder_module,
        "bundle_with_source_map",
        lambda *args, **kwargs: (
            TranspiledJavaScript("javascript", SourceMap(), imports),
            "stylesheet",
        ),
    )

    result = BrowserBundleBuilder(project_root, cache_dir).build(
        [
            SelectedTest(
                "browser_example.py::test_value",
                "browser_example",
                "test_value",
            )
        ],
        "run-1",
    )

    assert result == BrowserBundle(
        "javascript",
        "stylesheet",
        SourceMap().shifted(2),
        imports,
    )


def test_builder_reimports_changed_project_modules(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    dependency = project_root / "dependency.py"
    dependency.write_text(
        """from pyjs import js


@js
def current_value():
    return 1
""",
        encoding="utf-8",
    )
    (project_root / "browser_example.py").write_text(
        """from pyjs import js

from dependency import current_value


@js
def test_value():
    assert current_value() == 1
""",
        encoding="utf-8",
    )
    selected = SelectedTest("browser_example.py::test_value", "browser_example", "test_value")
    builder = BrowserBundleBuilder(project_root, cache_dir)

    first_source = builder.build([selected], "run-1").javascript
    dependency.write_text(
        """from pyjs import js


@js
def current_value():
    return 2
""",
        encoding="utf-8",
    )
    second_source = builder.build([selected], "run-2").javascript

    assert "return 1;" in first_source
    assert "return 2;" not in first_source
    assert "return 2;" in second_source
    assert "return 1;" not in second_source


def test_builder_releases_each_compiled_entrypoint(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    (project_root / "browser_example.py").write_text(
        """from pyjs import js


@js
def test_value():
    assert [1, 2, 3] == [1, 2, 3]
""",
        encoding="utf-8",
    )
    selected = SelectedTest(
        "browser_example.py::test_value",
        "browser_example",
        "test_value",
    )
    references = []
    real_bundle = builder_module.bundle_with_source_map

    def capture_entrypoint(entrypoint, *args):
        references.append(weakref.ref(entrypoint))
        return real_bundle(entrypoint, *args)

    monkeypatch.setattr(builder_module, "bundle_with_source_map", capture_entrypoint)

    BrowserBundleBuilder(project_root, cache_dir).build([selected], "run-1")
    gc.collect()

    assert references[0]() is None


def test_builder_rewrites_test_assertions_before_transpiling(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    (project_root / "browser_example.py").write_text(
        """from pyjs import js


@js
def test_value():
    actual = 1
    assert isinstance(actual, int)
    assert actual == 2, "wrong value"
""",
        encoding="utf-8",
    )
    builder = BrowserBundleBuilder(project_root, cache_dir)

    result = builder.build(
        [SelectedTest("browser_example.py::test_value", "browser_example", "test_value")],
        "run-1",
    )

    source = result.javascript
    assert "define('pyjs.testing.client.assertions'" in source
    assert "var __pyjs_assert_left_" in source
    assert "var __pyjs_assert_right_" in source
    assert "__pyjs_test_assert__(" in source
    assert "__pyjs_test_assert_compare__(" in source
    assert "'actual', '=='," in source
    assert "() => 'wrong value'" in source
    assert "__pyjsAssertCompare__" not in source


def test_builder_rewrites_pytest_raises_in_tests_and_helpers(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    (project_root / "browser_example.py").write_text(
        """import pytest
from pytest import raises as expect_raises
from pyjs import js


@js
def expect_error():
    with expect_raises(ValueError, match="bad"):
        raise ValueError("bad value")


@js
def test_raises():
    with pytest.raises(TypeError):
        raise TypeError("wrong type")
    expect_error()
""",
        encoding="utf-8",
    )

    result = BrowserBundleBuilder(project_root, cache_dir).build(
        [
            SelectedTest(
                "browser_example.py::test_raises",
                "browser_example",
                "test_raises",
            )
        ],
        "run-1",
    )

    source = result.javascript
    assert "__pyjs_test_raises__(TypeError)" in source
    assert "__pyjs_test_raises__(RangeError, {match: 'bad'})" in source
    assert "function expect_error()" in source
    assert "pytest.raises" not in source
    assert "expect_raises(" not in source


def test_builder_replaces_generic_types_from_a_previous_compilation(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    (project_root / "browser_example.py").write_text(
        """from pyjs import js


@js
class Value:
    def first(self):
        pass

    def second(self):
        pass


@js
async def create_value() -> Value:
    return Value()


@js
async def test_first():
    value = await create_value()
    value.first()


@js
async def test_second():
    value = await create_value()
    value.second()
""",
        encoding="utf-8",
    )
    builder = BrowserBundleBuilder(project_root, cache_dir)

    builder.build(
        [SelectedTest("browser_example.py::test_first", "browser_example", "test_first")],
        "run-1",
    )
    second = builder.build(
        [SelectedTest("browser_example.py::test_second", "browser_example", "test_second")],
        "run-2",
    )

    assert "\n    second() {" in second.javascript


def test_builder_recovers_after_a_failed_compilation(tmp_path):
    project_root = tmp_path / "project"
    cache_dir = project_root / ".pytest_cache" / "pyjs"
    project_root.mkdir()
    browser_test = project_root / "browser_test.py"
    browser_test.write_text(
        """from pyjs import js


@js
def test_value():
    values = set()
""",
        encoding="utf-8",
    )
    selected = SelectedTest("browser_test.py::test_value", "browser_test", "test_value")
    builder = BrowserBundleBuilder(project_root, cache_dir)

    with pytest.raises(
        CompilationError,
        match=r"Type arguments for set\(\) cannot be inferred",
    ):
        builder.build([selected], "bad-run")

    browser_test.write_text(
        """from pyjs import js


@js
def test_value():
    values = set[str]()
    values.add("good")
    assert 1 == 1
""",
        encoding="utf-8",
    )
    recovered = builder.build([selected], "good-run")

    assert "test_value: __pyjs_test_0" in recovered.javascript
    assert "initialize_test_runtime('good-run'" in recovered.javascript


def test_testing_signature_includes_all_python_runtime_sources(tmp_path, monkeypatch):
    package_root = tmp_path / "pyjs"
    compiler_source = package_root / "transpiler" / "analyzer.py"
    compiler_source.parent.mkdir(parents=True)
    compiler_source.write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(builder_module, "PYJS_PACKAGE_ROOT", package_root)

    first = compute_testing_signature()
    compiler_source.write_text("version = 2\n", encoding="utf-8")

    assert compute_testing_signature() != first
