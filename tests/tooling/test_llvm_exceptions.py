import pickle
import traceback
from pathlib import Path

import pytest

from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from pyjs.web.domx import CustomElement
from tests.native.settings_source import settings


def test_native_failure_is_picklable_and_displays_its_source_traceback():
    error = LLVMRuntimeError("message", "native source traceback", "ValueError", "builtins")
    restored = pickle.loads(pickle.dumps(error))
    assert restored.args == ("message",)
    assert restored.exception_type == "ValueError"
    assert restored.exception_module == "builtins"
    assert restored.native_traceback == "native source traceback"
    assert restored.__notes__ == [restored.native_traceback]
    assert "native source traceback" in "".join(traceback.format_exception(restored))


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_library_reports_error_and_remains_reusable(tmp_path, managed, optimize):
    setup = "gc_set_threshold(1000, byte_limit=128)" if managed else "pass"
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold

def render(value: int) -> str:
    {setup}
    if value < 0:
        raise ValueError("invalid café\\x00: " + str(value))
    return "value: " + str(value)
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", filename="page.py", optimize=optimize)
    saved = []
    try:
        for _ in range(3):
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(-5)
            assert caught.value.exception_type == "ValueError"
            assert caught.value.exception_module == "builtins"
            assert str(caught.value) == "invalid café\x00: -5"
            assert caught.value.native_traceback == (
                'Traceback (native PyJS):\n'
                '  File "page.py", line 7, in render\n'
                'ValueError: invalid café\x00: -5\n'
            )
            saved.append(caught.value)
            assert library._errors == []
            assert library.render(12) == "value: 12"
    finally:
        library.close()
    for error in saved:
        restored = pickle.loads(pickle.dumps(error))
        assert restored.args == error.args
        assert restored.exception_module == "builtins"
        assert restored.native_traceback == error.native_traceback
        assert restored.__notes__ == [error.native_traceback]


@pytest.mark.parametrize("optimize", [0, 2])
def test_same_named_application_errors_preserve_module_identity_after_close(tmp_path, optimize):
    source = '''
        from pyjs.native import gc_collect, gc_set_threshold

        class Failure(Exception):
            pass

        values: list[str] = []

        def render(value: str, fail: bool) -> str:
            gc_set_threshold(1, byte_limit=128)
            gc_collect()
            values.append(value)
            if fail:
                raise Failure("identical message")
            return str(values)
    '''
    errors = []
    for module in ("first_request", "second_request"):
        library = LLVM().compile_library(source, tmp_path / module, entry_point="render",
                                         module_name=module, filename="request.py", optimize=optimize)
        try:
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render("café", True)
            errors.append(caught.value)
            assert library.render("ready", False) == "['café', 'ready']"
        finally:
            library.close()
    assert errors[0].args == errors[1].args == ("identical message",)
    assert errors[0].native_traceback == errors[1].native_traceback
    for error, module in zip(errors, ("first_request", "second_request"), strict=True):
        restored = pickle.loads(pickle.dumps(error))
        assert restored.exception_type == error.exception_type == "Failure"
        assert restored.exception_module == error.exception_module == module


def test_direct_writer_failure_keeps_partial_output_and_allows_reuse(tmp_path):
    source = '''
from pyjs.web.domx import div
from pyjs.web.ssr import write_html_fd

def render(fail: bool, descriptor: int) -> int:
    status = write_html_fd(div("partial"), descriptor)
    if fail:
        raise ValueError("after output")
    return status
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", direct=True)
    output = tmp_path / "response"
    try:
        with output.open("wb") as destination:
            with pytest.raises(LLVMRuntimeError, match="after output"):
                library.render_to_fd(destination.fileno(), True)
            assert library.render_to_fd(destination.fileno(), False) == 0
        assert output.read_text() == "<div>partial</div>" * 2
    finally:
        library.close()


@pytest.mark.parametrize("reject", [False, True])
def test_settings_page_recovers_per_row_with_collection_in_cleanup(tmp_path, reject):
    source = (Path(__file__).parents[1] / "native/settings_source.py").read_text() + '''
from pyjs.native import gc_collect, gc_set_threshold

def render_checked(values: list[Setting], reject: bool) -> str:
    gc_set_threshold(1)
    rows: list[Element] = []
    for setting in values:
        try:
            if reject and setting.changed:
                raise ValueError("invalid setting: " + setting.name)
            rows.append(setting_row(setting))
        except ValueError as error:
            rows.append(div({"class": "error"}, str(error)))
        finally:
            gc_collect()
    return render_html(div(*rows))
'''
    counter = CustomElement.CUSTOM_ELEMENT_COUNTER
    CustomElement.CUSTOM_ELEMENT_COUNTER = 0
    try:
        comparison = LLVM().assert_library_matches_python(
            source, settings(), reject, directory=tmp_path,
            entry_point="render_checked",
        )
        assert comparison.native.count('class="error"') == (10 if reject else 0)
        comparison.library.close()
    finally:
        CustomElement.CUSTOM_ELEMENT_COUNTER = counter
