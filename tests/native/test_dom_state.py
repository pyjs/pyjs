import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("name", ["_initialized", "__pyjs_ref__"])
@pytest.mark.parametrize("setter", ["pass", "raise ValueError('initialization hook')"])
def test_class_local_reserved_properties_are_diagnosed(name, setter):
    with pytest.raises(LLVMUnsupported, match="framework initialization or reference fields"):
        transpile_llvm(f'''
from pyjs import state
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    value = state(1)
    @property
    def {name}(self) -> bool:
        return False
    @{name}.setter
    def {name}(self, value: bool) -> None:
        {setter}
def main() -> int:
    return Panel().value
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_attribute_mutation_before_base_initialization(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import state
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
def change(element: Element) -> None:
    element.setAttribute("value", "3")
    element.removeAttribute("value")
    element.setAttribute("value", "4")
class Panel(CustomElement):
    value = state(7)
    def __init__(self):
        change(self)
        super().__init__()
class NoSuper(CustomElement):
    value = state(7)
    def __init__(self):
        change(self)
def main() -> str:
    panel = Panel()
    missing = NoSuper()
    assert panel.value == 7
    assert missing.value == 4
    missing.value = 5
    return render_html(panel) + render_html(missing)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_state_descriptor_subclass_does_not_silently_lose_its_behavior():
    with pytest.raises(LLVMUnsupported, match="standard StateField descriptors"):
        transpile_llvm('''
from pyjs.state import StateField
from pyjs.web.domx import CustomElement
class Alternate(StateField):
    def __get__(self, instance, owner=None):
        return self if instance is None else 99
class Panel(CustomElement):
    value = Alternate(1)
def main() -> int:
    return Panel().value
''')


@pytest.mark.parametrize("default", ["True", "42", "1.5", "'ready'"])
def test_state_alone_retains_implicit_runtime_dependencies(tmp_path, default):
    result = LLVM().assert_matches_python(f'''
from pyjs import state
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    value = state({default})
def main() -> int:
    return 0 if Panel().value == {default} else 1
''', directory=tmp_path)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_state_preserves_narrowed_scalar_kind(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import state
from pyjs.web.domx import CustomElement
class Panel(CustomElement):
    count = state(0)
    enabled = state(False)
def put(panel: Panel, value: int | bool) -> None:
    panel.count = value
    if isinstance(value, bool):
        panel.enabled = value
def main() -> str:
    panel = Panel()
    values: list[int | bool] = [True, 5, False]
    result: list[str] = []
    for value in values:
        put(panel, value)
        result.append(str(panel.getAttribute("count")) + ":" + str(panel.enabled))
    return repr(result)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize(("default", "changed"), [
    ("'old'", "'new'"), ("1", "-9223372036854775808"), ("1.5", "-0.0"),
    ("False", "True"), ("True", "False"),
])
def test_state_write_allocation_failure_preserves_value_and_allows_retry(tmp_path, optimize, managed, default, changed):
    attribute = None if changed == "False" else "" if changed == "True" else changed.strip("'")
    source = transpile_llvm(f'''
from pyjs import state
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
from tests.native.allocation_support import arm, remaining
class Panel(CustomElement):
    value = state({default})
def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    for width in [0, 7, 20]:
        stages = 0
        point = 0
        while point <= stages:
            panel = Panel()
            for index in range(width):
                panel.setAttribute("data-" + str(index), "kept")
            before = render_html(panel)
            caught = False
            arm(1000 if point == 0 else point)
            try:
                panel.value = {changed}
            except MemoryError:
                caught = True
            if point == 0:
                stages = 1000 - remaining()
            arm(0)
            {"gc_collect()" if managed else "pass"}
            assert caught == (point != 0)
            assert stages == 0 if {changed == "False"} else 0 < stages < 1000
            if caught:
                assert panel.value == {default} and render_html(panel) == before
            panel.value = {changed}
            assert panel.value == {changed}
            assert panel.getAttribute("value") == {attribute!r}
            for index in range(width):
                assert panel.getAttribute("data-" + str(index)) == "kept"
            point += 1
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=managed, optimize=optimize)
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("member", ["value: int", "value = 1", "def __init__(self): self.value = 1"])
def test_state_cannot_replace_inherited_ordinary_members(member):
    with pytest.raises(LLVMUnsupported, match="state cannot replace ordinary application members"):
        transpile_llvm(f'''
from pyjs import state
from pyjs.web.domx import CustomElement
class Base(CustomElement):
    {member}
class Child(Base):
    value = state(1)
def main() -> int:
    return Child().value
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_state_attributes_are_authoritative(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import state
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    title = state("Ready")
    count = state(1)
    ratio = state(1.5)
    enabled = state(True)
    open = state(False)
    def __init__(self):
        super().__init__()
        self.title = "Chosen"
        self.count = 4
def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    initial = render_html(panel)
    panel.setAttribute("count", "１２")
    panel.setAttribute("ratio", " 2.25 ")
    panel.removeAttribute("title")
    panel.removeAttribute("enabled")
    panel.setAttribute("open", "false")
    assert panel.count == 12
    assert panel.ratio == 2.25
    assert panel.title == "Ready"
    assert not panel.enabled
    assert panel.open
    panel.count += 1
    panel.ratio = 4.5
    panel.title = "<changed>"
    panel.open = False
    panel.enabled = True
    gc_collect()
    panel.setAttribute("count", "invalid")
    try:
        value = panel.count
    except ValueError:
        panel.removeAttribute("count")
    else:
        return "missing error"
    assert panel.count == 1
    return initial + render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_state_union_views_and_reference_properties(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from typing import cast
from pyjs import state
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, ref
from pyjs.web.ssr import render_html
class First(CustomElement):
    count = state(1)
    value = state("first")
    def __init__(self):
        super().__init__()
        self.child = ref(div("body"))
        self.append(self.child)
    @property
    def label(self) -> str:
        return self.value
    @label.setter
    def label(self, value: str) -> None:
        self.value = value
class Second(CustomElement):
    count = state(2)
    value = state("second")
class Ordinary:
    def __init__(self):
        self.count = 3
        self.value: object = "ordinary"
def advance(value: First | Second | Ordinary) -> str:
    value.count += 1
    return cast(str, value.value) + ":" + str(value.count)
def attrs(value: Element) -> None:
    value.setAttribute("count", "40")
def main() -> str:
    first = First()
    first.label = "changed"
    attrs(first)
    values: list[First | Second | Ordinary] = [first, Second(), Ordinary()]
    result: list[str] = []
    for value in values:
        gc_collect()
        result.append(advance(value))
    return repr(result) + render_html(first)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize(("declaration", "message"), [
    ('value = state(9223372036854775808)', "default is outside native signed i64"),
    ('value = 10', "descriptors cannot be shadowed"),
    ('value = state(10)', "descriptor overrides"),
    ('def __setattr__(self, name: str, value: object): pass', "attribute access hooks"),
    ('_initialized: bool', "framework initialization or reference fields"),
    ('__pyjs_ref__: bool', "framework initialization or reference fields"),
    ('def getAttribute(self, name: str) -> str | None: return "override"', "DOM attribute overrides"),
    ('def attributeChangedCallback(self, name: str, old: str | None, new: str | None): pass', "observed-attribute callbacks"),
])
def test_state_unsupported_callbacks_and_defaults_are_diagnosed(declaration, message):
    with pytest.raises(LLVMUnsupported, match=message) as caught:
        transpile_llvm(f'''
from pyjs import state
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Base(CustomElement):
    value = state(1)
class Child(Base):
    {declaration}
def main() -> str:
    return render_html(Child())
''')
    # Callback inventories can reject while validating Base's reached family;
    # descriptor/layout checks reject at Child itself. Both need real locations.
    assert any(location in note for note in caught.value.__notes__ for location in (
        "_pyjs_native_.py:5:1 (Base class)", "_pyjs_native_.py:7:1 (Child class)",
    ))


@pytest.mark.parametrize("optimize", [0, 2])
def test_state_initialization_presence_and_inheritance(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import state
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Base(CustomElement):
    value = state(5)
    enabled = state(True)
class Child(Base):
    label = state("child")
    def __init__(self, events: list[str]):
        events.append(str(self.value) + ":" + str(self.enabled))
        self.value = 99
        super().__init__()
        events.append(str(self.value))
        self.value = 8
class NoSuper(CustomElement):
    value = state(5)
    def __init__(self):
        self.value = 99
def change(value: Base) -> None:
    value.value += 2
def main() -> str:
    events: list[str] = []
    child = Child(events)
    change(child)
    missing = NoSuper()
    assert missing.value == 5
    assert missing.getAttribute("value") is None
    missing.value = 3
    assert missing.value == 3
    child.value = True
    assert child.getAttribute("value") == "True"
    try:
        current = child.value
    except ValueError:
        child.value = 10
    else:
        return "bool was normalized"
    return repr(events) + render_html(child) + render_html(missing)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_state_assignment_order_and_base_reinitialization(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs import state
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    row_count = state(2)
    def __init__(self, events: list[str]):
        self.row_count = rhs(events)
        super().__init__()
        self.row_count = 4
    def reset(self) -> None:
        super().__init__()
def rhs(events: list[str]) -> int:
    events.append("rhs")
    return 8
def receiver(panel: Panel, events: list[str]) -> Panel:
    events.append("receiver:" + str(panel.row_count))
    return panel
def main() -> str:
    events: list[str] = []
    panel = Panel(events)
    receiver(panel, events).row_count = rhs(events)
    assert panel.getAttribute("row-count") == "8"
    panel.reset()
    assert panel.row_count == 2
    assert panel.getAttribute("row-count") is None
    panel.row_count = 9
    return repr(events) + render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
