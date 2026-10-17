import ast

import pytest

from scripts.update_webidl import (
    Argument,
    Definition,
    Member,
    ModuleSpec,
    dependency_cycles,
    module_dependency_graph,
    module_imports,
    order_module_classes,
    order_module_imports,
    place_global_instances,
    python_type,
    render_dictionary,
    render_interface,
    retained_webidl_names,
    selected_definitions,
    source_module_map,
    synchronize,
    validate_module_specs,
)


def class_node(module: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == name
    )


def methods(node: ast.ClassDef, name: str) -> list[ast.FunctionDef]:
    return [
        child for child in node.body if isinstance(child, ast.FunctionDef) and child.name == name
    ]


def test_retained_webidl_names_excludes_python_builtins():
    module = ast.parse(
        """
class DOMException(Exception):
    related: Event
"""
    )
    registry = {
        "DOMException": Definition("interface", "DOMException"),
        "Event": Definition("interface", "Event"),
        "Exception": Definition("interface", "Exception"),
    }

    assert retained_webidl_names(module, registry) == {"Event"}


def test_synchronize_removes_a_webidl_class_shadowing_a_python_builtin():
    existing = ast.parse(
        '''
class Exception:
    """WebIDL source: @webref/idl/wasm-js-api.idl"""
    pass

class DOMException(Exception):
    """WebIDL source: @webref/idl/dom.idl"""
    pass
'''
    )
    generated = ast.parse(
        '''
class DOMException(Exception):
    """WebIDL source: @webref/idl/dom.idl"""
    pass
'''
    )

    result = synchronize(existing, generated)

    assert [
        node.name for node in result.body if isinstance(node, ast.ClassDef)
    ] == ["DOMException"]
    assert ast.unparse(class_node(result, "DOMException").bases[0]) == "Exception"


def test_synchronize_preserves_implemented_and_client_method_signatures():
    existing = ast.parse(
        """
@js.native
class Element:
    @js
    def setAttribute(self, name: str, value: str):
        self.attributes[name] = value

    @setAttribute.client
    def setAttribute(self, name: str, value: str):
        pass
"""
    )
    generated = ast.parse(
        """
@js.native
class Element:
    def setAttribute(self, qualifiedName: str, value: object | str) -> None:
        ...
"""
    )

    result = synchronize(existing, generated)
    server, client = methods(class_node(result, "Element"), "setAttribute")

    assert [argument.arg for argument in server.args.args] == ["self", "name", "value"]
    assert ast.unparse(server.args.args[-1].annotation) == "str"
    assert server.returns is None
    assert isinstance(server.decorator_list[0], ast.Name)
    assert [argument.arg for argument in client.args.args] == ["self", "name", "value"]
    assert ast.unparse(client.args.args[-1].annotation) == "str"
    assert client.returns is None
    assert isinstance(client.decorator_list[0], ast.Attribute)
    assert client.decorator_list[0].attr == "client"


def test_synchronize_preserves_edited_placeholder_methods():
    existing = ast.parse(
        """
@js.native
class Element:
    def lookup(self, name): ...
"""
    )
    generated = ast.parse(
        """
@js.native
class Element:
    def lookup(self, selector: str) -> Element | None: ...
"""
    )

    result = synchronize(existing, generated)
    method = methods(class_node(result, "Element"), "lookup")[0]

    assert [argument.arg for argument in method.args.args] == ["self", "name"]
    assert method.returns is None


def test_synchronize_extends_dictionary_initializers_without_changing_existing_api():
    existing = ast.parse(
        """
@js
class Options:
    def __init__(self, old_name: str = ""):
        self.old_name = old_name
"""
    )
    generated = ast.parse(
        """
@js.dictionary
class Options:
    def __init__(self, currentName: str = ""):
        self.currentName = currentName
"""
    )

    result = synchronize(existing, generated)
    options = class_node(result, "Options")
    initializer = methods(options, "__init__")[0]

    assert ast.unparse(options.decorator_list[0]) == "js.dictionary"
    assert [argument.arg for argument in initializer.args.args] == ["self", "old_name"]
    assert [argument.arg for argument in initializer.args.kwonlyargs] == ["currentName"]
    assert [ast.unparse(statement) for statement in initializer.body] == [
        "self.old_name = old_name",
        "self.currentName = currentName",
    ]


def test_synchronize_preserves_existing_dictionary_field_types():
    existing = ast.parse(
        """
@js
class Options:
    def __init__(self, python_name: object = None):
        self.webName = python_name
"""
    )
    generated = ast.parse(
        """
@js.dictionary
class Options:
    def __init__(self, added: bool = False, webName: str = ""):
        self.added = added
        self.webName = webName
"""
    )

    result = synchronize(existing, generated)
    initializer = methods(class_node(result, "Options"), "__init__")[0]

    assert ast.unparse(initializer.args.args[1].annotation) == "object"
    assert [argument.arg for argument in initializer.args.kwonlyargs] == ["added"]
    assert ast.unparse(initializer.args.kw_defaults[0]) == "False"


def test_render_dictionary_preserves_webidl_omission_and_collection_defaults():
    definition = Definition(
        "dictionary",
        "Options",
        members=[
            Member(
                "field",
                "headers",
                "dict[str, str] | None",
                value="None",
                omit_when_none=True,
            ),
            Member(
                "field",
                "formats",
                "list[str] | None",
                value="None",
                default_factory="[]",
            ),
        ],
    )

    initializer = methods(render_dictionary(definition, {"Options": definition}), "__init__")[
        0
    ]
    source = ast.unparse(initializer)

    assert "if headers is not None:" in source
    assert "self.headers = headers" in source
    assert "if formats is None:" in source
    assert "formats = []" in source
    assert "self.formats = formats" in source


def test_render_dictionary_flattens_inherited_fields_without_runtime_inheritance():
    base = Definition(
        "dictionary",
        "BaseOptions",
        members=[Member("field", "label", "str", value='""')],
    )
    derived = Definition(
        "dictionary",
        "Options",
        base="BaseOptions",
        members=[Member("field", "enabled", "bool", value="False")],
    )

    rendered = render_dictionary(
        derived, {"BaseOptions": base, "Options": derived}
    )
    initializer = methods(rendered, "__init__")[0]

    assert rendered.bases == []
    assert [argument.arg for argument in initializer.args.args] == [
        "self",
        "enabled",
        "label",
    ]


def test_synchronize_dictionary_copies_default_factory_before_new_assignment():
    existing = ast.parse(
        """
@js
class Options:
    def __init__(self, name: str):
        self.name = name
"""
    )
    generated = ast.parse(
        """
@js.dictionary
class Options:
    def __init__(self, name: str, formats: list[str] | None = None):
        self.name = name
        if formats is None:
            formats = []
        self.formats = formats
"""
    )

    result = synchronize(existing, generated)
    initializer = methods(class_node(result, "Options"), "__init__")[0]
    source = ast.unparse(initializer)

    assert source.index("formats = []") < source.index("self.formats = formats")


def test_synchronize_removes_generated_classes_replaced_by_imports():
    existing = ast.parse(
        '''
from pyjs import js

@js.native
class Collection:
    """WebIDL source: @webref/idl/dom.idl"""

    pass
'''
    )
    generated = ast.parse(
        """
from pyjs import js
from pyjs.web.dom import Collection
"""
    )

    result = synchronize(existing, generated)

    assert not any(isinstance(node, ast.ClassDef) for node in result.body)
    assert "from pyjs.web.dom import Collection" in ast.unparse(result)


def test_synchronize_removes_unreferenced_definitions_absent_from_webidl():
    existing = ast.parse(
        '''
from pyjs import js

@js.native
class RemovedAPI:
    """WebIDL source: @webref/idl/removed.idl"""

    pass
'''
    )
    generated = ast.parse("from pyjs import js")

    result = synchronize(existing, generated)

    assert ast.unparse(result) == "from pyjs import js"


def test_synchronize_does_not_remove_arguments_from_an_implemented_method():
    existing = ast.parse(
        """
class DragEvent:
    def __init__(self, type: str, *, bubbles: bool = False, dataTransfer=None):
        self.type = type
        self.dataTransfer = dataTransfer
"""
    )
    generated = ast.parse(
        """
class DragEvent:
    def __init__(self, type: str, *, dataTransfer=None):
        ...
"""
    )

    result = synchronize(existing, generated)
    initializer = methods(class_node(result, "DragEvent"), "__init__")[0]

    assert [argument.arg for argument in initializer.args.kwonlyargs] == [
        "bubbles",
        "dataTransfer",
    ]


def test_synchronize_inserts_generated_subclasses_after_their_base():
    existing = ast.parse(
        """
class Earlier: ...
class Base: ...
class Later: ...
"""
    )
    generated = ast.parse(
        """
class Base: ...
class Derived(Base): ...
class Earlier: ...
class Later: ...
"""
    )

    result = synchronize(existing, generated)
    names = [node.name for node in result.body if isinstance(node, ast.ClassDef)]

    assert names.index("Derived") > names.index("Base")


def test_order_module_classes_moves_existing_base_before_subclass():
    module = ast.parse(
        """
class Derived(Base): ...
sentinel = 1
class Base: ...
"""
    )

    result = order_module_classes(module)

    assert [node.name for node in result.body if isinstance(node, ast.ClassDef)] == [
        "Base",
        "Derived",
    ]
    assert isinstance(result.body[1], ast.Assign)


def test_order_module_imports_moves_late_generated_imports_to_the_top():
    module = ast.parse(
        """
class Element: ...
from pyjs.web.events import Event
"""
    )

    result = order_module_imports(module)

    assert isinstance(result.body[0], ast.ImportFrom)
    assert isinstance(result.body[1], ast.ClassDef)


def test_global_instances_are_reattached_to_their_class_after_synchronization():
    module = ast.parse(
        """
from pyjs import js

class Document: ...

class InjectedLater: ...

document = Document()
js.native(document)
"""
    )

    result = place_global_instances(module, {"Document": ("document",)})
    source = [ast.unparse(node) for node in result.body]

    document_index = source.index("class Document:\n    ...")
    assert source[document_index + 1] == "document = Document()"
    assert source[document_index + 2] == "js.native(document)"
    assert source[document_index + 3] == "class InjectedLater:\n    ..."
    assert ast.unparse(result.body[0]) == "from pyjs import js"


def test_selected_definitions_rejects_globals_without_a_definition():
    registry = {"Document": Definition("interface", "Document", source="dom.idl")}
    spec = ModuleSpec(
        "dom",
        ("dom.idl",),
        global_instances={"Window": ("window",)},
    )

    with pytest.raises(
        ValueError,
        match="dom: generated globals have no selected definition: Window",
    ):
        selected_definitions(registry, spec, {"dom.idl": "dom"})


def test_module_spec_distinguishes_handwritten_global_instances():
    spec = ModuleSpec(
        "dom",
        ("dom.idl",),
        global_instances={"Document": ("document",)},
        handwritten_global_instances={"Storage": ("localStorage",)},
    )

    assert spec.all_global_instances == {
        "Document": ("document",),
        "Storage": ("localStorage",),
    }


def test_source_owned_modules_select_all_definitions_and_filter_foreign_partials():
    registry = {
        "Request": Definition(
            "interface",
            "Request",
            members=[
                Member("attribute", "url", "str", source="fetch.idl"),
                Member("attribute", "privateNetwork", "bool", source="private-network.idl"),
            ],
            source="fetch.idl",
            included_by_browser_policy=True,
        ),
        "Response": Definition(
            "interface",
            "Response",
            source="fetch.idl",
            included_by_browser_policy=True,
        ),
    }
    spec = ModuleSpec("network", ("fetch.idl",))

    definitions = selected_definitions(registry, spec, {"fetch.idl": "network"})

    assert set(definitions) == {"Request", "Response"}
    assert [member.name for member in definitions["Request"].members] == ["url"]


def test_projection_only_exposes_members_contributed_by_the_module_sources():
    registry = {
        "Navigator": Definition(
            "interface",
            "Navigator",
            members=[
                Member("attribute", "language", "str", source="html.idl"),
                Member(
                    "attribute",
                    "serviceWorker",
                    "ServiceWorkerContainer",
                    source="service-workers.idl",
                ),
            ],
            source="html.idl",
            included_by_browser_policy=True,
        )
    }
    spec = ModuleSpec(
        "serviceworker",
        ("service-workers.idl",),
        projections=("Navigator",),
    )

    definitions = selected_definitions(
        registry,
        spec,
        {"html.idl": "html", "service-workers.idl": "serviceworker"},
    )

    assert [member.name for member in definitions["Navigator"].members] == ["serviceWorker"]


def test_history_is_owned_by_dom_with_its_complete_api():
    history = Definition(
        "interface",
        "History",
        members=[
            Member("attribute", "length", "int", source="html.idl"),
            Member("method", "pushState", "None", source="html.idl"),
        ],
        source="html.idl",
        included_by_browser_policy=True,
    )
    registry = {"History": history}

    definitions = selected_definitions(
        registry,
        ModuleSpec("dom", ("dom.idl",)),
        {"dom.idl": "dom", "html.idl": "html"},
    )

    assert [member.name for member in definitions["History"].members] == [
        "length",
        "pushState",
    ]


def test_source_module_map_rejects_duplicate_source_ownership():
    with pytest.raises(ValueError, match="fetch.idl is owned by both first and second"):
        source_module_map(
            (
                ModuleSpec("first", ("fetch.idl",)),
                ModuleSpec("second", ("fetch.idl",)),
            )
        )


def test_module_imports_reuse_javascript_types_instead_of_creating_local_stubs():
    registry = {
        "Request": Definition(
            "interface",
            "Request",
            source="fetch.idl",
            included_by_browser_policy=True,
        )
    }
    spec = ModuleSpec("network", ("fetch.idl",))

    imports = module_imports(
        registry,
        spec,
        {"fetch.idl": "network"},
        {"ArrayBuffer"},
    )

    assert imports["pyjs.javascript"] == ("ArrayBuffer",)
    assert python_type("bigint") == "int"


def test_module_dependency_graph_reports_cycles():
    specs = (
        ModuleSpec("dom", imports={"pyjs.web.events": ("Event",)}),
        ModuleSpec("events", imports={"pyjs.web.dom": ("Window",)}),
    )

    graph = module_dependency_graph(specs)

    assert dependency_cycles(graph) == [("dom", "events", "dom")]


def test_validate_module_specs_keeps_webgpu_as_a_leaf():
    registry = {
        "GPU": Definition(
            "interface",
            "GPU",
            source="webgpu.idl",
            included_by_browser_policy=True,
        )
    }
    specs = (
        ModuleSpec("dom", imports={"pyjs.web.webgpu": ("GPU",)}),
        ModuleSpec("webgpu", ("webgpu.idl",)),
    )

    with pytest.raises(ValueError, match="Large leaf modules must not be dependencies: webgpu"):
        validate_module_specs(registry, specs, {})


def test_render_interface_initializes_attributes_per_instance():
    definition = Definition(
        "interface",
        "Document",
        "Node",
        [
            Member("constant", "DOCUMENT_NODE", "int", value="9"),
            Member("attribute", "adoptedStyleSheets", "list[CSSStyleSheet]"),
        ],
    )

    rendered = render_interface(definition, {"Document": definition})
    initializer = methods(rendered, "__init__")[0]

    assert any(
        isinstance(statement, ast.Assign)
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "DOCUMENT_NODE"
        for statement in rendered.body
    )
    assert not any(
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == "adoptedStyleSheets"
        for statement in rendered.body
    )
    assignment = next(
        statement
        for statement in initializer.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Attribute)
        and statement.target.attr == "adoptedStyleSheets"
    )
    assert isinstance(assignment.value, ast.List)


def test_render_interface_preserves_dictionary_parameters():
    definition = Definition(
        "interface",
        "Canvas",
        members=[
            Member(
                "method",
                "configure",
                "None",
                arguments=[Argument("configuration", "CanvasConfiguration")],
            )
        ],
    )

    method = methods(render_interface(definition, {"Canvas": definition}), "configure")[0]

    assert ast.unparse(method) == (
        "def configure(self, configuration: CanvasConfiguration) -> None:\n"
        "    ..."
    )


def test_render_interface_makes_required_arguments_after_defaults_keyword_only():
    definition = Definition(
        "interface",
        "PipelineError",
        members=[
            Member(
                "method",
                "create",
                "None",
                arguments=[
                    Argument("message", "str", '""'),
                    Argument("options", "PipelineErrorOptions"),
                ],
            )
        ],
    )

    method = methods(
        render_interface(definition, {"PipelineError": definition}), "create"
    )[0]

    assert ast.unparse(method) == (
        "def create(self, message: str='', *, options: PipelineErrorOptions) "
        "-> None:\n"
        "    ..."
    )


def test_synchronize_migrates_legacy_attributes_into_existing_initializer():
    existing = ast.parse(
        """
class Document(Node):
    DOCUMENT_NODE = 9
    adoptedStyleSheets: list[CSSStyleSheet] = []
    title: str = ""

    def _webidl_attributes(self):
        self.adoptedStyleSheets: list[CSSStyleSheet] = []
        self.title: str = ""
        self.contentWindow: Window | None = None

    def __init__(self):
        super().__init__()
        self.title = "Untitled"
"""
    )
    generated = ast.parse(
        """
class Document(Node):
    DOCUMENT_NODE = 9

    def __init__(self):
        super().__init__()
        self.adoptedStyleSheets: list[CSSStyleSheet] = []
        self.title: str = ""
        self.contentWindow: WindowProxy | None = None
"""
    )

    result = synchronize(existing, generated)
    document = class_node(result, "Document")
    initializer = methods(document, "__init__")[0]

    assert not methods(document, "_webidl_attributes")
    assert not any(isinstance(statement, ast.AnnAssign) for statement in document.body)
    assignments = {
        node_key
        for statement in initializer.body
        if (node_key := ast.unparse(statement)).startswith("self.")
    }
    assert "self.adoptedStyleSheets: list[CSSStyleSheet] = []" in assignments
    assert "self.title = 'Untitled'" in assignments
    assert "self.contentWindow: Window | None = None" in assignments


def test_synchronize_preserves_explicit_class_attribute_defaults():
    existing = ast.parse(
        """
class HTMLDivElement(HTMLElement):
    tagName = "DIV"
    tagName: str = ""

    def _webidl_attributes(self):
        self.tagName: str = ""
"""
    )
    generated = ast.parse(
        """
class HTMLDivElement(HTMLElement):
    def __init__(self):
        super().__init__()
        self.tagName: str = ""
        self.align: str = ""
"""
    )

    result = synchronize(existing, generated)
    element = class_node(result, "HTMLDivElement")
    initializer = methods(element, "__init__")[0]
    initializer_source = ast.unparse(initializer)

    assert "tagName = 'DIV'" in ast.unparse(element)
    assert "self.tagName" not in initializer_source
    assert "self.align: str = ''" in initializer_source


def test_synchronize_preserves_property_backed_attributes():
    existing = ast.parse(
        """
class Collection:
    def __init__(self, items=None):
        self._items = [] if items is None else items

    @property
    def length(self) -> int:
        return len(self._items)
"""
    )
    generated = ast.parse(
        """
class Collection:
    def __init__(self):
        self.length: int = 0
"""
    )

    result = synchronize(existing, generated)
    collection = class_node(result, "Collection")
    initializer = methods(collection, "__init__")[0]

    assert ast.unparse(initializer) == (
        "def __init__(self, items=None):\n"
        "    self._items = [] if items is None else items"
    )
    assert len(methods(collection, "length")) == 1


def test_synchronize_preserves_existing_field_type_and_value():
    existing = ast.parse(
        """
class Element:
    def __init__(self):
        self.children: list[Element] = []
"""
    )
    generated = ast.parse(
        """
class Element:
    def __init__(self):
        self.children: HTMLCollection = None
"""
    )

    result = synchronize(existing, generated)
    initializer = methods(class_node(result, "Element"), "__init__")[0]
    assignment = initializer.body[0]

    assert isinstance(assignment, ast.AnnAssign)
    assert ast.unparse(assignment.annotation) == "list[Element]"
    assert isinstance(assignment.value, ast.List)


def test_synchronize_preserves_generic_bases_and_adds_missing_members():
    existing = ast.parse(
        """
class Request[T](EventTarget):
    def result(self) -> T: ...
"""
    )
    generated = ast.parse(
        """
class Request(EventTarget):
    def result(self) -> object: ...
    def cancel(self) -> None: ...
"""
    )

    result = synchronize(existing, generated)
    request = class_node(result, "Request")

    assert ast.unparse(request) == (
        "class Request[T](EventTarget):\n\n"
        "    def result(self) -> T:\n"
        "        ...\n\n"
        "    def cancel(self) -> None:\n"
        "        ..."
    )
