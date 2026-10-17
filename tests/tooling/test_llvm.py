import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from pyjs.analysis.source import create_module
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm_module
from pyjs.tooling.llvm import LLVM, LLVMComparison, LLVMExecution, LLVMLibrary
from pyjs.web.domx import CustomElement

SETTINGS_SOURCE = Path(__file__).parents[1] / "native/settings_source.py"


def test_manual_library_loading_requires_complete_schema_metadata(tmp_path):
    module = transpile_llvm_module('''
        def main(value: int | None, items: list[str | None]) -> str:
            return str(value) + str(items)
    ''', target="library")
    # Reject incomplete metadata before loading a shared object or allocating
    # its heap, not later while resolving an anonymous union reference.
    with pytest.raises(TypeError, match="type_definitions"):
        LLVMLibrary(tmp_path / "not-loaded.so", module.llvm_ir, module.parameters,
                    module.direct, module.managed, module.exceptions)
    path = LLVM().compile(module.llvm_ir, tmp_path, shared=True)
    library = LLVMLibrary(path, module.llvm_ir, module.parameters, module.direct,
                          module.managed, module.exceptions, module.type_definitions)
    try:
        assert library.render(3, ["a", None]) == "3['a', None]"
    finally:
        library.close()


def test_failed_compile_exposes_diagnostics_and_keeps_ir(tmp_path):
    source = "define i32 @main() { ret i32 not_an_integer }"
    with pytest.raises(subprocess.CalledProcessError) as caught:
        LLVM().compile(source, tmp_path)
    note, = caught.value.__notes__
    assert str(tmp_path / "program.ll") in note
    assert "error:" in note
    assert caught.value.stderr[-8000:] in note
    assert (tmp_path / "program.ll").read_text() == source


@pytest.mark.parametrize("oracle_exit,options", [(1, "print_stacktrace=0:halt_on_error=0"),
                                                 (0, "halt_on_error=0:exitcode=0")])
def test_sanitized_execution_stops_on_recoverable_ubsan_report(tmp_path, monkeypatch, oracle_exit, options):
    llvm = LLVM()
    compiler = llvm.ensure()
    # Pre-instrumented IR models third-party/runtime IR. A link-time
    # -fno-sanitize-recover flag alone cannot change these existing handlers.
    source = tmp_path / "overflow.c"
    source.write_text(f"int main(void) {{ volatile int x = 2147483647; x += 1; return {oracle_exit}; }}\n")
    ir = tmp_path / "overflow.ll"
    llvm.runner.run([compiler, "-S", "-emit-llvm", "-fsanitize=undefined", source, "-o", ir])
    monkeypatch.setenv("UBSAN_OPTIONS", options)
    execution = llvm._run_ir(ir.read_text(), tmp_path, name="checked", optimize=0,
                             pass_fds=(), sanitizers=("undefined",), timeout=10, artifacts=tmp_path)
    assert execution.returncode < 0
    assert "runtime error: signed integer overflow" in execution.stderr
    oracle = llvm._run_python(f"def main() -> int:\n    x = 2147483647\n    x += 1\n    return {oracle_exit}\n",
                              tmp_path, timeout=10)
    assert not LLVMComparison(oracle, execution).matches
    assert LLVMComparison(oracle, LLVMExecution("", oracle_exit, "", "")).matches
    assert not LLVMComparison(execution, execution).matches
    assert os.environ["UBSAN_OPTIONS"] == options


def test_llvm_uses_an_explicit_compiler(monkeypatch, tmp_path):
    executable = tmp_path / "clang"
    executable.write_text("clang", encoding="utf-8")
    runner = Mock()
    runner.run.return_value = subprocess.CompletedProcess(
        [executable, "--version"],
        0,
        stdout="clang version 21.1.8\n",
        stderr="",
    )
    monkeypatch.setenv("PYJS_CLANG", str(executable))

    llvm = LLVM(runner=runner)

    assert llvm.ensure() == executable
    assert llvm.version == "clang version 21.1.8"
    runner.run.assert_called_once_with(
        [executable, "--version"],
        capture_output=True,
    )


def test_llvm_compiles_and_executes_source(tmp_path):
    execution = LLVM().run_source(
        """
        def main() -> str:
            return "native output"
        """,
        directory=tmp_path,
    )

    assert execution.returncode == 0
    assert execution.stdout == "native output"
    assert execution.stderr == ""
    assert execution.artifacts == tmp_path
    assert (tmp_path / "program.ll").is_file()
    assert (tmp_path / "program").is_file()


@pytest.mark.parametrize(
    "source",
    [
        """
        def main() -> int:
            return 37
        """,
        """
        def main() -> str:
            return "same ✓"
        """,
    ],
)
def test_llvm_asserts_exact_cpython_parity(source, tmp_path):
    comparison = LLVM().assert_matches_python(source, directory=tmp_path)

    assert comparison.matches


def test_llvm_reports_cpython_native_mismatch(monkeypatch, tmp_path):
    llvm = LLVM()
    original = llvm.run_source

    def changed(*args, **kwargs):
        execution = original(*args, **kwargs)
        return type(execution)(
            execution.llvm_ir,
            execution.returncode,
            "changed",
            execution.stderr,
            execution.artifacts,
        )

    monkeypatch.setattr(llvm, "run_source", changed)

    with pytest.raises(AssertionError, match="CPython and native LLVM differ"):
        llvm.assert_matches_python(
            "def main() -> str: return 'original'",
            directory=tmp_path,
        )


@pytest.mark.parametrize("direct", [False, True])
def test_llvm_library_writes_without_materializing_a_python_string(
    direct,
    tmp_path,
):
    if direct:
        signature = "descriptor: int) -> int"
        result = "return document.write(root, descriptor)"
    else:
        signature = ") -> str"
        result = "return document.render(root)"
    library = LLVM().compile_library(
        f"""
        from pyjs.native import Document, div

        def main({signature}:
            document = Document()
            root = div(document, "shared library")
            {result}
        """,
        tmp_path,
        direct=direct,
    )
    reader, writer = os.pipe()
    try:
        status = library.render_to_fd(writer)
    finally:
        os.close(writer)
    try:
        output = os.read(reader, 4096)
    finally:
        os.close(reader)

    assert status == 0
    assert output == b"<div>shared library</div>"
    assert library.path.suffix == ".so"
    assert library.render_to_fd(-1) == 9


def test_llvm_library_writes_directly_to_a_socket(tmp_path):
    library = LLVM().compile_library(
        """
        from pyjs.native import Document, div

        def main(descriptor: int) -> int:
            document = Document()
            return document.write(div(document, "socket output"), descriptor)
        """,
        tmp_path,
        direct=True,
    )
    reader, writer = socket.socketpair()
    try:
        assert library.render_to_socket(writer) == 0
        writer.shutdown(socket.SHUT_WR)
        assert reader.recv(4096) == b"<div>socket output</div>"
    finally:
        reader.close()
        writer.close()


def test_llvm_public_web_dom_writes_directly_to_a_socket(tmp_path):
    library = LLVM().compile_library(
        """
        from pyjs.web.domx import div, tw
        from pyjs.web.ssr import write_html_fd

        def main(descriptor: int) -> int:
            pending: int | str = descriptor
            if not isinstance(pending, int):
                return -1
            return write_html_fd(
                div(tw("public"), "socket output"),
                pending,
            )
        """,
        tmp_path,
        direct=True,
    )
    reader, writer = socket.socketpair()
    try:
        assert library.render_to_socket(writer) == 0
        writer.shutdown(socket.SHUT_WR)
        assert reader.recv(4096) == b'<div class="public">socket output</div>'
    finally:
        reader.close()
        writer.close()


def test_llvm_library_marshals_scalar_arguments(tmp_path):
    source = """
        from pyjs.native import Document, div

        def render(
            prefix: str,
            count: int,
            enabled: bool,
            descriptor: int,
        ) -> int:
            document = Document()
            text = f"{prefix}-{count}" if enabled else prefix
            return document.write(div(document, text), descriptor)
    """
    comparison = LLVM().assert_library_matches_python(
        source,
        "rows",
        48,
        True,
        directory=tmp_path,
        entry_point="render",
        direct=True,
    )

    assert comparison.native == "<div>rows-48</div>"
    with pytest.raises(TypeError, match="count must be int, not bool"):
        comparison.library.render("rows", True, True)
    with pytest.raises(OverflowError, match="count does not fit"):
        comparison.library.render("rows", 1 << 63, True)


def test_llvm_library_marshals_shared_numeric_fields(tmp_path):
    library = LLVM().compile_library(
        """
        from pyjs import float32, int8
        from pyjs.native import Document, div

        class Reading:
            code: int8
            ratio: float32

            def __init__(self, code: int8, ratio: float32) -> None:
                self.code = code
                self.ratio = ratio

        def render(reading: Reading, descriptor: int) -> int:
            document = Document()
            if reading.code != 7:
                return document.write(div(document, "bad code"), descriptor)
            if reading.ratio != 1.5:
                return document.write(div(document, "bad ratio"), descriptor)
            return document.write(div(document, "ready"), descriptor)
        """,
        tmp_path,
        entry_point="render",
        direct=True,
    )

    assert library.render({"code": 7, "ratio": 1.5}) == "<div>ready</div>"


def test_llvm_library_requires_explicit_direct_output(tmp_path):
    with pytest.raises(
        LLVMUnsupported,
        match="pass direct=True",
    ):
        LLVM().compile_library(
            """
            from pyjs.web.domx import div
            from pyjs.web.ssr import render_html

            def render(limit: int) -> int:
                render_html(div(str(limit)))
                return 0
            """,
            tmp_path,
            entry_point="render",
        )


def test_llvm_python_comparison_restores_the_module_registry(tmp_path):
    module_name = "llvm_comparison_cleanup"
    python_module_name = f"{module_name}_python"
    sys.modules.pop(python_module_name, None)

    comparison = LLVM().assert_library_matches_python(
        """
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html

        def render(value: str) -> str:
            return render_html(div(value))
        """,
        "ready",
        directory=tmp_path,
        module_name=module_name,
        entry_point="render",
    )

    assert comparison.matches
    assert python_module_name not in sys.modules


def test_llvm_direct_library_flushes_outputs_larger_than_its_buffer(tmp_path):
    payload = "large & value " * 7000
    library = LLVM().compile_library(
        f"""
        from pyjs.native import Document, div

        def main(descriptor: int) -> int:
            document = Document()
            return document.write(
                div(document, {payload!r}),
                descriptor,
            )
        """,
        tmp_path,
        direct=True,
    )
    output = tmp_path / "output.html"
    with output.open("wb") as destination:
        assert library.render_to_fd(destination.fileno()) == 0
        assert library.render_to_fd(destination.fileno()) == 0

    expected = f"<div>{payload.replace('&', '&amp;')}</div>".encode()
    assert output.read_bytes() == expected * 2


@pytest.mark.parametrize("entry_point", ["render_settings", "write_settings"])
def test_llvm_library_marshals_settings_objects_and_matches_cpython(
    entry_point,
    tmp_path,
):
    source = SETTINGS_SOURCE.read_text()
    module = create_module(
        source,
        str(SETTINGS_SOURCE),
        "native_settings_arguments",
    )
    settings = module.settings()

    counter = CustomElement.CUSTOM_ELEMENT_COUNTER
    CustomElement.CUSTOM_ELEMENT_COUNTER = 0
    try:
        comparison = LLVM().assert_library_matches_python(
            source,
            settings,
            directory=tmp_path,
            filename=str(SETTINGS_SOURCE),
            module_name="native_settings_input",
            entry_point=entry_point,
            direct=entry_point == "write_settings",
        )
    finally:
        CustomElement.CUSTOM_ELEMENT_COUNTER = counter

    assert comparison.matches
    assert comparison.native.startswith('<div class="catalog rounded"')
    assert comparison.native.count("<details") == 48
    parameter = comparison.library.parameters[0]
    assert parameter.name == "values"
    assert parameter.value_type.kind == "list"
    assert parameter.value_type.item_type is not None
    assert parameter.value_type.item_type.kind == "object"
    assert tuple(field.name for field in parameter.value_type.item_type.fields) == tuple(
        module.Setting.__annotations__
    )
    assert (
        comparison.library.render([vars(setting) for setting in settings])
        == comparison.native
    )
