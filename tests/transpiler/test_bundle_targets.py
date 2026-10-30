import pytest

from pyjs.analysis.diagnostics import CompilationError, format_compilation_error
from pyjs.analysis.source import create_module
from pyjs.javascript.transpiler import (
    BundleTarget,
    StandaloneBundleTarget,
    bundle_standalone_with_source_maps,
    bundle_targets_with_source_maps,
    bundle_with_source_map,
)


def custom_element_class(source: str, class_name: str, tag_name: str) -> str:
    start = source.index(f"class {class_name} ")
    end = source.index(f"customElements.define('{tag_name}'", start)
    return source[start:end]


def test_standalone_bundles_share_analysis_without_sharing_output():
    module = create_module(
        """
from pyjs import js

@js
def shared_helper() -> str:
    return "shared"

@js.inline("{shared_helper}()", shared_helper=shared_helper)
def shared_inline() -> str: ...

@js
class Formatter:
    def first(self) -> str:
        return "first"

    def second(self) -> str:
        return "second"

@js
def first_helper() -> str:
    return Formatter().first()

@js
def second_helper() -> str:
    return Formatter().second()

@js
def first():
    print(first_helper())
    print(shared_helper())

@js
def first_hydration():
    print("hydrate first")

@js
def second():
    print(second_helper())
    print(shared_inline())
""".lstrip(),
        "standalone.py",
        "standalone",
    )
    expected_first = bundle_with_source_map(
        module.first,
        additional_entry_points=(module.first_hydration,),
        filename="first.js",
    )
    expected_second = bundle_with_source_map(
        module.second,
        filename="second.js",
    )

    generated = bundle_standalone_with_source_maps(
        (
            StandaloneBundleTarget(
                "first",
                module.first,
                additional_entry_points=(module.first_hydration,),
            ),
            StandaloneBundleTarget("second", module.second),
        )
    )

    for name, expected in (
        ("first", expected_first),
        ("second", expected_second),
    ):
        actual_source, actual_css = generated[name]
        expected_source, expected_css = expected
        assert actual_source.javascript == expected_source.javascript
        assert actual_source.source_map.to_json() == expected_source.source_map.to_json()
        assert actual_css == expected_css


def test_bundle_targets_place_dependencies_at_their_lowest_common_ancestor():
    module = create_module(
        """
from pyjs import js
from pyjs.web.domx import CustomElement

@js
def shared():
    print("shared")

@js
def public_only():
    print("public")

@js
def account_only():
    print("account")

@js
class SharedElement(CustomElement):
    def initialize(self):
        shared()

@js
class PublicElement(CustomElement):
    def initialize(self):
        public_only()

@js
class AccountElement(CustomElement):
    def initialize(self):
        account_only()

@js
def application():
    return SharedElement

@js
def public():
    PublicElement()

@js
def catalog():
    PublicElement()
    SharedElement()

@js
def account():
    AccountElement()

@js
def settings():
    AccountElement()
    SharedElement()
""".lstrip(),
        "store.py",
        "store",
    )

    generated, css = bundle_targets_with_source_maps(
        (
            BundleTarget("store", module.application),
            BundleTarget("store.public", module.public, "store"),
            BundleTarget("store.public.catalog", module.catalog, "store.public"),
            BundleTarget("store.account", module.account, "store"),
            BundleTarget("store.account.settings", module.settings, "store.account"),
        )
    )

    assert css == ""
    root = generated["store"].javascript
    public = generated["store.public"].javascript
    catalog = generated["store.public.catalog"].javascript
    account = generated["store.account"].javascript
    settings = generated["store.account.settings"].javascript

    # Custom-element support makes these complete chunks intentionally large;
    # the placement assertions focus on the definitions that distinguish them.
    assert "class SharedElement extends CustomElement" in root
    assert "function shared()" in root
    assert "class PublicElement extends CustomElement" not in root
    assert "class PublicElement extends CustomElement" in public
    assert "function public_only()" in public
    assert "class AccountElement extends CustomElement" not in public
    assert "class AccountElement extends CustomElement" in account
    assert "function account_only()" in account
    assert "class PublicElement extends CustomElement" not in catalog
    assert "class AccountElement extends CustomElement" not in settings


def test_child_bundle_imports_and_reexports_its_parent_runtime():
    module = create_module(
        """
from pyjs import js

@js
def application():
    print("application")

@js
def page_helper():
    print("page")

@js
def page():
    page_helper()
""".lstrip(),
        "example.py",
        "example",
    )

    generated, _css = bundle_targets_with_source_maps(
        (
            BundleTarget("example", module.application),
            BundleTarget("example.page", module.page, "example"),
        ),
        filename_suffix=".mjs",
    )

    assert generated["example.page"].javascript == (
        "import { define, importModule } from './example.mjs';\n"
        "export { define, importModule };\n"
    )
    assert generated["example.page"].source_map.file == "example.page.mjs"


def test_server_rendered_element_emits_hydration_without_creation_helpers():
    module = create_module(
        """
from pyjs import js
from pyjs.web.domx import CustomElement, div, ref, tw
from pyjs.web.events import Event

@js
def render_button():
    return div(tw("flex"), "Ready")

@js
def client_ready():
    print("ready")

@js
def shared_label():
    return "Shared"

@js
class SharedStatus(CustomElement):
    def initialize(self):
        print(shared_label())

@js
def dynamic_label():
    return div(shared_label())

@js
class DynamicResult(CustomElement):
    def __init__(self):
        super().__init__()
        self.append(dynamic_label())

@js
class InteractiveCard(CustomElement):
    def __init__(self):
        super().__init__()
        self.button = ref(render_button())
        self.addEventListener("click", self.clicked)

    def clicked(self, event: Event):
        client_ready()
        self.append(DynamicResult())

@js
def application():
    SharedStatus()

@js
def card_page():
    InteractiveCard()
""".lstrip(),
        "cards.py",
        "cards",
    )

    generated, css = bundle_targets_with_source_maps(
        (
            BundleTarget("cards", module.application),
            BundleTarget("cards.page", module.card_page, "cards"),
        )
    )
    page_bundle = generated["cards.page"]
    page = page_bundle.javascript

    assert ".flex" in css
    assert page_bundle.source_map.file == "cards.page.js"
    assert {mapping.source.filename for mapping in page_bundle.source_map.mappings} == {
        "cards.py"
    }
    assert "class InteractiveCard extends CustomElement" in page
    interactive = custom_element_class(
        page,
        "InteractiveCard",
        "interactive-card",
    )
    dynamic = custom_element_class(page, "DynamicResult", "dynamic-result")
    assert "_hydrate()" in interactive
    assert "\n    _create(" not in interactive
    assert "\n    _create(" in dynamic
    assert "function client_ready()" in page
    assert "function render_button()" not in page
    assert "function dynamic_label()" in page
    assert "const {shared_label} = __import_js__('cards');" in page
    assert "const {div" not in page


@pytest.mark.parametrize('client_creation', [False, True])
def test_proxy_hydration_only_retains_creation_when_the_client_constructs_it(client_creation):
    source = '''from pyjs import js
from pyjs.web.domx import CustomElement, ProxyElement, button, ref, tag
from pyjs.web.events import Event
@js
def render_label() -> str:
    return "Server label"
@js
class Control(ProxyElement):
    def __init__(self):
        self.element = button(render_label())
    def listen(self, callback: callable):
        self.element.addEventListener("click", callback)
@js
class Panel(CustomElement):
    def __init__(self):
        super().__init__()
        self.control = ref(Control())
        self.control.listen(self.clicked)
        tag(self, self.control)
    def clicked(self, event: Event):
        self.setAttribute("data-clicked", "true")
@js
def application():
    pass
@js
def page():
    Panel()
'''
    if client_creation:
        source = source.replace('self.setAttribute("data-clicked", "true")', 'tag(self, Control())')
    module = create_module(source, 'controls.py', 'controls')
    generated, _ = bundle_targets_with_source_maps((
        BundleTarget('controls', module.application),
        BundleTarget('controls.page', module.page, 'controls'),
    ))
    page = generated['controls.page'].javascript
    # Whole page bundles include shared DOM machinery; compare the relevant paths.
    assert 'new Control()._hydrate(' in page
    assert ('function render_label()' in page) is client_creation
    assert ('_create()' in page) is client_creation


def test_server_rendered_event_target_rejects_constructor_local_value():
    module = create_module(
        """
from pyjs import js
from pyjs.web.domx import CustomElement, div
from pyjs.web.events import Event

@js
class InteractiveCard(CustomElement):
    def __init__(self):
        super().__init__()
        button = div("Open")
        button.addEventListener("click", self.clicked)
        self.append(button)

    def clicked(self, event: Event):
        pass

@js
def application():
    pass

@js
def card_page():
    InteractiveCard()
""".lstrip(),
        "cards.py",
        "cards",
    )

    with pytest.raises(CompilationError) as caught:
        bundle_targets_with_source_maps(
            (
                BundleTarget("cards", module.application),
                BundleTarget("cards.page", module.card_page, "cards"),
            )
        )
    assert format_compilation_error(caught.value) == (
        '  File "cards.py", line 10\n'
        '    button.addEventListener("click", self.clicked)\n'
        "    ^^^^^^\n"
        "pyjs.CompilationError: Hydrated event targets cannot be "
        "constructor-local values [PYJS2001]\n"
        "help: Store the target as a ref() attribute on self before "
        "registering the event listener.\n"
    )


def test_hydrated_event_target_rejects_constructor_loop_binding():
    module = create_module(
        '''from pyjs import js
from pyjs.web.domx import CustomElement, div, ref, tag
from pyjs.web.events import Event
@js
class Form(CustomElement):
    def __init__(self):
        super().__init__()
        self.first = ref(div())
        self.second = ref(div())
        for target in [self.first, self.second]:
            target.addEventListener("click", self.clicked)
        tag(self, self.first, self.second)
    def clicked(self, event: Event):
        pass
@js
def application():
    pass
@js
def page():
    Form()
''', 'form.py', 'form')
    with pytest.raises(CompilationError, match='constructor-local values'):
        bundle_targets_with_source_maps((BundleTarget('form', module.application),
                                         BundleTarget('form.page', module.page, 'form')))
