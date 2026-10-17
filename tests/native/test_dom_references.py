import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_proxy_subclasses_share_the_declared_element_slot(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import ProxyElement, div, span
from pyjs.web.ssr import render_html
from pyjs.web.ui.button import Button

class Label(ProxyElement):
    def __init__(self, text: str):
        self.element = span(text)

def replace(proxy: ProxyElement) -> None:
    proxy.element = div("replacement<&")

def main() -> str:
    gc_set_threshold(1)
    buttons = [Button("First"), Button("Second", href="/next")]
    label = Label("original")
    alias: ProxyElement = label
    replace(alias)
    gc_collect()
    label.setAttribute("data-kept", "yes")
    labels = [label, Label("last")]
    return render_html(div(div(*buttons), div(*labels)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("control", ["Input", "Textarea", "Slider"])
def test_proxy_control_downcasts_keep_an_explicit_native_boundary(control):
    # Native downcasts from the broad Element slot are a separate capability;
    # preserving declarations must not turn them into unchecked pointer casts.
    with pytest.raises(LLVMUnsupported, match="native concrete casts require matching types or an application upcast"):
        transpile_llvm(f'''
from pyjs.web.ui.input import Input
from pyjs.web.ui.slider import Slider
from pyjs.web.ui.textarea import Textarea
def main() -> str:
    return {control}().get_value()
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_hydration_marker_survives_aliases_and_delayed_assignment(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, ref
from pyjs.web.ssr import render_html

class Panel(CustomElement):
    output: Element
    other: Element

def marked(value: Element) -> Element:
    return ref(value)

def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    child = div("hello")
    aliases = [child]
    assert marked(aliases[0]) is child
    gc_collect()
    panel.setAttribute("data-self-id", "chosen<&")
    panel.output = child
    panel.other = div("plain")
    panel.append(panel.output, panel.other)
    assert ref(3) == 3
    assert ref("text") == "text"
    return render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
    assert result.native.stdout == (
        '<pyjs-panel data-self-id="chosen&lt;&amp;"><div id="chosen&lt;&amp;-output">hello</div>'
        '<div>plain</div></pyjs-panel>'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_duplicate_reference_id_fails_before_field_publication(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, ref
from pyjs.web.ssr import render_html

class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.output = div("original")

def main() -> str:
    panel = Panel()
    blocked = ref(div({"id": ""}, "blocked"))
    original = panel.output
    try:
        panel.output = blocked
    except ValueError:
        assert panel.output is original
    else:
        return "missing error"
    blocked.removeAttribute("id")
    panel.output = blocked
    try:
        panel.output = blocked
    except ValueError:
        assert panel.output is blocked
    else:
        return "lost marker"
    panel.append(panel.output)
    return render_html(panel)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
    assert result.native.stdout == '<pyjs-panel data-self-id="ce1"><div id="ce1-output">blocked</div></pyjs-panel>'


def test_erased_reference_requires_narrowing():
    with pytest.raises(LLVMUnsupported, match="hydration references require a typed value"):
        transpile_llvm('''
from pyjs.web.domx import div, ref
def keep(value: object) -> object:
    return ref(value)
def main() -> int:
    keep(div())
    return 0
''')


def test_erased_field_assignment_cannot_lose_a_reference_marker():
    with pytest.raises(LLVMUnsupported, match="hydration references require a typed value"):
        transpile_llvm('''
from pyjs.web.domx import CustomElement, div, ref
class Panel(CustomElement):
    output: object
def assign(panel: Panel, value: object) -> None:
    panel.output = value
def main() -> int:
    assign(Panel(), ref(div()))
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_proxy_reference_marker_belongs_to_wrapper_and_survives_rebinding(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, div, ref
from pyjs.web.ssr import render_html
class Box(ProxyElement):
    def __init__(self, element: Element):
        self.padding = 42
        self.element = element
    def label(self) -> str:
        return "base"
class Child(Box):
    def label(self) -> str:
        return "child"
class Panel(CustomElement):
    output: Box
    plain: Element
def mark(value: Box) -> Box:
    return ref(value)
def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    node = div("first")
    box = Child(node)
    aliases = [box]
    assert mark(aliases[0]) is box
    unmarked = Box(node)
    panel.output = unmarked
    panel.plain = node
    assert node.getAttribute("id") is None
    box.element = div("second")
    gc_collect()
    panel.output = box
    assert box.padding == 42
    assert box.label() == "child"
    assert node.getAttribute("id") is None
    assert box.getAttribute("id") == "ce1-output"
    old = box.element
    box._hydrate(div({"id": "blocked"}, "third"))
    panel.output = unmarked
    try:
        panel.output = box
    except ValueError:
        assert panel.output is unmarked
    else:
        return "missing duplicate error"
    box.removeAttribute("id")
    panel.output = box
    assert old.getAttribute("id") == "ce1-output"
    # A marked backing node does not mark a fresh wrapper around it.
    marked_node = ref(div("marked node"))
    fresh = Box(marked_node)
    panel.output = fresh
    assert marked_node.getAttribute("id") is None
    panel.plain = marked_node
    return render_html(div(node, old, box, fresh))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_and_nullable_proxy_references_publish_only_after_hydration(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ProxyElement, div, ref
from pyjs.web.ssr import render_html
class Panel(CustomElement):
    output: ProxyElement | None
    mixed: ProxyElement | Element | str | None
def mark(value: ProxyElement | None) -> ProxyElement | None:
    return ref(value)
def mixed(value: ProxyElement | Element | str | None) -> ProxyElement | Element | str | None:
    return ref(value)
def assign(panel: Panel, value: ProxyElement | Element | str | None) -> None:
    panel.mixed = value
def main() -> str:
    panel = Panel()
    empty = ProxyElement()
    panel.output = empty
    panel.output = None
    assert mark(None) is None
    assert mark(empty) is empty
    try:
        panel.output = empty
    except AttributeError:
        assert panel.output is None
    else:
        return "missing element error"
    empty._hydrate(div("ready"))
    gc_collect()
    panel.output = empty
    assign(panel, mixed(None))
    assert panel.mixed is None
    assign(panel, mixed("text"))
    assert panel.mixed == "text"
    empty.element = div("new")
    assign(panel, mixed(empty))
    assert panel.mixed is empty
    saved = empty.element
    node = div("direct")
    assign(panel, mixed(node))
    return render_html(div(saved, node))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("hook", ["getAttribute", "setAttribute"])
def test_proxy_hydration_does_not_bypass_attribute_overrides(hook):
    overrides = {
        "getAttribute": 'def getAttribute(self, name: str) -> str | None: return "override"',
        "setAttribute": 'def setAttribute(self, name: str, value: str) -> None: pass',
    }
    with pytest.raises(LLVMUnsupported, match="proxy hydration does not support"):
        transpile_llvm('''
from pyjs.web.domx import CustomElement, ProxyElement, div, ref
class Box(ProxyElement):
    HOOK
class Panel(CustomElement):
    output: ProxyElement
def main() -> int:
    panel = Panel()
    box = Box()
    box.element = div()
    panel.output = ref(box)
    return 0
'''.replace("HOOK", overrides[hook]))


@pytest.mark.parametrize("declaration", ["__pyjs_ref__: bool", "__pyjs_ref__ = True",
                                        "def __init__(self): self.__pyjs_ref__ = False"])
def test_proxy_reference_marker_cannot_be_shadowed(declaration):
    with pytest.raises(LLVMUnsupported, match="proxy reference markers must be managed by ref"):
        transpile_llvm(f'''
from pyjs.web.domx import ProxyElement, ref
class Box(ProxyElement):
    {declaration}
def main() -> int:
    ref(Box())
    return 0
''')


def test_proxy_library_inputs_require_compiled_construction():
    with pytest.raises(LLVMUnsupported, match="proxy wrappers must be constructed in compiled code"):
        transpile_llvm('''
from pyjs.web.domx import ProxyElement, ref
from pyjs.web.ssr import render_html
def main(value: ProxyElement) -> str:
    return render_html(ref(value).element)
''', target="library")


@pytest.mark.parametrize("optimize", [0, 2])
def test_proxy_reference_precedes_setter_and_retains_generic_fields(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, ProxyElement, div, ref
from pyjs.web.ssr import render_html
class Box[T](ProxyElement):
    def __init__(self, payload: T):
        self.payload = payload
        self.element = div(str(payload))
class Panel(CustomElement):
    shadow: Box[int]
    def __init__(self):
        super().__init__()
        self.events: list[str] = []
        self.saved = [Box(0)]
    @property
    def output(self) -> Box[int]:
        return self.saved[0]
    @output.setter
    def output(self, value: Box[int]) -> None:
        self.events.append(str(value.getAttribute("id")))
        gc_collect()
        if value.payload < 0:
            raise ValueError("setter failed")
        if value.payload == 43:
            self.shadow = value
        self.saved[0] = value
def main() -> str:
    gc_set_threshold(1)
    panel = Panel()
    panel.output = ref(Box(42))
    assert panel.output.payload == 42
    rejected = ref(Box(-1))
    try:
        panel.output = rejected
    except ValueError:
        assert panel.output.payload == 42
    else:
        return "missing setter error"
    assert rejected.getAttribute("id") == "ce1-output"
    try:
        panel.output = rejected
    except ValueError:
        assert len(panel.events) == 2
    else:
        return "missing hydration error"
    try:
        panel.output = ref(Box(43))
    except ValueError:
        # A setter assigning another custom-element field repeats hydration,
        # unlike storing the value inside an ordinary container.
        assert panel.output.payload == 42
        assert len(panel.events) == 3
    else:
        return "missing nested hydration error"
    return repr(panel.events) + render_html(div(panel.output, rejected))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("hook", ["__setattr__", "get_data"])
def test_reference_assignment_does_not_bypass_owner_hooks(hook):
    overrides = {
        "__setattr__": "def __setattr__(self, name: str, value: object): pass",
        "get_data": 'def get_data(self, name: str) -> str: return "override"',
    }
    with pytest.raises(LLVMUnsupported, match="hydration assignment does not support custom"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ref
class Child(CustomElement):
    pass
class Panel(CustomElement):
    output: Element
    HOOK
def main() -> int:
    panel = Panel()
    panel.output = ref(Child())
    return 0
'''.replace("HOOK", overrides[hook]))


@pytest.mark.parametrize("view", ["Child", "Base", "Element", "Child | str | None"])
@pytest.mark.parametrize("body", ["pass", 'if name == "__pyjs_ref__": raise ValueError("marker refused")'])
def test_reference_marking_does_not_bypass_child_hooks(view, body):
    with pytest.raises(LLVMUnsupported, match="ref marking does not support child __setattr__ overrides") as caught:
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ref
class Base(CustomElement):
    pass
class Child(Base):
    def __setattr__(self, name: str, value: object):
        {body}
def mark(value: {view}) -> {view}:
    return ref(value)
def main() -> int:
    mark(Child())
    return 0
''')
    expected_view = "an opaque DOM value" if view == "Element" else ("Base value" if view == "Base" else "Child value")
    assert f"Child.__setattr__ is reachable through {expected_view}" in str(caught.value)


def test_opaque_reference_diagnostic_names_unrelated_reached_override():
    with pytest.raises(LLVMUnsupported, match="Fancy.__setattr__ is reachable through an opaque DOM value"):
        transpile_llvm('''
from pyjs.web.domx import CustomElement, div, ref
class Fancy(CustomElement):
    def __setattr__(self, name: str, value: object):
        pass
def main() -> int:
    Fancy()
    ref(div())
    return 0
''')


def test_reference_marking_ignores_unreached_child_overrides(tmp_path):
    result = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, ref
from pyjs.web.ssr import render_html
class Base(CustomElement):
    pass
class Unreached(Base):
    def __setattr__(self, name: str, value: object):
        pass
def mark(value: Element) -> Element:
    return ref(value)
def main() -> str:
    return render_html(mark(Base()))
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_reference_field_failure_reports_the_assignment_line(tmp_path):
    result = LLVM().run_source('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, ref
class Panel(CustomElement):
    output: Element
def main() -> int:
    panel = Panel()
    child = ref(div({"id": "taken"}))
    panel.output = child
    return 0
''', filename="reference_failure.py", directory=tmp_path)
    assert result.returncode < 0
    assert result.stderr == (
        'Traceback (native PyJS):\n'
        '  File "reference_failure.py", line 9, in main\n'
        'ValueError: element ids are used for hydration and should not be set\n'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_reference_assignment_orders_operands_and_precedes_property_setter(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, ref
from pyjs.web.ssr import render_html

class Panel(CustomElement):
    def __init__(self, events: list[str]):
        super().__init__()
        self.events = events
        self.saved = [div("old")]
    @property
    def output(self) -> Element:
        return self.saved[0]
    @output.setter
    def output(self, value: Element) -> None:
        self.events.append("setter:" + str(value.getAttribute("id")))
        gc_collect()
        if value.hasAttribute("reject"):
            raise ValueError("setter failed")
        self.saved[0] = value

def child(events: list[str], fail: bool) -> Element:
    events.append("rhs")
    if fail:
        raise ValueError("rhs failed")
    return ref(div("new"))

def owner(panel: Panel) -> Panel:
    panel.events.append("receiver")
    panel.setAttribute("data-self-id", "updated")
    gc_collect()
    return panel

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    panel = Panel(events)
    try:
        owner(panel).output = child(events, True)
    except ValueError:
        events.append("caught rhs")
    owner(panel).output = child(events, False)
    before = panel.output
    rejected = ref(div({"reject": ""}, "rejected"))
    try:
        panel.output = rejected
    except ValueError:
        assert panel.output is before
        events.append("caught setter:" + str(rejected.getAttribute("id")))
    return repr(events) + render_html(panel.output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
    assert result.native.stdout == (
        "['rhs', 'caught rhs', 'rhs', 'receiver', 'setter:updated-output', "
        "'setter:updated-output', 'caught setter:updated-output']"
        '<div id="updated-output">new</div>'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_reference_marker_follows_custom_and_optional_union_dom_views(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, ref
from pyjs.web.ssr import render_html

class Child(CustomElement):
    pass
class First(CustomElement):
    output: Element | None
class Second(CustomElement):
    def __init__(self):
        super().__init__()
        self.padding = 42
        self.output: Element | None = None
class Ordinary:
    def __init__(self, value: Element):
        self.value = value

def mark(value: Child | str | None) -> Child | str | None:
    return ref(value)
def assign(owner: First | Second, value: Element | None) -> None:
    owner.output = value
def clear_identity(owner: Element) -> None:
    owner.removeAttribute("data-self-id")
def attach(owner: Element, child: Element) -> str:
    owner.append(child)
    return render_html(owner)

def main() -> str:
    owners: list[First | Second] = [First(), Second()]
    results: list[str] = []
    for owner in owners:
        assign(owner, None)
        child = Child()
        assert mark(child) is child
        ordinary = Ordinary(child)
        assert ordinary.value.getAttribute("id") is None
        gc_collect()
        clear_identity(owner)
        assign(owner, ordinary.value)
        results.append(attach(owner, child))
    assert mark(None) is None
    assert mark("text") == "text"
    return repr(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
    assert "None-output" in result.native.stdout


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("proxy", [False, True])
def test_reference_allocation_failure_keeps_id_and_field_unpublished(tmp_path, optimize, proxy):
    source = transpile_llvm('''
from pyjs.web.domx import CustomElement, ProxyElement, div, ref
from tests.native.allocation_support import arm

class Box(ProxyElement):
    def __init__(self, text: str):
        self.element = div(text)

class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.output = CHILD("old")

def main() -> int:
    failures = 0
    for point in range(1, 30):
        panel = Panel()
        original = panel.output
        child = ref(CHILD("new"))
        failed = False
        arm(point)
        try:
            panel.output = child
        except MemoryError:
            arm(0)
            failed = True
        arm(0)
        if failed:
            failures += 1
            assert panel.output is original
            assert child.getAttribute("id") is None
            panel.output = child
        assert panel.output is child
        assert child.getAttribute("id") is not None
    assert failures > 0
    assert failures < 29
    return 0
'''.replace("CHILD", "Box" if proxy else "div"))
    result = run_allocation_case(source, tmp_path, managed=False, optimize=optimize,
                                 only=("pyjs.arena.try.alloc",))
    assert result.stdout == result.stderr == b""
