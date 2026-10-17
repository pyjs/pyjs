import gc
import sys
import typing
import weakref

import pytest

from pyjs.analysis import LibraryMappings
from pyjs.analysis import analyze_source as analyze_python_source
from pyjs.analysis.analyzer import (
    JS_BUILTINS,
    AnalysisEnvironment,
    InferenceVisitor,
    release_compilation,
)
from pyjs.analysis.source import create_module
from pyjs.decorators import js_metadata
from pyjs.javascript.source import analyze_source, compile_source
from pyjs.javascript.transpiler import prepare_bundle
from pyjs.testing.helpers import (
    ad,
    assert_bundle_module_transpile,
    assert_compilation_diagnostic,
    assert_compiled_sources,
    assert_module_analysis_transpile,
    assert_module_transpile,
    diagnostic_text,
    transpile_line,
)
from pyjs.tooling.node import Node


def test_create_module_preserves_source_for_inspection():
    module = create_module("def answer():\n    return 42\n", "memory_example.py")

    assert module.answer() == 42
    assert module.answer.__code__.co_filename == "memory_example.py"


@pytest.mark.parametrize("existing", ["absent", "blocked", "module"])
@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_create_module_failure_restores_exact_registry_state(monkeypatch, existing, failure):
    from types import ModuleType

    name = "_pyjs_failed_registry_replacement"
    previous = ModuleType(name) if existing == "module" else None
    if existing == "absent":
        monkeypatch.delitem(sys.modules, name, raising=False)
    else:
        monkeypatch.setitem(sys.modules, name, previous)
    with pytest.raises(failure, match="failed replacement"):
        create_module(f"raise {failure.__name__}('failed replacement')", "registry.py", name)
    assert (name in sys.modules) == (existing != "absent")
    assert sys.modules.get(name) is previous


def test_create_module_discards_overloads_from_the_replaced_module():
    overloaded = create_module(
        """
from typing import overload

@overload
def choose(value: int) -> int: ...

def choose(value):
    return value
""",
        "reloaded.py",
        "_pyjs_test_reloaded",
    )
    assert len(typing.get_overloads(overloaded.choose)) == 1

    with pytest.raises(RuntimeError, match="failed replacement"):
        create_module(
            """
from typing import overload

@overload
def choose(value: str) -> str: ...

raise RuntimeError("failed replacement")
""",
            "reloaded.py",
            "_pyjs_test_reloaded",
        )
    assert len(typing.get_overloads(overloaded.choose)) == 1

    replacement = create_module(
        "def choose(value):\n    return value\n",
        "reloaded.py",
        "_pyjs_test_reloaded",
    )

    assert typing.get_overloads(replacement.choose) == []


def test_analyze_source_wraps_a_function_body():
    analysis = analyze_source("value = 1 + 2", wrap=True)

    assert "value: int" in analysis.types
    assert "var value = 1 + 2;" in analysis.javascript


def test_target_definition_filter_does_not_require_js_metadata():
    environment = AnalysisEnvironment(
        "example",
        JS_BUILTINS,
        LibraryMappings(),
        InferenceVisitor,
        analyze_all_definitions=False,
        definition_filter=lambda name, _value, _module: name == "helper",
    )
    with analyze_source(
        """
def helper(value: int) -> int:
    return value + 1

def main() -> int:
    return helper(2)
""",
        wrap=False,
        environment=environment,
    ) as analysis:
        assert analysis.entry_point.name == "main"
        assert analysis.entry_point.container.search("helper").name == "helper"


def test_analysis_environment_selects_its_library_mappings():
    mappings = LibraryMappings(
        stdlib_imports={
            ("math", "sqrt"): ("pyjs.stdlib.math", "sqrt"),
        },
    )
    environment = AnalysisEnvironment(
        "example",
        JS_BUILTINS,
        mappings,
        InferenceVisitor,
        analyze_all_definitions=False,
        definition_filter=lambda name, _value, _module: name in {"main", "sqrt"},
    )
    with analyze_python_source(
        """
        from math import sqrt

        def main() -> float:
            return sqrt(4.0)
        """,
        environment=environment,
    ) as analysis:
        assert "pyjs.stdlib.math" in analysis.entry_point.container.container
        assert "return sqrt(4.0)" in analysis.types


def test_analyze_source_keeps_imports_and_declarations_outside_wrapped_main():
    analysis = analyze_source(
        """
from pyjs import js

@js
def double(value: int) -> int:
    return value * 2

print(double(3))
""",
        wrap=True,
    )

    assert "export function double(value)" in analysis.javascript
    assert "console.log(double(3))" in analysis.javascript


def test_analyze_source_keeps_type_aliases_outside_wrapped_main():
    assert_module_transpile(
        """
        from pyjs import js

        Vector = tuple[float, float]

        @js
        def first(values: list[Vector]) -> Vector:
            return values[0]

        print(first([(3.0, 4.0)])[0])
        """,
        """
        import { float_string as $float_string, get_tuple_item as $get_tuple_item, get_list_item as $get_list_item } from './pyjs.python.js';

        export function first(values) {
            return $get_list_item(values, 0);
        }

        export function main() {
            console.log($float_string($get_tuple_item(first([[3.0, 4.0]]), 0)));
        }
        """,
        wrap=True,
    )


def test_imported_type_alias_resolves_its_defining_type_dependencies():
    module_name = "_pyjs_imported_type_alias_contract"
    consumer_name = "_pyjs_imported_type_alias_consumer"
    create_module(
        """
from dataclasses import dataclass
from typing import TypeAlias

from pyjs import js

@js
@dataclass(frozen=True)
class Alpha:
    value: int

@js
@dataclass(frozen=True)
class Bravo:
    label: str

Choice: TypeAlias = Alpha | Bravo
""",
        filename=f"{module_name}.py",
        module_name=module_name,
    )
    try:
        assert_compiled_sources(
            f"""
from {module_name} import Choice

from pyjs import js

@js
def size(values: list[Choice]) -> int:
    return len(values)

def main():
    print(size([]))
""",
            {
                consumer_name: """
                export function size(values) {
                    return values.length;
                }

                export function main() {
                    console.log(size([]));
                }
                """,
            },
            module_name=consumer_name,
        )
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop(consumer_name, None)


def test_analyze_source_keeps_js_bindings_outside_a_wrapped_main():
    source = """
from typing import Final
from pyjs import JS

answer: Final[JS[int]] = 42
print(answer)
"""
    assert_module_transpile(
        source,
        """
        export const answer = 42;

        export function main() {
            console.log(answer);
        }
""",
        wrap=True,
    )
    assert_bundle_module_transpile(
        source,
        """
        const answer = 42;
        __export_js__.answer = answer;

        function main() {
            console.log(answer);
        }
        __export_js__.main = main;
""",
        wrap=True,
    )


def test_analyze_source_keeps_inferred_js_bindings_outside_wrapped_main():
    assert_module_transpile(
        """
        from typing import Final

        from pyjs import JS

        answer: JS = 42
        label: Final[JS] = "ready"
        print(answer, label)
        """,
        """
        export let answer = 42;
        export const label = 'ready';

        export function main() {
            console.log(answer, label);
        }
        """,
        wrap=True,
    )


def test_analyze_source_can_choose_wrapping_from_the_parsed_module():
    script = analyze_source('message = "def main()"; print(message)')
    module = analyze_source("def main():\n    print('ready')\n")

    assert script.wrapped is True
    assert module.wrapped is False


def test_analyze_source_detects_a_selected_non_main_entry_point():
    with analyze_source(
        "def render():\n    return 'ready'\n",
        entry_point="render",
    ) as analysis:
        assert analysis.wrapped is False
        assert analysis.entry_point.name == "render"


def test_analyze_source_wraps_statements_in_the_selected_entry_point():
    with analyze_source(
        "print('ready')\n",
        entry_point="render",
    ) as analysis:
        assert analysis.wrapped is True
        assert analysis.entry_point.name == "render"


def test_transpiler_test_helper_supports_module_imports():
    javascript = transpile_line(
        'from pyjs.web.events import Event; event = Event("ready"); print(event.type)'
    )

    assert "var event = new Event('ready');" in javascript
    assert "console.log(event.type);" in javascript


def test_len_uses_browser_collection_length():
    analysis = analyze_source(
        """
from pyjs.web.dom import Element

def main():
    results = Element().querySelectorAll("div")
    print(len(results))
"""
    )

    assert "console.log(results.length);" in analysis.javascript


def test_generated_web_apis_preserve_native_names_and_collection_protocols():
    analysis = analyze_source(
        """
from pyjs.web.dom import Element
from pyjs.web.files import FileList
from pyjs.web.indexeddb import IDBCursor

def main(cursor: IDBCursor, element: Element, files: FileList):
    cursor.continue_()
    element.setPointerCapture(7)
    print(len(files))
"""
    )

    assert "cursor.continue();" in analysis.javascript
    assert "element.setPointerCapture(7);" in analysis.javascript
    assert "console.log(files.length);" in analysis.javascript


def test_immutable_class_constants_are_available_to_generated_and_user_apis():
    analysis = analyze_source(
        """
from pyjs import js
from pyjs.web.events import WheelEvent

@js
class Status:
    READY = 1
    LABEL = "ready"

def main():
    print(WheelEvent.DOM_DELTA_PIXEL)
    print(Status.READY)
    print(Status.LABEL)
"""
    )

    assert "console.log(WheelEvent.DOM_DELTA_PIXEL);" in analysis.javascript
    assert "static READY = 1;" in analysis.javascript
    assert "static LABEL = 'ready';" in analysis.javascript
    assert "console.log(Status.READY);" in analysis.javascript
    assert "console.log(Status.LABEL);" in analysis.javascript


def test_js_module_scalar_bindings_infer_types_and_are_tree_shaken():
    assert_module_analysis_transpile(
        """
from typing import Final
from pyjs import JS, js

lowercase: JS = 5_000
UPPERCASE: JS = 10_000
label: Final[JS] = "ready"
enabled: JS = True
ratio: JS = 1.5
missing: JS = None
unused: JS = "unused"
server_secret = "do not include"

@js
class Runner:
    def start(self):
        print(lowercase)
        print(UPPERCASE)
        print(label)
        print(enabled)
        print(ratio)
        print(missing)

def main():
    Runner().start()
""",
        """
        lowercase: __module__ = 5000
        UPPERCASE: __module__ = 10000
        label: __const__ = 'ready'
        enabled: __module__ = True
        ratio: __module__ = 1.5
        missing: __module__ = None

        class Runner:

            def start() -> None:
                print(lowercase)
                print(UPPERCASE)
                print(label)
                print(enabled)
                print($float_string(ratio))
                print(missing)

        def main() -> None:
            Runner().[Runner]start()
        """,
        """
        import { float_string as $float_string } from './pyjs.python.js';
        export let lowercase = 5000;
        export let UPPERCASE = 10000;
        export const label = 'ready';
        export let enabled = true;
        export let ratio = 1.5;
        export let missing = null;

        export class Runner {

            start() {
                console.log(lowercase);
                console.log(UPPERCASE);
                console.log(label);
                console.log((enabled ? 'True' : 'False'));
                console.log($float_string(ratio));
                console.log((missing, 'None'));
            }
        }

        export function main() {
            new Runner().start();
        }
        """,
    )


def test_js_module_scalar_binding_can_supply_a_function_default():
    assert_module_analysis_transpile(
        """
from typing import Final
from pyjs import JS, js

DEFAULT_AMOUNT: Final[JS] = 3

@js
def add(value: int, amount: int = DEFAULT_AMOUNT) -> int:
    return value + amount

def main():
    print(add(4))
    print(add(4, 2))
""",
        """
        DEFAULT_AMOUNT: __const__ = 3

        def add(value: int, amount: int=DEFAULT_AMOUNT) -> int:
            return value.[int]__add__!(amount)

        def main() -> None:
            print(add(4))
            print(add(4, 2))
        """,
        """
        export const DEFAULT_AMOUNT = 3;

        export function add(value, { amount=DEFAULT_AMOUNT} = {}) {
            return value + amount;
        }

        export function main() {
            console.log(add(4));
            console.log(add(4, {amount: 2}));
        }
        """,
    )


def test_annotated_js_metadata_is_the_explicit_module_binding_form():
    assert_module_transpile(
        """
from typing import Annotated
from pyjs import js

answer: Annotated[int, js] = 42

def main():
    print(answer)
""",
        """
        export let answer = 42;

        export function main() {
            console.log(answer);
        }
        """,
    )


def test_js_module_list_bindings_infer_item_types_and_are_tree_shaken():
    assert_module_analysis_transpile(
        """
from typing import Final
from pyjs import JS

names: Final[JS] = ["Ada", "Grace"]
unused: Final[JS] = [1, 2, 3]

def main():
    print(names[1])
    names.append("Linus")
    print(len(names))
""",
        """
        names: __const__ = ['Ada', 'Grace']

        def main() -> None:
            print($get_list_item(names, 1))
            names.[list__str]append!('Linus')
            print(names.[list__str]__len__!())
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';
        export const names = ['Ada', 'Grace'];

        export function main() {
            console.log($get_list_item(names, 1));
            (names.push('Linus'), null);
            console.log(names.length);
        }
        """,
    )


def test_js_module_tuple_bindings_infer_fixed_item_types():
    assert_module_analysis_transpile(
        """
from typing import Final
from pyjs import JS

channels: Final[JS] = ("left", "right")

def main():
    print("left" in channels)
    print(channels[1])
""",
        """
        channels: __const__ = ('left', 'right')

        def main() -> None:
            print($contains_equal_sequence_item(channels, 'left'))
            print($get_tuple_item(channels, 1))
        """,
        """
        import { contains_equal_sequence_item as $contains_equal_sequence_item, get_tuple_item as $get_tuple_item } from './pyjs.python.js';
        export const channels = ['left', 'right'];

        export function main() {
            console.log(($contains_equal_sequence_item(channels, 'left') ? 'True' : 'False'));
            console.log($get_tuple_item(channels, 1));
        }
        """,
    )


def test_module_client_instances_preserve_constructor_arguments_and_dependencies():
    assert_module_transpile(
        """
from pyjs import js

@js
class Transport:
    def __init__(self, token: str):
        self.token = token

@js
class Client:
    def __init__(self, transport: Transport, path: str = "/api"):
        self.transport = transport
        self.path = path

@js
def configured_client(token: str, path: str) -> Client:
    return Client(Transport(token), path=path)

client = configured_client("secret", "/custom")

def main():
    print(client.path)
""",
        """
        export class Transport {

            constructor(token) {
                this.token = token;
            }
        }

        export class Client {

            constructor(transport, { path='/api'} = {}) {
                this.transport = transport;
                this.path = path;
            }
        }

        export function configured_client(token, path) {
            return new Client(new Transport(token), {path: path});
        }
        export const client = configured_client('secret', '/custom');

        export function main() {
            console.log(client.path);
        }
        """,
    )


def test_module_client_instance_arguments_must_be_available_to_javascript():
    assert_compilation_diagnostic(
        """\
        from pyjs import js

        token = "server secret"

        @js
        class Client:
            def __init__(self, token: str):
                self.token = token

        client = Client(token)

        def main():
            print(client.token)
        """,
        diagnostic_text(
            "module_initializer.py",
            10,
            "client = Client(token)",
            "                ^^^^^",
                "pyjs.CompilationError: Name 'token' is a Python value, not a client "
                "value [PYJS1004]",
                "help: Import JS from pyjs and annotate the existing assignment "
                "with JS so its value is available to client code.",
        ),
        filename="module_initializer.py",
    )


def test_module_client_instance_calls_use_normal_argument_validation():
    assert_compilation_diagnostic(
        """\
        from pyjs import js

        @js
        class Client:
            def __init__(self, retries: int):
                self.retries = retries

        client = Client("three")

        def main():
            print(client.retries)
        """,
        diagnostic_text(
            "module_initializer.py",
            8,
            'client = Client("three")',
            "                ^^^^^^^",
            "pyjs.CompilationError: Argument 'retries' to Client.__init__ expects "
            "int, got str [PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="module_initializer.py",
    )


def test_js_module_dict_bindings_infer_key_and_value_types():
    assert_module_analysis_transpile(
        """
from typing import Final
from pyjs import JS

scores: Final[JS] = {"Ada": 10, "Grace": 20}

def main():
    print(scores["Grace"])
    scores["Linus"] = 30
    print(scores["Linus"])
    print(len(scores))
""",
        """
        scores: __const__ = {'Ada': 10, 'Grace': 20}

        def main() -> None:
            print($get_dict_item(scores, 'Grace'))
            scores.[dict__str_int]__setitem__!('Linus', 30)
            print($get_dict_item(scores, 'Linus'))
            print(scores.[dict__str_int]__len__!())
        """,
        """
        import { get_dict_item as $get_dict_item } from './pyjs.python.js';
        export const scores = new Map([['Ada', 10], ['Grace', 20]]);

        export function main() {
            console.log($get_dict_item(scores, 'Grace'));
            (scores.set('Linus', 30), null);
            console.log($get_dict_item(scores, 'Linus'));
            console.log(scores.size);
        }
        """,
    )


def test_unmarked_module_values_remain_outside_the_compilation_boundary():
    ad(
        """\
        server_value = "server only"

        def main():
            print(server_value)
        """,
        diagnostic_text(
            "server_value.py",
            4,
            "print(server_value)",
            "      ^^^^^^^^^^^^",
            "pyjs.CompilationError: Name 'server_value' is a Python value, not a "
            "client value [PYJS1004]",
            "help: Import JS from pyjs and annotate the existing assignment "
            "with JS so its value is available to client code.",
        ),
        filename="server_value.py",
    )


def test_js_bindings_do_not_resolve_unrelated_server_annotations():
    assert_module_transpile(
        """
from pyjs import JS

server_value: ServerOnlyType = None
answer: JS[int] = 42

def main():
    print(answer)
""",
        """
        export let answer = 42;

        export function main() {
            console.log(answer);
        }
        """,
    )


def test_js_module_bindings_reject_unsupported_runtime_values():
    ad(
        """\
        from pyjs import JS

        item: JS[object] = object()

        def main():
            print(item)
        """,
        diagnostic_text(
            "module_binding.py",
            3,
            "item: JS[object] = object()",
            "                   ^^^^^^^^",
            "pyjs.CompilationError: JS module binding `item` has unsupported "
            "value type `object` [PYJS2001]",
            "help: Use a literal bool, int, float, str, list, tuple, dict, or "
            "None value.",
        ),
        filename="module_binding.py",
    )


@pytest.mark.parametrize(
    ("declaration", "underline", "message"),
    [
        (
            "items: JS = []",
            "            ^^",
            "Cannot infer the item type of an empty JS module list; use JS[list[T]].",
        ),
        (
            "items: JS = {}",
            "            ^^",
            "Cannot infer the key and value types of an empty JS module dict; "
            "use JS[dict[K, V]].",
        ),
        (
            "items: JS = ()",
            "            ^^",
            "Cannot infer the item types of an empty JS module tuple; "
            "use JS[tuple[T, ...]].",
        ),
    ],
)
def test_empty_js_module_collections_require_an_explicit_type(
    declaration,
    underline,
    message,
):
    ad(
        f"""\
        from pyjs import JS

        {declaration}

        def main():
            print(items)
        """,
        diagnostic_text(
            "empty_binding.py",
            3,
            declaration,
            underline,
            f"pyjs.CompilationError: {message} [PYJS1101]",
            "help: Specialize JS with the complete client type, such as JS[list[str]].",
        ),
        filename="empty_binding.py",
    )


def test_empty_js_module_collections_accept_explicit_types():
    assert_module_analysis_transpile(
        """
from pyjs import JS

names: JS[list[str]] = []
scores: JS[dict[str, int]] = {}

def main():
    print(len(names))
    print(len(scores))
""",
        """
        names: __module__ = []
        scores: __module__ = {}

        def main() -> None:
            print(names.[list__str]__len__!())
            print(scores.[dict__str_int]__len__!())
        """,
        """
        export let names = [];
        export let scores = new Map([]);

        export function main() {
            console.log(names.length);
            console.log(scores.size);
        }
        """,
    )


def test_imported_js_module_bindings_preserve_source_module_and_aliases():
    module_name = "_pyjs_js_binding_settings"
    create_module(
        """
from typing import Final
from pyjs import JS

timeout: Final[JS] = 5_000
modes: Final[JS] = ["fast", "safe"]
server_secret = "do not include"
""",
        filename=f"{module_name}.py",
        module_name=module_name,
    )
    try:
        assert_compiled_sources(
            f"""
from {module_name} import modes as request_modes, timeout as request_timeout

def main():
    print(request_timeout)
    print(request_modes[0])
""",
            {
                module_name: """
                export const timeout = 5000;
                export const modes = ['fast', 'safe'];
                """,
                "_pyjs_js_binding_consumer": f"""
                import {{ modes as request_modes, timeout as request_timeout }} from './{module_name}.js';
                import {{ get_list_item as $get_list_item }} from './pyjs.python.js';

                export function main() {{
                    console.log(request_timeout);
                    console.log($get_list_item(request_modes, 0));
                }}
                """,
                "pyjs.python": """
                export function get_list_item(target, index) {
                    var actual_index = index < 0 ? index + target.length : index;
                    if (actual_index < 0 || actual_index >= target.length) {
                        throw new IndexError('list index out of range');
                    }
                    return target[Number(actual_index)];
                }

                export class LookupError extends Error {
                }

                export class IndexError extends LookupError {
                }
                """,
            },
            module_name="_pyjs_js_binding_consumer",
        )
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("_pyjs_js_binding_consumer", None)


def test_imported_generic_union_orders_share_emitted_methods():
    module_name = "_pyjs_generic_union_model"
    consumer_name = "_pyjs_generic_union_consumer"
    create_module('''
from pyjs import js
@js
class Box[T]:
    def __init__(self, value: T):
        self.value = value
    def get(self) -> T:
        return self.value
    def unused(self) -> int:
        return 99
@js
def read(box: Box[int | str]) -> int:
    box.get()
    return 7
''', filename=f"{module_name}.py", module_name=module_name)
    source = f'''
from {module_name} import Box, read
def main() -> int:
    return read(Box[str | int](1))
'''
    try:
        with compile_source(source, module_name=consumer_name) as compilation:
            assert compilation.sources == {
                module_name: '''export class Box__intUstr {

    constructor(value) {
        this.value = value;
    }

    get() {
        return this.value;
    }
}

export function read(box) {
    box.get();
    return 7;
}''',
                consumer_name: f'''import {{ Box__intUstr, read }} from './{module_name}.js';

export function main() {{
    return read(new Box__intUstr(1));
}}''',
            }
            result = Node().run_javascript(compilation.javascript + "\nconsole.log(__pyjsEntry__.main());")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "7\n"
        assert result.stderr == ""
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop(consumer_name, None)


def test_reserved_module_exports_and_import_aliases_are_escaped():
    module_name = "_pyjs_reserved_bindings"
    create_module(
        """
from pyjs import JS, js

@js
def default(value: int) -> int:
    return value + 1

static: JS = 4
""",
        filename=f"{module_name}.py",
        module_name=module_name,
    )
    try:
        assert_compiled_sources(
            f"""
from {module_name} import default as package, static

def main():
    new = package(static)
    print(new)
""",
            {
                module_name: """
                export function $$default(value) {
                    return value + 1;
                }
                export let $$static = 4;
                """,
                "_pyjs_reserved_binding_consumer": f"""
                import {{ $$static, $$default as $$package }} from './{module_name}.js';

                export function main() {{
                    var $$new = $$package($$static);
                    console.log($$new);
                }}
                """,
            },
            module_name="_pyjs_reserved_binding_consumer",
        )
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("_pyjs_reserved_binding_consumer", None)


def test_dunder_dispatch_supports_builtins_and_user_classes():
    analysis = analyze_source(
        """
from pyjs import js

@js
class Basket:
    def __init__(self, count: int):
        self.count = count

    def __len__(self) -> int:
        return self.count

def main():
    print(len("abc"))
    print(len([1, 2]))
    print(len({"answer": 42}))
    print(len(Basket(4)))
    print(abs(-3))
    print(abs(-1.5))
    print(round(1.5))
"""
    )

    assert "console.log([...'abc'].length);" in analysis.javascript
    assert "console.log([1, 2].length);" in analysis.javascript
    assert "console.log(new Map([['answer', 42]]).size);" in analysis.javascript
    assert "console.log(new Basket(4).__len__());" in analysis.javascript
    assert "Math.abs(-3)" in analysis.javascript
    assert "Math.abs(-1.5)" in analysis.javascript
    assert "Math.round(value)" in analysis.javascript
    assert "__len__()" in analysis.javascript


def test_javascript_math_uses_the_native_browser_namespace():
    analysis = analyze_source(
        """
from pyjs.javascript import Math

def main(maximum: int):
    index = round(Math.random() * 1000) % maximum
"""
    )

    assert "Math.round(value)" in analysis.javascript
    assert "Math.random() * 1000" in analysis.javascript


def test_compile_source_produces_an_executable_bundle_entry():
    compilation = compile_source("def main():\n    print('hello')\n")

    assert "const __pyjsEntry__ = importModule" in compilation.javascript
    assert "console.log('hello')" in compilation.javascript
    assert compilation.sources == {
        "_pyjs_source_": "export function main() {\n    console.log('hello');\n}"
    }
    assert compilation.entry_point.name == "main"


def test_source_entry_points_are_retained_without_marking_them_keep():
    module = create_module(
        "def main():\n    print('ready')\n",
        "entry_point.py",
    )
    package, entry_point, _css = prepare_bundle(
        module.main,
        include_main=True,
        include_css=False,
    )
    try:
        assert not js_metadata(module.main, "keep", False)
        assert package == {
            "entry_point": """\
export function main() {
    console.log('ready');
}"""
        }
    finally:
        release_compilation(entry_point)


def test_discarded_source_analysis_releases_its_compilation_graph():
    analysis = analyze_source("value = len([1, 2, 3])", wrap=True)
    entry_point = weakref.ref(analysis.entry_point)

    del analysis
    gc.collect()

    assert entry_point() is None


def test_discarded_source_compilation_releases_its_compilation_graph():
    from pyjs.analysis.analyzer import BUILTINS, _reachable_analyzer_objects

    initial_count = len(tuple(_reachable_analyzer_objects(BUILTINS)))
    compilation = compile_source(
        """
from pyjs import js
from pyjs.server import WatchedQuery

@js
async def load() -> int:
    return 1

def main():
    query = WatchedQuery[int](load)
"""
    )
    entry_point = weakref.ref(compilation.entry_point)

    del compilation
    gc.collect()

    assert entry_point() is None
    assert len(tuple(_reachable_analyzer_objects(BUILTINS))) == initial_count


def test_discarded_prepared_bundle_releases_its_compilation_graph():
    module = create_module(
        "def main():\n    print(len([1, 2, 3]))\n",
        "discarded_prepare.py",
    )
    package, analyzed_entry_point, _css = prepare_bundle(
        module.main,
        include_main=True,
    )
    entry_point = weakref.ref(analyzed_entry_point)

    del package, analyzed_entry_point, module
    gc.collect()

    assert entry_point() is None


def test_source_results_can_release_shared_compiler_state_explicitly():
    from pyjs.analysis.analyzer import BUILTINS, _reachable_analyzer_objects

    initial_count = len(tuple(_reachable_analyzer_objects(BUILTINS)))
    source = """
from pyjs import js
from pyjs.server import WatchedQuery

@js
async def load() -> int:
    return 1

def main():
    query = WatchedQuery[int](load)
"""

    with compile_source(source) as compilation:
        assert compilation.entry_point.name == "main"

    assert len(tuple(_reachable_analyzer_objects(BUILTINS))) == initial_count


def test_overlapping_source_results_can_close_out_of_order():
    from pyjs.analysis.analyzer import BUILTINS, _reachable_analyzer_objects

    initial_count = len(tuple(_reachable_analyzer_objects(BUILTINS)))
    source = """
from pyjs import js
from pyjs.server import WatchedQuery

@js
async def load() -> {value_type}:
    return {value}

def main():
    query = WatchedQuery[{value_type}](load)
"""
    first = compile_source(
        source.format(value_type="int", value="1"),
        module_name="first_source",
    )
    second = compile_source(
        source.format(value_type="str", value="'two'"),
        module_name="second_source",
    )

    first.close()
    assert len(tuple(_reachable_analyzer_objects(BUILTINS))) > initial_count

    second.close()
    assert len(tuple(_reachable_analyzer_objects(BUILTINS))) == initial_count


def test_analyze_source_ignores_python_314_deferred_class_annotations():
    analysis = analyze_source(
        """
from pyjs import js

@js
class Result:
    value: int

def main():
    Result()
"""
    )

    assert "export class Result" in analysis.javascript
