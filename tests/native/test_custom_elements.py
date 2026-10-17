"""Custom application instances and opaque DOM pointers must not share layouts."""

import sys
import tempfile
from textwrap import dedent

import pytest

from pyjs.analysis.source import create_module
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html
from tests.native.model_inputs_fixtures import WidgetRow


@pytest.fixture(autouse=True)
def element_counter():
    counter = CustomElement.CUSTOM_ELEMENT_COUNTER
    CustomElement.CUSTOM_ELEMENT_COUNTER = 0
    yield
    CustomElement.CUSTOM_ELEMENT_COUNTER = counter


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("collect", [False, True])
def test_host_models_render_public_form_widgets_across_calls(tmp_path, monkeypatch, optimize, direct, collect):
    source = dedent('''
        from tests.native.model_inputs_fixtures import WidgetRow
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.web.domx import div, input, ref, tw
        from pyjs.web.events import Event
        from pyjs.web.html import HTMLInputElement
        from pyjs.web.ssr import render_html, write_html_fd
        from pyjs.web.ui import Widget
        from pyjs.web.ui.alert import Alert, AlertDescription, AlertTitle
        from pyjs.web.ui.badge import Badge
        class Catalog(Widget):
            search: HTMLInputElement
            def __init__(self, values: list[WidgetRow]):
                super().__init__()
                self.search = ref(input({"value": "initial"}))
                self.search.value = "browser-only"
                self.search.addEventListener("input", self.update)
                self.add(self.search, *[
                    div(tw("row"), Badge(row.name), Alert(
                        AlertTitle("Changed" if row.changed else "Default"),
                        AlertDescription(row.description))) for row in values
                ])
            def update(self, event: Event) -> None:
                raise RuntimeError("browser callback ran during SSR")
    ''')
    arguments = "values: list[WidgetRow], descriptor: int" if direct else "values: list[WidgetRow]"
    result = "write_html_fd(catalog, descriptor)" if direct else "render_html(catalog)"
    source += f"\ndef render({arguments}) -> {'int' if direct else 'str'}:\n"
    if collect:
        source += "    gc_set_threshold(1, byte_limit=128)\n"
    source += "    catalog = Catalog(values)\n"
    if collect:
        source += "    gc_collect()\n"
    source += f"    return {result}\n"
    module_name = "_native_public_widgets_expected"
    monkeypatch.setitem(sys.modules, module_name, None)
    module = create_module(source, module_name=module_name)
    values = [WidgetRow(name=f"setting_{index}", description="café <value> & details " * 20,
                        changed=index % 2 == 0) for index in range(12)]
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize, direct=direct)
    try:
        # Exact host models require promotion even without explicit GC calls.
        assert library.managed
        for batch in (values, values[:1], [], values):
            CustomElement.CUSTOM_ELEMENT_COUNTER = 0
            assert library.render(batch) == render_html(module.Catalog(batch))
        with pytest.raises(TypeError, match=r"^values\[0\]\.name must be str, not int$"):
            library.render([WidgetRow.model_construct(name=1, description="bad", changed=False)])
        CustomElement.CUSTOM_ELEMENT_COUNTER = 0
        assert library.render(values) == render_html(module.Catalog(values))
    finally:
        library.close()


@pytest.mark.parametrize("optimization", [0, 2])
def test_custom_fields_inheritance_and_virtual_methods(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Greeting(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def label(self) -> str:
        return self.name

    def populate(self) -> None:
        tag(self, div(self.display))

    @property
    def display(self) -> str:
        return self.label()

class Counted(Greeting):
    def __init__(self, name: str, count: int):
        super().__init__(name)
        self.count = count

    def label(self) -> str:
        return self.name + ":" + str(self.count)

def fill(value: Greeting) -> Greeting:
    value.name = value.name + "!"
    value.populate()
    return value

def main() -> str:
    first = Counted("Ada", 3)
    first.count += 1
    return render_html(div(fill(first), fill(Greeting("Grace"))))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == (
        '<div><pyjs-counted data-self-id="ce1"><div>Ada!:4</div></pyjs-counted>'
        '<pyjs-greeting data-self-id="ce2"><div>Grace!</div></pyjs-greeting></div>'
    )


@pytest.mark.parametrize("optimization", [0, 2])
def test_custom_element_dom_boundaries(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        tag(self, name)

class Holder:
    def __init__(self, element: Element):
        self.element = element

def as_element(value: Item) -> Element:
    return value

def optional(value: Item | None) -> Element | None:
    return value

def render(value: Element) -> str:
    return render_html(value)

def erased_identity(value: object, element: Element) -> bool:
    return value is element

def element_kind(value: Item | str) -> bool:
    return isinstance(value, Element)

def main() -> str:
    first = Item("Ada")
    second = Item("Grace")
    elements: list[Element] = [first]
    elements.append(second)
    holder = Holder(first)
    nullable = optional(first)
    assert element_kind(first)
    assert not element_kind("text")
    assert first is as_element(first)
    assert first == as_element(first)
    assert as_element(first) == first
    assert as_element(second) != first
    assert first in elements
    assert holder.element is first
    assert elements[0] is first
    assert nullable is first
    assert optional(None) is None
    assert first is not second
    assert erased_identity(first, as_element(first))
    assert not erased_identity(second, as_element(first))
    assert not erased_identity(0, as_element(first))
    concrete: list[Item] = [first, second]
    return render(first) + render_html(div(*elements)) + render_html(div(*concrete))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_custom_identity_is_assigned_when_base_initializer_runs(tmp_path):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Leaf(CustomElement):
    pass

class Parent(CustomElement):
    def __init__(self):
        child = Leaf()
        super().__init__()
        tag(self, child)

def main() -> str:
    return render_html(div(Parent(), Leaf()))
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == (
        '<div><pyjs-parent data-self-id="ce2"><pyjs-leaf data-self-id="ce1">'
        '</pyjs-leaf></pyjs-parent><pyjs-leaf data-self-id="ce3"></pyjs-leaf></div>'
    )


@pytest.mark.parametrize("optimization", [0, 2])
def test_custom_elements_in_union_collections(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        tag(self, name)

def union(value: Item | str) -> Element | str:
    return value

def main() -> str:
    gc_set_threshold(1)
    first = Item("Ada")
    values: list[Element | str] = [first, "<text>"]
    assert values[0] is first
    assert values[1] is not first
    values.append(Item("Grace"))
    values.insert(1, Item("Linus"))
    values[0] = Item("Guido")
    lookup: dict[str, Element | str] = {"first": first}
    lookup["second"] = Item("Margaret")
    lookup.setdefault("third", Item("Hedy"))
    pair: tuple[Element | str, Element | str] = (first, "tuple")
    concrete: list[Item | str] = [first, "raw"]
    assert concrete[0] is pair[0] is first
    gc_collect()
    assert first.name == "Ada"
    return render_html(div(div(*values), div(*lookup.values()),
                           div(pair[0], pair[1]), div(*concrete),
                           div(union(first), union("text"))))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_reached_widget_base_keeps_application_methods(tmp_path):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import div, tw
from pyjs.web.ui import Widget
from pyjs.web.ssr import render_html

class Panel(Widget):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.add(tw("panel"), div(self.name), "<tail>")

def main() -> str:
    return render_html(Panel("Ada"))
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == '<pyjs-panel data-self-id="ce1" class="panel"><div>Ada</div>&lt;tail&gt;</pyjs-panel>'


@pytest.mark.parametrize("optimization", [0, 2])
def test_constructor_failure_gc_and_reinitialization(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Panel(CustomElement):
    def __init__(self, name: str, fail: bool = False):
        self.name = name
        tag(self, "discarded-before-super")
        super().__init__()
        gc_collect()
        if fail:
            raise ValueError(self.name)
        tag(self, div(self.name))

    def reset(self) -> None:
        super().__init__()
        gc_collect()
        tag(self, self.name + " reset")

def main() -> str:
    gc_set_threshold(1)
    retained: list[Panel] = []
    for index in range(10):
        try:
            Panel("failure:" + str(index), True)
        except ValueError:
            gc_collect()
        retained.append(Panel("success:" + str(index)))
    retained[0].reset()
    gc_collect()
    return render_html(div(*retained))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert 'data-self-id="ce21">success:0 reset' in comparison.native.stdout
    assert "discarded" not in comparison.native.stdout


def test_first_class_tw_is_an_independent_mutable_dictionary(tmp_path):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import div, tw
from pyjs.web.ssr import render_html

def attributes() -> dict[str, str]:
    return tw("name-3")

def main() -> str:
    gc_set_threshold(1)
    original = attributes()
    copied = original.copy()
    original["data-value"] = "<&>"
    original["class"] = "updated"
    gc_collect()
    assert copied == {"class": "name-3"}
    return render_html(div(original, div(copied)))
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
    assert comparison.native.stdout == '<div class="updated" data-value="&lt;&amp;&gt;"><div class="name-3"></div></div>'


def test_opaque_state_mutation_keeps_an_explicit_callback_boundary():
    with pytest.raises(LLVMUnsupported, match="observed-attribute callbacks"):
        transpile_llvm('''
from pyjs import effect, state
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

class Panel(CustomElement):
    title = state("default")
    @effect(title)
    def changed(self):
        pass

def change(value: Element) -> None:
    value.setAttribute("title", "changed")

def main() -> str:
    panel = Panel()
    change(panel)
    return render_html(panel)
''')


@pytest.mark.parametrize("annotation", ["Element", "Element | str"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_opaque_dom_type_queries_recover_custom_classes(tmp_path, annotation, optimize):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div

class Panel(CustomElement):
    pass

def query(value: {annotation}) -> bool:
    return isinstance(value, Panel)

def main() -> int:
    assert not query(div())
    return int(query(Panel()))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_host_custom_elements_are_not_marshaled_as_plain_records():
    with pytest.raises(LLVMUnsupported, match="constructed in compiled code"):
        transpile_llvm('''
from pyjs.web.domx import CustomElement
from pyjs.web.ssr import render_html

class Panel(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

def main(value: Panel) -> str:
    return render_html(value)
''', target="library")


@pytest.mark.parametrize("optimization", [0, 2])
def test_custom_union_roots_and_generator_upcasts(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from typing import Iterator
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html, render_document

class First(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        tag(self, self.name)

class Second(CustomElement):
    def __init__(self, count: int):
        super().__init__()
        self.count = count
        tag(self, str(self.count))

def choose(flag: bool) -> First | Second:
    return First("union") if flag else Second(7)

def as_element(value: Second) -> Element:
    return value

def rows() -> Iterator[Element]:
    for index in range(3):
        gc_collect()
        yield as_element(Second(index))

def main() -> str:
    gc_set_threshold(1)
    return render_html(choose(True)) + render_document(choose(False)) + render_html(div(*rows()))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("name", ["Element", "Attribute"])
def test_application_names_do_not_select_private_dom_layouts(name):
    with pytest.raises(LLVMUnsupported, match="native argument .* is not supported"):
        transpile_llvm(f'''
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

class {name}:
    def __init__(self):
        self.payload = 1

def main() -> str:
    return render_html(div({name}()))
''')


def test_widget_base_requires_a_concrete_custom_tag():
    with pytest.raises(LLVMUnsupported, match="construction requires a concrete tag"):
        transpile_llvm('''
from pyjs.web.ui import Widget
from pyjs.web.ssr import render_html

def main() -> str:
    return render_html(Widget())
''')


@pytest.mark.parametrize("direct", [False, True])
def test_library_custom_roots_reset_ids_between_requests(tmp_path, direct):
    signature = "name: str, descriptor: int) -> int" if direct else "name: str) -> str"
    render = "write_html_fd(root, descriptor)" if direct else "render_html(root)"
    library = LLVM().compile_library(f'''
from pyjs.native import gc_collect, gc_set_threshold
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html, write_html_fd

class Panel(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        gc_collect()
        tag(self, self.name)

def main({signature}:
    gc_set_threshold(1)
    root = Panel(name)
    gc_collect()
    return {render}
''', tmp_path, direct=direct)
    for name in ("Ada", "Grace", "<&>"):
        with tempfile.TemporaryFile() as destination:
            assert library.render_to_fd(destination.fileno(), name) == 0
            destination.seek(0)
            escaped = "&lt;&amp;&gt;" if name == "<&>" else name
            assert destination.read() == f'<pyjs-panel data-self-id="ce1">{escaped}</pyjs-panel>'.encode()


def test_application_typed_custom_comparison_keeps_callbacks(tmp_path):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def __eq__(self, other: "Item") -> bool:
        return self.name == other.name

def main() -> int:
    first = Item("Ada")
    other = Item("Ada")
    assert first == other
    assert first is not other
    assert first != Item("Grace")
    return 7
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_opaque_custom_comparison_does_not_silently_skip_callbacks():
    with pytest.raises(LLVMUnsupported, match="custom callbacks requires application-typed"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    def __eq__(self, other: object) -> bool:
        return True

def compare(left: Element, right: Item) -> bool:
    return left == right

def main() -> int:
    return int(compare(Item(), Item()))
''')


@pytest.mark.parametrize("method, operator", [("__eq__", "=="), ("__ne__", "!=")])
def test_custom_comparison_preserves_disabled_methods(tmp_path, method, operator):
    comparison = LLVM().assert_matches_python(f'''
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    {method} = None

def main() -> int:
    first = Item()
    second = Item()
    try:
        result = first {operator} second
        return int(result)
    except TypeError:
        return 7
''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimization", [0, 2])
def test_assert_narrowing_converts_custom_storage_at_reads(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.name = "Ada"
        tag(self, self.name)

def checked(value: Item) -> str:
    assert isinstance(value, Element)
    return render_html(value)

def checked_optional(value: Item | None) -> str:
    assert isinstance(value, Element)
    return render_html(value)

def checked_union(value: Item | str) -> str:
    if isinstance(value, Element):
        return render_html(value)
    return value

class Holder:
    def __init__(self, value: Item):
        self.item = value

def checked_field(holder: Holder) -> str:
    if isinstance(holder.item, Element):
        return render_html(holder.item)
    return "missing"

def main() -> str:
    first = Item()
    rendered = checked(first) + checked_optional(first) + checked_union(first) + checked_field(Holder(first))
    assert isinstance(first, Element)
    return rendered + render_html(first)
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimization", [0, 2])
def test_erased_custom_and_dom_views_share_identity(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    pass

def opaque(value: Item) -> Element:
    return value

def same(left: object, right: object) -> bool:
    return left is right

def main() -> int:
    first = Item()
    other = Item()
    values: list[object] = [first, opaque(first), other]
    gc_collect()
    assert same(first, opaque(first))
    assert same(opaque(first), first)
    assert values[0] is values[1]
    assert values[1] is not values[2]
    assert not same(first, None)
    assert same(None, None)
    return 7
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_dom_type_queries_recover_custom_classes(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    pass

def opaque(value: Item) -> Element:
    return value

def query(value: object) -> bool:
    return isinstance(value, Item)

def main() -> int:
    return int(query(opaque(Item())))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("imports, query", [
    ("from pyjs.web.html import HTMLDivElement", "HTMLDivElement"),
    ("from pyjs.web.html import HTMLDivElement as Div", "Div"),
    ("from pyjs.web import html", "html.HTMLDivElement"),
    ("from pyjs.web.html import HTMLElement", "HTMLElement"),
])
def test_concrete_dom_type_queries_require_distinct_runtime_types(imports, query):
    with pytest.raises(LLVMUnsupported, match="not concrete DOM interfaces"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import span
{imports}

def query(value: Element | str) -> bool:
    return isinstance(value, {query})

def main() -> int:
    return int(query(span()))
''')


@pytest.mark.parametrize("optimization", [0, 2])
def test_dictionary_get_projects_custom_defaults_and_dom_hits(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, "default")

def main() -> str:
    first = Item()
    lookup: dict[str, Element] = {"hit": div("stored")}
    value = lookup.get("missing", first)
    assert value is first
    assert lookup.get("missing", first) is first
    assert lookup.get("hit", first) is lookup["hit"]
    return render_html(value) + render_html(lookup.get("hit", first)) + render_html(lookup.get("missing", first))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("base_method, override, invoke", [
    ("def run(self) -> Element: return div()",
     "def run(self) -> Item: return Item()", "return render_html(value.run())"),
    ("def run(self, item: Item) -> str: return 'base'",
     "def run(self, item: Element) -> str: return render_html(item)", "return value.run(Item())"),
])
def test_virtual_dom_variance_requires_storage_adapters(base_method, override, invoke):
    with pytest.raises(LLVMUnsupported, match="preserve custom-element versus opaque DOM storage"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html

class Item(CustomElement):
    pass

class Base:
    {base_method}

class Derived(Base):
    {override}

def apply(value: Base) -> str:
    {invoke}

def main() -> str:
    return apply(Base()) + apply(Derived())
''')


@pytest.mark.parametrize("container, literal", [
    ("list[{item}]", "[Item()]"),
    ("dict[str, {item}]", "{'key': Item()}"),
    ("list[list[{item}]]", "[[Item()]]"),
])
@pytest.mark.parametrize("alternative", ["None", "str"])
def test_dom_container_union_views_require_invariant_items(container, literal, alternative):
    actual = container.format(item=f"Item | {alternative}")
    expected = container.format(item=f"Element | {alternative}")
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement

class Item(CustomElement):
    pass

def consume(values: {expected}) -> int:
    return len(values)

def main() -> int:
    values: {actual} = {literal}
    return consume(values)
''')


@pytest.mark.parametrize("boundary", ["return", "field", "override", "alias_mutation"])
def test_optional_dom_container_boundaries_do_not_reinterpret_members(boundary):
    sources = {
        "return": '''
def main() -> list[Element | None]:
    values: list[Item | None] = [Item()]
    return values
''',
        "field": '''
class Holder:
    values: list[Element | None]
    def __init__(self):
        values: list[Item | None] = [Item()]
        self.values = values
def main() -> int:
    return len(Holder().values)
''',
        "override": '''
class Base:
    def values(self) -> list[Element | None]:
        return [div()]
class Derived(Base):
    def values(self) -> list[Item | None]:
        return [Item()]
def consume(value: Base) -> int:
    return len(value.values())
def main() -> int:
    return consume(Base()) + consume(Derived())
''',
        "alias_mutation": '''
def mutate(values: list[Element | None]) -> None:
    values.append(div())
def main() -> str:
    values: list[Item | None] = [Item()]
    mutate(values)
    result = ""
    for value in values:
        if value is not None:
            result += value.name
    return result
''',
    }
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        self.name = "item"
''' + sources[boundary])


@pytest.mark.parametrize("optimization", [0, 2])
def test_optional_dom_values_convert_individually_not_as_container_views(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, "item")

def show(value: Element | None) -> str:
    return render_html(value) if value is not None else "none"

def main() -> str:
    items: list[Item | None] = [Item(), None]
    elements: list[Element | None] = []
    result = ""
    for item in items:
        result += show(item)
        elements.append(item)
    for element in elements:
        result += show(element)
    return result
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("alternative", ["", " | None", " | str"])
@pytest.mark.parametrize("boundary", ["call", "return", "assignment", "override", "list", "tagged"])
def test_generic_dom_views_require_invariant_storage(alternative, boundary):
    actual, expected = f"Box[Item{alternative}]", f"Box[Element{alternative}]"
    sources = {
        "call": f'''
def main() -> int:
    box: {actual} = Box(Item())
    return consume(box)
''',
        "return": f'''
def make() -> {expected}:
    box: {actual} = Box(Item())
    return box
def main() -> int:
    return consume(make())
''',
        "assignment": f'''
def main() -> int:
    box: {actual} = Box(Item())
    view: {expected} = box
    return consume(view)
''',
        "override": f'''
class Base:
    def make(self) -> {expected}:
        return Box(div())
class Derived(Base):
    def make(self) -> {actual}:
        return Box(Item())
def apply(value: Base) -> int:
    return consume(value.make())
def main() -> int:
    return apply(Base()) + apply(Derived())
''',
        "list": f'''
def apply(values: list[{expected}]) -> int:
    return consume(values[0])
def main() -> int:
    values: list[{actual}] = [Box(Item())]
    return apply(values)
''',
        "tagged": f'''
def apply(value: {expected} | str) -> int:
    return 7
def main() -> int:
    box: {actual} = Box(Item())
    return apply(box)
''',
    }
    with pytest.raises(LLVMUnsupported, match="generic object views require matching type arguments"):
        transpile_llvm(f'''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div

class Item(CustomElement):
    pass

class Box[T]:
    def __init__(self, value: T):
        self.value = value

def consume(value: {expected}) -> int:
    return 7
''' + sources[boundary])


@pytest.mark.parametrize("optimization", [0, 2])
def test_generic_dom_construction_converts_fields_without_aliasing(tmp_path, optimization):
    comparison = LLVM().assert_matches_python('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, tag
from pyjs.web.ssr import render_html

class Item(CustomElement):
    def __init__(self):
        super().__init__()
        tag(self, "item")

class Box[T]:
    def __init__(self, value: T):
        self.value = value

class ItemBox(Box[Item]):
    pass

def show(box: Box[Element]) -> str:
    return render_html(box.value)

def show_item(box: Box[Item]) -> str:
    return render_html(box.value)

def main() -> str:
    item = Item()
    concrete: Box[Item] = Box(item)
    view = Box[Element](concrete.value)
    assert view is not concrete
    assert view.value is concrete.value
    return show(view) + show(Box[Element](item)) + render_html(concrete.value) + show_item(ItemBox(item))
''', directory=tmp_path, optimize=optimization, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_inherited_dom_fields_preserve_the_base_storage_view():
    with pytest.raises(LLVMUnsupported, match="stored DOM views require matching wrapper and opaque representations at line 3$"):
        transpile_llvm('''
from pyjs.web.dom import Element
from pyjs.web.domx import CustomElement, div
from pyjs.web.ssr import render_html

class Item(CustomElement):
    pass

class Base:
    def __init__(self):
        self.value: Element = div()

class Derived(Base):
    def __init__(self):
        self.value: Item = Item()

def show(value: Base) -> str:
    return render_html(value.value)

def main() -> str:
    return show(Base()) + show(Derived())
''')
