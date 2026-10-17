import sys

import pytest

from pyjs.analysis.analyzer import analyze_module, release_compilation
from pyjs.analysis.source import create_module
from pyjs.javascript.source import compile_source
from pyjs.javascript.transpiler import BundleTarget, bundle_targets_with_source_maps


def test_render_bound_getattr_does_not_publish_client_dependencies():
    module = create_module('''
from pyjs import js
from pyjs.web.domx import tw
@js
class Base:
    def styles(self) -> str:
        return 'base'
@js
class Child(Base):
    def styles(self) -> str:
        tw('flex')
        return 'child'
@js
def read(value: Base) -> str:
    return getattr(value, 'styles', None)()
@js
def main() -> str:
    return read(Child())
''', filename="render_bound_getattr.py")
    try:
        entry, classes = analyze_module(module, render_primary=True)
        try:
            method = entry.container.search("Child").find("styles")
            assert classes == {"flex"}
            assert entry in method.render_visited
            assert entry not in method.visited
            assert not entry.virtual_receiver_dependencies
        finally:
            release_compilation(entry)
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("render_primary", [False, True], ids=["client", "render"])
@pytest.mark.parametrize("call", [
    'tw("flex\\tgap-2\\nblock")',
    'styles("flex\\tgap-2\\nblock")',
    'styles(classes="flex\\tgap-2\\nblock")',
    'tw(classes="flex\\tgap-2\\nblock")',
])
def test_literal_tailwind_extraction_resolves_the_function(call, render_primary):
    module = create_module(f'''
from pyjs.web.domx import tw, tw as styles

def main() -> dict[str, str]:
    return {call}
''', filename="tailwind_extraction.py")
    try:
        entry, classes = analyze_module(module, render_primary=render_primary)
        try:
            assert classes == {"flex", "gap-2", "block"}
        finally:
            release_compilation(entry)
    finally:
        sys.modules.pop(module.__name__)


def test_render_receiver_css_does_not_ship_its_creation_helper():
    module = create_module('''
from pyjs import js
from pyjs.web.domx import tw

@js
def make() -> dict[str, str]:
    return tw("flex")

@js
def main() -> int:
    return len(make())
''', filename="tailwind_render_bundle.py")
    try:
        bundles, css = bundle_targets_with_source_maps((BundleTarget("styles", module.main),))
        assert ".flex" in css
        # The module-loader scaffold remains even for a render-only bundle;
        # inspect the application definitions, not that unrelated boilerplate.
        javascript = bundles["styles"].javascript
        assert "function make()" not in javascript
        assert "function main()" not in javascript
        assert "function tw(" not in javascript
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("render_primary", [False, True], ids=["client", "render"])
@pytest.mark.parametrize("argument", ["dynamic", "label()"])
def test_dynamic_and_unrelated_tw_calls_do_not_extract_css(render_primary, argument):
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import tw as styles

@js
def tw(value: int) -> int:
    return value + 1

@js
def label() -> str:
    return "runtime-" + str(tw(2))

@js
def unused() -> dict[str, str]:
    return styles("unreachable")

def main() -> dict[str, str]:
    dynamic = label()
    return styles(classes={argument})
''', filename="tailwind_dynamic.py")
    try:
        entry, classes = analyze_module(module, render_primary=render_primary)
        try:
            assert classes == set()
            assert module.main() == {"class": "runtime-3"}
        finally:
            release_compilation(entry)
    finally:
        sys.modules.pop(module.__name__)


def test_dynamic_tw_argument_is_preserved_in_javascript():
    with compile_source('''
from pyjs import js
from pyjs.web.domx import tw

@js
def label() -> str:
    return "dynamic"

def main() -> dict[str, str]:
    return tw(classes=label())
''') as result:
        assert result.sources[result.entry_point.container.name] == '''\
import { tw } from './pyjs.web.domx.js';

export function label() {
    return 'dynamic';
}

export function main() {
    return tw(label());
}'''
        assert result.entry_point.tailwind_classes == set()


@pytest.mark.parametrize("render_primary", [False, True], ids=["client", "render"])
@pytest.mark.parametrize("expression", [
    'len(tw("flex gap-2"))',
    'tw("flex gap-2").get("class", "")',
    'make().get("class", "")',
    'Styles().count()',
])
def test_tailwind_in_call_receivers_is_reachable(expression, render_primary):
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import tw

@js
def make() -> dict[str, str]:
    return tw("flex gap-2")

@js
class Styles:
    def __init__(self):
        self.attrs = tw("flex gap-2")

    def count(self) -> int:
        return len(self.attrs)

def main():
    return {expression}
''', filename="tailwind_receiver.py")
    try:
        entry, classes = analyze_module(module, render_primary=render_primary)
        try:
            assert classes == {"flex", "gap-2"}
            if expression.startswith("make"):
                # Finding the CSS alone is insufficient: the helper belongs
                # to render reachability even though it is not a JS entry.
                assert entry.container.search("make") in entry.compilation_objects
            if expression.startswith("Styles"):
                assert entry.container.search("Styles").find("__init__") in entry.compilation_objects
        finally:
            release_compilation(entry)
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("expression", [
    'Box().styles', 'len(Box().styles)', 'Box().styles.get("class", "")',
    'Child().styles.get("class", "")',
])
def test_render_property_getters_retain_css_but_not_client_code(expression):
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import tw

@js
class Box:
    @property
    def styles(self) -> dict[str, str]:
        return tw("flex")

@js
class Child(Box):
    pass

@js
def main():
    return {expression}
''', filename="tailwind_property.py")
    try:
        entry, classes = analyze_module(module, render_primary=True)
        try:
            getter = entry.container.search("Box").find("styles")
            assert classes == {"flex"}
            assert getter in entry.compilation_objects
            assert entry not in getter.visited
        finally:
            release_compilation(entry)
        bundles, css = bundle_targets_with_source_maps((BundleTarget("property", module.main),))
        assert ".flex" in css
        # Only the loader scaffold belongs in this render-only bundle.
        assert "class Box" not in bundles["property"].javascript
        assert "function tw(" not in bundles["property"].javascript
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("expression, classes", [
    ('get_fn()()', {"flex"}),
    ('(make if True else other)()', {"flex", "grid"}),
    ('[make][0]()', {"flex"}),
])
def test_render_function_valued_callees(expression, classes):
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import tw

@js
def make() -> dict[str, str]:
    return tw("flex")

@js
def other() -> dict[str, str]:
    return tw("grid")

@js
def get_fn():
    return make

@js
def main():
    return {expression}
''', filename="tailwind_callable.py")
    try:
        entry, collected = analyze_module(module, render_primary=True)
        try:
            assert collected == classes
            function = entry.container.search("make")
            assert function in entry.compilation_objects
            assert entry not in function.visited
        finally:
            release_compilation(entry)
        bundles, css = bundle_targets_with_source_maps((BundleTarget("callable", module.main),))
        assert all("." + name in css for name in classes)
        assert "function make(" not in bundles["callable"].javascript
        assert "function get_fn(" not in bundles["callable"].javascript
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("expression, constructed", [
    ("Card.kind()", False), ("Card.class_kind()", False),
    ("Card().kind()", True), ("Card.make().kind()", True),
])
def test_render_static_methods_do_not_imply_construction(expression, constructed):
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import CustomElement, div, ref, tw
from pyjs.web.events import Event

@js
class Card(CustomElement):
    def __init__(self):
        super().__init__()
        self.button = ref(div(tw("flex")))
        self.addEventListener("click", self.clicked)

    def clicked(self, event: Event):
        print("clicked")

    @staticmethod
    def kind() -> str:
        return "card"

    @classmethod
    def class_kind(cls) -> str:
        return "card"

    @staticmethod
    def make() -> "Card":
        return Card()

@js
def main() -> str:
    return {expression}
''', filename="tailwind_static.py")
    try:
        bundles, css = bundle_targets_with_source_maps((BundleTarget("static", module.main),))
        javascript = bundles["static"].javascript
        assert (".flex" in css) == constructed
        assert ("class Card" in javascript) == constructed
        assert ("_hydrate()" in javascript) == constructed
        assert "\n    _create(" not in javascript
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("construct_first", [False, True])
def test_render_virtual_accessors_follow_reached_classes_and_release(construct_first):
    body = 'item = Child()\n    return read(item)' if construct_first else 'return read(Child())'
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import tw

@js
class Box:
    @property
    def styles(self) -> dict[str, str]:
        return tw("flex")

    @styles.setter
    def styles(self, value: dict[str, str]) -> None:
        tw("block")

@js
class Child(Box):
    @property
    def styles(self) -> dict[str, str]:
        return tw("grid")

    @styles.setter
    def styles(self, value: dict[str, str]) -> None:
        tw("inline")

@js
class Unused(Box):
    @property
    def styles(self) -> dict[str, str]:
        return tw("hidden")

@js
def read(value: Box) -> dict[str, str]:
    value.styles = {{"class": "example"}}
    return value.styles

@js
def main():
    {body}

@js
def plain():
    return read(Box())
''', filename="tailwind_virtual.py")
    try:
        for function, expected in (
            (module.main, {"flex", "grid", "block", "inline"}),
            (module.plain, {"flex", "block"}),
        ):
            entry, classes = analyze_module(module, entry_point=function, render_primary=True)
            try:
                assert classes == expected
                assert all(entry not in obj.visited for obj in entry.compilation_objects)
                assert entry.render_classes
                assert entry.render_virtual_dependencies
            finally:
                release_compilation(entry)
            assert not entry.render_virtual_dependencies
            assert not entry.render_classes
    finally:
        sys.modules.pop(module.__name__)


def test_render_union_method_dependencies_stay_server_only():
    module = create_module('''
from pyjs import js
from pyjs.web.domx import tw

@js
class Left:
    def styles(self) -> dict[str, str]:
        return tw("flex")

@js
class Right:
    def styles(self) -> dict[str, str]:
        return tw("grid")

@js
def render(value: Left | Right) -> dict[str, str]:
    return value.styles()

@js
def main():
    render(Left())
    return render(Right())
''', filename="tailwind_union.py")
    try:
        entry, classes = analyze_module(module, render_primary=True)
        try:
            assert classes == {"flex", "grid"}
            for name in ("Left", "Right"):
                method = entry.container.search(name).find("styles")
                assert method in entry.compilation_objects
                assert entry not in method.visited
        finally:
            release_compilation(entry)
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("render_first", [False, True])
def test_client_runtime_protocols_do_not_retain_render_only_classes(render_first):
    body = ('box = Box()\n    card = Card()' if render_first
            else 'card = Card()\n    box = Box()')
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import CustomElement
from pyjs.web.events import Event

@js
def server_label() -> str:
    return "server-only-marker"

@js
class Box:
    def __len__(self) -> int:
        return len(server_label())

@js
class Card(CustomElement):
    def __init__(self):
        super().__init__()
        self.addEventListener("click", self.clicked)

    def clicked(self, event: Event):
        print(list(map(len, [[1], [2, 3]])))

@js
def main():
    {body}
    return card
''', filename="tailwind_render_protocol.py")
    try:
        bundles, _ = bundle_targets_with_source_maps((BundleTarget("page", module.main),))
        javascript = bundles["page"].javascript
        # Hydration/runtime scaffolding is substantial; check the definitions
        # crossing the client/server boundary rather than snapshotting it all.
        assert "class Card" in javascript
        assert "clicked(" in javascript
        assert "class Box" not in javascript
        assert "server_label" not in javascript
        assert "server-only-marker" not in javascript
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("property_access", [False, True], ids=["method", "getter"])
@pytest.mark.parametrize("client_discovery", ["initialize", "base"])
def test_render_overrides_survive_prior_client_class_discovery(property_access, client_discovery):
    decorator = "@property" if property_access else ""
    access = "value.styles" if property_access else "value.styles()"
    base = "CustomElement" if client_discovery == "base" else "object"
    parent = "Child" if client_discovery == "base" else "CustomElement"
    initialize = "pass" if client_discovery == "base" else "Child()"
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import CustomElement, tw

@js
class Base({base}):
    {decorator}
    def styles(self) -> dict[str, str]:
        return tw("flex")

@js
class Child(Base):
    {decorator}
    def styles(self) -> dict[str, str]:
        return tw("grid")

@js
class Card({parent}):
    def initialize(self):
        {initialize}

    {decorator}
    def styles(self) -> dict[str, str]:
        return tw("block")

@js
def read(value: Base) -> dict[str, str]:
    return {access}

@js
def main():
    read(Base())
    Card()
    return read(Child())
''', filename="tailwind_mixed_discovery.py")
    try:
        assert module.main() == {"class": "grid"}
        entry, classes = analyze_module(module, render_primary=True)
        try:
            expected = {"flex", "grid", "block"} if client_discovery == "base" else {"flex", "grid"}
            assert classes == expected
            child = entry.container.search("Child")
            method = child.find("styles")
            assert child in entry.render_classes
            assert entry in child.visited
            assert entry in method.render_visited
            assert entry not in method.visited
        finally:
            release_compilation(entry)
        assert not entry.render_classes
        bundles, css = bundle_targets_with_source_maps((BundleTarget("page", module.main),))
        assert ".flex" in css
        assert ".grid" in css
        assert (".block" in css) == (client_discovery == "base")
        # The hydrated classes remain, but server-only accessors do not.
        assert "class Card" in bundles["page"].javascript
        assert "styles()" not in bundles["page"].javascript
    finally:
        sys.modules.pop(module.__name__)


@pytest.mark.parametrize("body, expected, result", [
    ("return value.style", {"flex", "grid"}, "right"),
    ('value.style = "new"\n    return 0', {"block", "inline"}, 0),
], ids=["getter", "setter"])
def test_render_union_properties(body, expected, result):
    module = create_module(f'''
from pyjs import js
from pyjs.web.domx import tw

@js
class Left:
    @property
    def style(self) -> str:
        tw("flex")
        return "left"

    @style.setter
    def style(self, value: str) -> None:
        tw("block")

@js
class Right:
    @property
    def style(self) -> str:
        tw("grid")
        return "right"

    @style.setter
    def style(self, value: str) -> None:
        tw("inline")

@js
def read(value: Left | Right):
    {body}

@js
def main():
    read(Left())
    return read(Right())
''', filename="tailwind_union_property.py")
    try:
        assert module.main() == result
        entry, classes = analyze_module(module, render_primary=True)
        try:
            assert classes == expected
            assert all(entry not in obj.visited for obj in entry.compilation_objects)
        finally:
            release_compilation(entry)
        bundles, css = bundle_targets_with_source_maps((BundleTarget("page", module.main),))
        for name in expected:
            assert f".{name} {{" in css
        assert "class Left" not in bundles["page"].javascript
        assert "class Right" not in bundles["page"].javascript
    finally:
        sys.modules.pop(module.__name__)
