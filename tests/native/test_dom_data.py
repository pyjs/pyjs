import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_data_helpers_share_attributes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.set_data("title", "<hello>")
def read(value: CustomElement) -> str | None:
    return value.get_data("title")
def main() -> str:
    panel = Panel()
    assert read(panel) == "<hello>"
    assert panel.getAttribute("data-title") == "<hello>"
    panel.setAttribute("data-title", "changed")
    assert panel.get_data(name="title") == "changed"
    panel.set_data(value="42", name="page")
    panel.removeAttribute("data-title")
    assert panel.get_data("title") is None
    return render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_data_helpers_keep_order_optional_views_and_overrides(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.native import gc_collect
class Panel(CustomElement):
    def set_data(self, name: str, value: str) -> None:
        super().set_data(name, "prefix:" + value)
    def get_data(self, name: str) -> str | None:
        return super().get_data(name)
def argument(log: list[str], value: str) -> str:
    log.append(value)
    gc_collect()
    return value
def projected(value: CustomElement | None) -> Element | None:
    return value
def main() -> str:
    log: list[str] = []
    panel = Panel()
    panel.set_data(value=argument(log, "value"), name=argument(log, "name"))
    assert panel.get_data("name") == "prefix:value"
    plain: list[CustomElement] = [panel]
    assert projected(plain[0]) is panel
    assert projected(None) is None
    return repr(log) + str(plain[0].getAttribute("data-name"))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_ordinary_elements_do_not_gain_custom_data_helpers():
    with pytest.raises(CompilationError):
        transpile_llvm('''
from pyjs.web.domx import div
def main() -> str | None:
    return div().get_data("name")
''')


@pytest.mark.parametrize("operation", ["get_data", "set_data"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_opaque_data_helpers_dispatch_overrides(tmp_path, operation, optimize):
    arguments = '"name"' if operation == "get_data" else '"name", "value"'
    comparison = LLVM().assert_matches_python(f'''
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.calls = 0
    def get_data(self, name: str) -> str | None:
        self.calls += 1
        return "override"
    def set_data(self, name: str, value: str) -> None:
        self.calls += 1
def change(value: CustomElement) -> str:
    return str(value.{operation}({arguments}))
def main() -> str:
    panel = Panel()
    result = change(panel)
    return result + str(panel.calls)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_mutable_custom_dom_view_cannot_accept_plain_elements():
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage and element types"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
class Panel(CustomElement):
    pass
def add(values: list[Element]) -> None:
    values.append(div())
def main() -> str | None:
    values: list[CustomElement] = [Panel()]
    add(values)
    return values[1].get_data("title")
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_tagged_data_helpers_keep_member_overrides(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.native import gc_collect
from pyjs.web.domx import CustomElement
class First(CustomElement):
    pass
class Second(CustomElement):
    data_name = state("initial")
    def __init__(self):
        super().__init__()
        self.runs = 0
    @effect(data_name)
    def changed(self) -> None:
        gc_collect()
        self.runs += 1
    def get_data(self, name: str) -> str | None:
        value = super().get_data(name)
        return None if value is None else "override:" + value
def argument(log: list[str], value: str) -> str:
    log.append(value)
    gc_collect()
    return value
def change(value: First | Second, log: list[str]) -> str:
    value.set_data(value=argument(log, "ok"), name=argument(log, "name"))
    value.append("old")
    value.replaceChildren("new")
    value.setAttribute("title", "done")
    assert value.hasAttribute("title")
    assert value.getAttribute("title") == "done"
    value.removeAttribute("title")
    return str(value.get_data("name"))
def main() -> str:
    second = Second()
    values: list[First | Second] = [First(), second]
    result: list[str] = []
    log: list[str] = []
    for value in values:
        result.append(change(value, log))
    assert second.runs == 2
    return repr(result) + repr(log)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
