import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("method, parameters", [("staticmethod", ""), ("classmethod", "cls")])
def test_effect_methods_require_an_instance_receiver(method, parameters):
    with pytest.raises(LLVMUnsupported, match="state effects require reached ordinary methods"):
        transpile_llvm(f'''
from pyjs import effect, state
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    value = state(1)
    @effect(value)
    @{method}
    def changed({parameters}) -> None:
        pass
def main() -> int:
    return Panel().value
''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("other", ["True", '"text"'])
def test_effect_dispatch_keeps_generic_storage_families_separate(tmp_path, optimize, other):
    result = LLVM().assert_matches_python(f'''
from pyjs import effect, state
from pyjs.native import gc_collect
from pyjs.web.domx import CustomElement
class Panel[T](CustomElement):
    value = state(1)
    def __init__(self, payload: T):
        super().__init__()
        self.payload = payload
        self.runs = 0
    @effect(value)
    def changed(self) -> None:
        gc_collect()
        self.runs += 1
def main() -> str:
    first = Panel(3)
    second = Panel({other})
    first.value = 2
    second.setAttribute("value", "2")
    return str(first.runs) + ":" + str(second.runs)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "2:2"
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_effect_dispatch_retains_nominal_child_overrides(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.web.domx import CustomElement
class Panel[T](CustomElement):
    value = state(1)
    def __init__(self, payload: T):
        super().__init__()
        self.payload = payload
        self.runs = 0
    @effect(value)
    def changed(self) -> None:
        self.runs += 1
class Child(Panel[int]):
    def changed(self) -> None:
        super().changed()
        self.runs += 1
def change(value: Panel[int]) -> None:
    value.value = 2
def main() -> str:
    first = Panel(3)
    second = Panel(True)
    child = Child(4)
    change(first)
    change(child)
    second.value = 2
    return str(first.runs) + ":" + str(second.runs) + ":" + str(child.runs)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "2:2:4"
    assert result.native.stderr == ""


def test_custom_initial_effect_hook_is_not_silently_bypassed():
    with pytest.raises(LLVMUnsupported, match="custom initial-effect hooks"):
        transpile_llvm('''
from pyjs import effect, state
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    value = state(1)
    @effect(value)
    def changed(self) -> None:
        pass
    def _run_initial_effects(self) -> None:
        raise ValueError("custom hook")
def main() -> int:
    return Panel().value
''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ['panel.data_value = "new"', 'panel.set_data("value", "new")'])
def test_failed_state_publication_does_not_run_effects(tmp_path, optimize, operation):
    source = transpile_llvm(f'''
from pyjs import effect, state
from pyjs.web.domx import CustomElement
from tests.native.allocation_support import arm
class Panel(CustomElement):
    data_value = state("old")
    def __init__(self):
        super().__init__()
        self.runs = 0
    @effect(data_value)
    def changed(self) -> None:
        self.runs += 1
def main() -> int:
    failures = 0
    for point in range(1, 25):
        panel = Panel()
        panel.runs = 0
        arm(point)
        try:
            {operation}
        except MemoryError:
            arm(0)
            failures += 1
            assert panel.data_value == "old"
            assert panel.runs == 0
            {operation}
        arm(0)
        assert panel.data_value == "new"
        assert panel.runs == 1
    assert 0 < failures < 24
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=False, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("statement", [
    'tag(panel, {"value": "2"})',
    'opaque(panel)',
])
def test_effectful_opaque_and_bulk_paths_are_not_silent(statement):
    with pytest.raises(LLVMUnsupported, match="observed-attribute callbacks"):
        transpile_llvm(f'''
from pyjs import effect, state
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
class Panel(CustomElement):
    value = state(1)
    @effect(value)
    def changed(self) -> None:
        pass
def opaque(value: Element) -> None:
    value.setAttribute("value", "2")
def main() -> int:
    panel = Panel()
    {statement}
    return panel.value
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_initial_and_changed_effects_share_attribute_state(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, ref, span, tag
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    title = state("Ready")
    count = state(1)
    enabled = state(True)
    def __init__(self, log: list[str]):
        super().__init__()
        self.log = log
        self.title = "Chosen"
        self.count = 4
        self.output = ref(span("pending"))
        self.output.setAttribute("class", "status")
        tag(self, self.output)
    @effect(title, count)
    def render_state(self) -> None:
        gc_collect()
        self.log.append(self.title + ":" + str(self.count))
        self.enabled = False
        self.output.textContent = self.title + ":" + str(self.count)
    @effect(enabled)
    def render_enabled(self) -> None:
        self.log.append("enabled:" + str(self.enabled))
def main() -> str:
    gc_set_threshold(1)
    log: list[str] = []
    panel = Panel(log)
    panel.count = 5
    panel.count = 5
    panel.setAttribute("title", "Next")
    panel.set_data("runs", "41")
    assert panel.get_data("runs") == "41"
    panel.removeAttribute("count")
    return repr(log) + render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_data_effects_keep_generated_names_alive_across_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    data_value = state("old")
    data_other = state("other")
    def __init__(self):
        super().__init__()
        self.log: list[str] = []
    @effect(data_value)
    def first(self) -> None:
        gc_collect()
        self.log.append("value:" + self.data_value)
    @effect(data_other)
    def second(self) -> None:
        self.log.append("other:" + self.data_other)
def change(panel: Panel, name: str, value: str) -> None:
    panel.set_data(name, value)
def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    change(panel, "value", "new")
    change(panel, "other", "changed")
    return repr(panel.log)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_effects_follow_actual_class_through_base_and_union_receivers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.native import gc_collect
from pyjs.web.domx import CustomElement
class Base(CustomElement):
    value = state(1)
    log: list[str]
    def __init__(self, log: list[str]):
        super().__init__()
        self.log = log
    @effect(value)
    def changed(self, prefix: str = "base") -> None:
        self.log.append(prefix + str(self.value))
class Child(Base):
    def changed(self, prefix: str = "base") -> None:
        gc_collect()
        super().changed(prefix)
        self.log.append("child")
    @effect(Base.value)
    def extra(self) -> None:
        self.log.append("extra")
class Sibling(Base):
    pass
class Other(CustomElement):
    value = state(2)
    def __init__(self, log: list[str]):
        super().__init__()
        self.log = log
    @effect(value)
    def changed(self) -> None:
        self.log.append("other" + str(self.value))
def change(value: Base) -> None:
    value.value += 1
def joined(value: Base | Other) -> None:
    value.value += 1
def main() -> str:
    log: list[str] = []
    child = Child(log)
    sibling = Sibling(log)
    other = Other(log)
    change(child)
    change(sibling)
    values: list[Base | Other] = [child, sibling, other]
    for value in values:
        joined(value)
    return repr(log)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_effect_exception_keeps_published_state_and_allows_recovery(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.native import gc_collect
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    value = state(1)
    def __init__(self, log: list[str], saved: list[Panel], fail: bool):
        self.log = log
        saved.append(self)
        super().__init__()
        if fail:
            self.value = 9
    @effect(value)
    def first(self) -> None:
        gc_collect()
        self.log.append("first:" + str(self.value))
        if self.value == 9:
            raise ValueError("effect")
    @effect(value)
    def second(self) -> None:
        self.log.append("second:" + str(self.value))
def main() -> str:
    log: list[str] = []
    saved: list[Panel] = []
    try:
        Panel(log, saved, True)
    except ValueError as error:
        log.append(str(error))
    panel = saved[0]
    assert panel.value == 9
    panel.value = 9
    panel.value = 10
    try:
        panel.setAttribute("value", "9")
    except ValueError as error:
        log.append(str(error))
    assert panel.value == 9
    panel.removeAttribute("value")
    assert panel.value == 1
    return repr(log)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_no_super_and_failed_constructors_preserve_effect_phases(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import effect, state
from pyjs.native import gc_collect
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    value = state(7)
    enabled = state(True)
    def __init__(self, log: list[str], saved: list[Panel], fail: bool):
        self.log = log
        saved.append(self)
        self.setAttribute("value", "3")
        self.value = 99
        if fail:
            raise ValueError("constructor")
    @effect(value, enabled)
    def changed(self) -> None:
        gc_collect()
        self.log.append(str(self.value) + ":" + str(self.enabled))
def main() -> str:
    log: list[str] = []
    saved: list[Panel] = []
    panel = Panel(log, saved, False)
    panel.value += 2
    panel.enabled = True
    try:
        Panel(log, saved, True)
    except ValueError:
        pass
    failed = saved[1]
    failed.value = 99
    assert failed.value == 3
    failed.setAttribute("value", "4")
    assert failed.value == 4
    return repr(log)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
