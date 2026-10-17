from dataclasses import FrozenInstanceError
from textwrap import dedent
from unittest.mock import Mock

import pytest

from pyjs import js
from pyjs.analysis.analyzer import release_compilation
from pyjs.analysis.diagnostics import CompilationError
from pyjs.decorators import (
    backend_references,
    configure_js,
    is_declaration,
    is_js_enabled,
    js_metadata,
    own_js_decoration,
    own_js_metadata,
)
from pyjs.javascript.source import compile_source
from pyjs.javascript.transpiler import bundle, bundle_import, prepare_bundle
from pyjs.testing.helpers import ad, assert_transpile, at, diagnostic_text
from pyjs.web import domx
from pyjs.web.dom import HTMLElement
from pyjs.web.domx import div, tw
from tests.semantics.helpers import assert_semantics


@pytest.mark.parametrize("annotation", ["Later", "Annotated[Later, f'{UNIT}']"])
def test_inline_reference_validation_allows_a_later_class_annotation(annotation):
    source = '''
        from typing import Annotated
        from pyjs import js
        UNIT = "javascript"
        @js
        def helper(value: Later) -> int:
            return value.amount
        @js.inline("{helper}({value})", helper=helper)
        def read(value: Later) -> int:
            return helper(value)
        @js
        class Later:
            def __init__(self, amount: int):
                self.amount = amount
        def main() -> None:
            print(read(Later(42)))
    '''.replace("value: Later", f"value: {annotation}")
    at(source, '''
        def helper(value: Later) -> int:
            return value.amount

        class Later:

            def __init__(amount: int) -> None:
                self.amount = amount

        def main() -> None:
            print(read(Later(42)))
    ''', '''
        const $helper = helper;

        export function helper(value) {
            return value.amount;
        }

        export class Later {

            constructor(amount) {
                this.amount = amount;
            }
        }

        export function main() {
            console.log($helper(new Later(42)));
        }
    ''')
    assert_semantics(dedent(source) + "\nmain()\n")


def test_declaration_namespace_emits_only_the_reached_static_member():
    source = '''
        @js.inline("{value} + 1")
        def transform(value: int) -> int:
            return value + 1

        @js.inline("{value} * 2")
        def twice(value: int) -> int:
            return value * 2

        transform.twice = twice

        def main() -> int:
            return transform.twice(3)
    '''
    at(source, '''
        def main() -> int:
            return twice(3)
    ''', '''
        export function main() {
            return 3 * 2;
        }
    ''')


def inline_dom_helper_entrypoint():
    return div(div("Inline helper"))


def styled_entrypoint():
    return div(tw("hidden"), "Styled")


def keep_for_test(monkeypatch, function):
    previous = vars(function).get("__js__")
    monkeypatch.setattr(function, "__js__", previous, raising=False)
    configure_js(function, keep=True)


def test_inline_dependency_replaces_wrapper_and_retains_runtime_helper(monkeypatch):
    keep_for_test(monkeypatch, inline_dom_helper_entrypoint)
    package, entry_point, _ = prepare_bundle(
        inline_dom_helper_entrypoint,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_css=False,
    )

    release_compilation(entry_point)

    assert (
        package[__name__]
        == """\
const {tag: $tag} = __import_js__('pyjs.web.domx');

function inline_dom_helper_entrypoint() {
    return $tag('div', $tag('div', 'Inline helper'));
}
__export_js__.inline_dom_helper_entrypoint = inline_dom_helper_entrypoint;"""
    )
    assert (
        package["pyjs.web.domx"]
        == """\
class ProxyElement {
}
__export_js__.ProxyElement = ProxyElement;

function tag(name_or_element, ...args) {
    if ((typeof name_or_element === 'string')) {
        var e = document.createElement(name_or_element);
    } else {
        e = name_or_element;
    }
    for (var arg of args) {
        if ((typeof arg === 'string')) {
            e.append(arg);
        } else if ((arg instanceof Element)) {
            e.append(arg);
        } else if ((arg instanceof ProxyElement)) {
            e.append(arg.element);
        } else if ((arg instanceof Map)) {
            var attrs = arg;
            for (var [attr, value] of attrs.entries()) {
                e.setAttribute(attr, value);
            }
        } else {
            throw new TypeError();
        }
    }
    return e;
}
__export_js__.tag = tag;"""
    )


def test_canvas_accepts_the_same_dom_arguments_as_other_tag_helpers():
    assert_transpile(
        """
        from pyjs.web.domx import canvas, tw

        def main():
            return canvas(tw("block"), {"aria-label": "Game"})
        """,
        """
        import { tw, tag as $tag } from './pyjs.web.domx.js';

        export function main() {
            return $tag('canvas', tw('block'), new Map([['aria-label', 'Game']]));
        }
        """,
    )


@js
def tag(value: str) -> str:
    return value


@js.inline(
    "({local}({value}), {remote}('div'))",
    local=tag,
    remote=domx.tag,
)
def colliding_dependency_names(value: str) -> HTMLElement:
    return div(value)


def colliding_dependency_entrypoint(use_local: bool) -> HTMLElement:
    if use_local:
        result = colliding_dependency_names("local")
    else:
        result = colliding_dependency_names("remote")
    return result


def no_inline_dependency_entrypoint() -> int:
    return 1


def test_positional_references_must_be_classes_or_functions():
    with pytest.raises(TypeError) as caught:
        js.references(3)

    assert str(caught.value) == "JavaScript references must be classes or functions."


def test_reference_names_must_be_identifiers():
    def render(): ...

    render.__qualname__ = "render"
    with pytest.raises(TypeError) as caught:
        js.inline("null", **{"not-valid": tag})(render)

    assert str(caught.value) == (
        "JavaScript references require identifier names and class or function "
        "values; invalid: 'not-valid' (function)."
    )


def test_references_must_be_classes_or_functions():
    def render(): ...

    render.__qualname__ = "render"
    with pytest.raises(TypeError) as caught:
        js.inline("null", helper=3)(render)

    assert str(caught.value) == (
        "JavaScript references require identifier names and class or function "
        "values; invalid: 'helper' (int)."
    )


def test_inline_reference_names_cannot_shadow_call_arguments():
    def render(value: str): ...

    render.__qualname__ = "render"
    with pytest.raises(TypeError) as caught:
        js.inline("null", value=tag)(render)

    assert str(caught.value) == (
        "@js.inline reference names for 'render' conflict with call arguments: value."
    )


def test_inline_reference_names_cannot_shadow_the_result_format():
    def render(value: str): ...

    render.__qualname__ = "render"
    with pytest.raises(TypeError) as caught:
        js.inline("null", _result_format=tag)(render)

    assert str(caught.value) == (
        "@js.inline reference names for 'render' conflict with call arguments: "
        "_result_format."
    )


def test_inline_reference_names_cannot_shadow_argument_representations():
    def render(value: str): ...

    render.__qualname__ = "render"
    with pytest.raises(TypeError) as caught:
        js.inline("null", _arg_representations=tag)(render)

    assert str(caught.value) == (
        "@js.inline reference names for 'render' conflict with call arguments: "
        "_arg_representations."
    )


def test_inline_generators_receive_nested_argument_representations():
    assert_transpile(
        """
        from pyjs import StaticArray, int8, int64, js

        def item_width(value, _arg_representations, **kwargs):
            item = _arg_representations[0].item_representation
            return "0" if item is None else str(item.numeric.bits)

        @js.inline(item_width)
        def width(value: object) -> int: ...

        def has_int64(value, _arg_representations, **kwargs):
            return str(
                any(
                    item.kind == "integer" and item.bits == 64
                    for item in _arg_representations[0].numeric_formats
                )
            ).lower()

        @js.inline(has_int64)
        def contains_int64(value: object) -> bool: ...

        def main():
            values: list[int8] = [int8(1)]
            fixed = StaticArray[int64, 1]([1])
            either: list[int64] | tuple[int64, ...] = [int64(1)]
            mixed: list[int64] | tuple[int8, ...] = [int64(1)]
            homogeneous: tuple[int64, int64] = (int64(1), int64(2))
            heterogeneous: tuple[int8, int64] = (int8(1), int64(2))
            possible_items: list[int64] | tuple[float, ...] = [int64(1)]
            possible_value: int64 | float = int64(1)
            return (
                width(values)
                + width(fixed)
                + width(either)
                + width(mixed)
                + width(homogeneous)
                + width(heterogeneous)
                + contains_int64(possible_items)
                + contains_int64(possible_value)
            )
        """,
        """
        export function main() {
            var values = [((1 << 24) >> 24)];
            var fixed = [BigInt.asIntN(64, BigInt(1))];
            var either = [BigInt.asIntN(64,BigInt('1'))];
            var mixed = [BigInt.asIntN(64,BigInt('1'))];
            var homogeneous = [BigInt.asIntN(64,BigInt('1')), BigInt.asIntN(64,BigInt('2'))];
            var heterogeneous = [((1 << 24) >> 24), BigInt.asIntN(64,BigInt('2'))];
            var possible_items = [BigInt.asIntN(64,BigInt('1'))];
            var possible_value = BigInt.asIntN(64,BigInt('1'));
            return 8 + 64 + 64 + 0 + 64 + 0 + true + true;
        }
        """,
    )


def test_tuple_producers_preserve_tuple_representation_identity():
    assert_transpile(
        """
        from pyjs import int8, int64, js

        def tuple_metadata(value, _arg_representations, **kwargs):
            representation = _arg_representations[0]
            item = representation.item_representation
            return str(
                (100 if representation.kind == "tuple" else 0)
                + (item.numeric.bits if item is not None else 0)
            )

        @js.inline(tuple_metadata)
        def metadata(value: object) -> int: ...

        @js
        def varargs(*values: int8) -> int:
            return metadata(values)

        @js
        def dynamic_slice(
            values: tuple[int64, int64],
            stop: int,
        ) -> int:
            return metadata(values[:stop])

        @js
        def main() -> None:
            mixed: tuple[int8, int64] = (int8(1), int64(2))
            mapping: dict[int8, int64] = {int8(1): int64(2)}
            converted = tuple([int64(1), int64(2)])
            print(metadata(mixed))
            print(metadata(mixed[:]))
            print(metadata(mapping.popitem()))
            print(metadata(converted))
            print(metadata(next(enumerate([int64(1)]))))
            print(metadata(next(zip([int8(1)], [int64(2)]))))
            print(metadata(divmod(int8(5), int8(2))))
            print(metadata(next(iter(mapping.items()))))
            print(varargs(int8(1), int8(2)))
            print(dynamic_slice((int64(1), int64(2)), 1))
        """,
        """
        import { pop_dict_pair as $pop_dict_pair, raise_stop_iteration as $raise_stop_iteration, float_divmod as $float_divmod, integer_index as $integer_index } from './pyjs.python.js';

        export function varargs(...values) {
            return 108;
        }

        export function dynamic_slice(values, stop) {
            return 164;
        }

        export function main() {
            var mixed = [((1 << 24) >> 24), BigInt.asIntN(64,BigInt('2'))];
            var mapping = new Map([[((1 << 24) >> 24), BigInt.asIntN(64,BigInt('2'))]]);
            var converted = Array.from([BigInt.asIntN(64,BigInt('1')), BigInt.asIntN(64,BigInt('2'))]);
            console.log(100);
            console.log(100);
            console.log(100);
            console.log(164);
            console.log(100);
            console.log(100);
            console.log(108);
            console.log(100);
            console.log(varargs(((1 << 24) >> 24), ((2 << 24) >> 24)));
            console.log(dynamic_slice([BigInt.asIntN(64,BigInt('1')), BigInt.asIntN(64,BigInt('2'))], 1));
        }
        """,
    )


def test_bound_inline_decorator_accepts_references():
    at(
        """
        from pyjs import js

        @js
        def wrap(value: str) -> str:
            return "[" + value + "]"

        @js
        def render(value: str) -> str: ...

        @render.inline(wrap=wrap)
        def render(value, wrap, **kwargs):
            return f"{wrap}({value})"

        def main():
            print(render("ready"))
        """,
        """
        def wrap(value: str) -> str:
            return '['.[str]__add__!(value).[str]__add__!(']')

        def main() -> None:
            print(render('ready'))
        """,
        """
        const $wrap = wrap;

        export function wrap(value) {
            return '[' + value + ']';
        }

        export function main() {
            console.log($wrap('ready'));
        }
        """,
    )


def test_inline_reference_can_retain_a_class():
    at(
        """
        from pyjs import js

        @js
        class Box:
            def __init__(self, value: str):
                self.value = value

        @js.inline("new {Box}({value})", Box=Box)
        def make_box(value: str) -> Box: ...

        def main():
            box = make_box("ready")
        """,
        """
        class Box:

            def __init__(value: str) -> None:
                self.value = value

        def main() -> None:
            box: Box = make_box('ready')
        """,
        """
        const $Box = Box;

        export class Box {

            constructor(value) {
                this.value = value;
            }
        }

        export function main() {
            var box = new $Box('ready');
        }
        """,
    )


def test_source_implementation_references_retain_generated_code_dependencies():
    at(
        """
        from pyjs import js

        @js
        def helper() -> str:
            return "ready"

        @js.references(helper)
        def source(analyzed):
            return "return helper();"

        @js
        def render() -> str: ...

        render.source(source)

        def main():
            print(render())
        """,
        """
        def helper() -> str:
            return 'ready'

        def render() -> str:

        def main() -> None:
            print(render())
        """,
        """
        export function helper() {
            return 'ready';
        }

        export function render() {
            return helper();
        }

        export function main() {
            console.log(render());
        }
        """,
    )


def test_post_definition_references_retain_generated_code_dependencies():
    assert_transpile(
        """
        from pyjs.decorators import configure_js

        @js
        def helper() -> str:
            return "ready"

        @js
        class Widget:
            def render(self) -> str:
                return "widget"

        @js.references(helper)
        def post_definition(included):
            return "Widget.helper = helper;"

        configure_js(Widget, post_definition_source=post_definition)

        def main():
            print(Widget().render())
        """,
        """
        export function helper() {
            return 'ready';
        }

        export class Widget {

            render() {
                return 'widget';
            }
        }
        Widget.helper = helper;

        export function main() {
            console.log(new Widget().render());
        }
        """,
    )


def test_source_reference_requires_client_compilation():
    ad(
        """\
        from pyjs import js

        def helper() -> str:
            return "ready"

        @js.references(helper)
        @js
        def render() -> str: ...

        render.source("return helper();")

        def main():
            print(render())
        """,
        diagnostic_text(
            "source_reference.py",
            8,
            "def render() -> str: ...",
            "    ^^^^^^",
            "pyjs.CompilationError: JavaScript reference 'helper' of generated "
            "code for 'render' is not available to client code [PYJS1002]",
            "help: Decorate 'helper' with @js.",
        ),
        filename="source_reference.py",
    )


def test_inline_copies_references_from_its_source_callable():
    @js
    def render(): ...

    @js.references(helper=tag)
    def source(**kwargs):
        return "null"

    render.inline(source)

    assert backend_references(render, "js") == {"helper": tag}


def test_value_implementation_must_be_a_function():
    def render(): ...

    render.__qualname__ = "render"
    render = js.inline("null")(render)
    with pytest.raises(TypeError) as caught:
        render.value(3)

    assert str(caught.value) == "@render.value requires a function."


def test_inline_implementation_must_be_callable():
    @js
    def render(): ...

    with pytest.raises(TypeError) as caught:
        render.inline(3)

    assert str(caught.value) == "@render.inline requires a callable."


def test_inline_source_must_be_a_string_or_callable():
    def render(): ...

    with pytest.raises(TypeError) as caught:
        js.inline(3)(render)

    assert str(caught.value) == "@js.inline requires a source string or callable."


def test_js_decorated_function_is_not_accepted_as_inline_source_generator():
    @js
    def runtime_helper(value: str) -> str:
        return value

    def render(value: str) -> str: ...

    with pytest.raises(TypeError) as caught:
        js.inline(runtime_helper)(render)

    assert str(caught.value) == (
        "An @js.inline source generator cannot be marked @js. "
        "Use @js.inline(call=helper) to call a runtime helper."
    )


def test_js_decorated_function_is_not_accepted_by_inline_method():
    @js.inline("{value}")
    def render(value: str) -> str: ...

    @js
    def runtime_helper(value: str) -> str:
        return value

    with pytest.raises(TypeError) as caught:
        render.inline(runtime_helper)

    assert str(caught.value) == (
        "An inline source generator cannot be marked @js. "
        "Use @js.inline(call=helper) to call a runtime helper."
    )


def test_inline_call_requires_a_compiled_runtime_function():
    def runtime_helper(value: str) -> str:
        return value

    with pytest.raises(TypeError) as caught:
        js.inline(call=runtime_helper)

    assert str(caught.value) == "@js.inline call target must be marked @js."


def test_inline_call_cannot_be_combined_with_source_or_references():
    @js
    def runtime_helper(value: str) -> str:
        return value

    with pytest.raises(TypeError) as caught:
        js.inline("{value}", call=runtime_helper)

    assert str(caught.value) == (
        "@js.inline requires exactly one of source or call."
    )

    with pytest.raises(TypeError) as caught:
        js.inline(call=runtime_helper, helper=runtime_helper)

    assert str(caught.value) == (
        "@js.inline(call=...) does not accept references."
    )


def test_inline_call_forwards_arguments_to_tree_shaken_runtime_function():
    at(
        """
        from pyjs import js

        @js
        def render_runtime(value: str, prefix: str = ">") -> str:
            return prefix + value

        @js.inline(call=render_runtime)
        def render(value: str, label: str = ">") -> str: ...

        def main():
            print(render("ready", label="!"))
        """,
        """
        def render_runtime(value: str, prefix: str='>') -> str:
            return prefix.[str]__add__!(value)

        def main() -> None:
            print($render_runtime('ready', prefix='!'))
        """,
        """
        const $render_runtime = render_runtime;

        export function render_runtime(value, { prefix='>'} = {}) {
            return prefix + value;
        }

        export function main() {
            console.log($render_runtime('ready', {prefix: '!'}));
        }
        """,
    )


def test_static_inline_call_keeps_receiver_reachability_and_emission():
    at(
        '''
        @js
        def helper(value: str) -> str:
            return value
        @js
        class Factory:
            @staticmethod
            @js.inline(call=helper)
            def run(value: str) -> str: ...
        @js
        def make() -> Factory:
            print("receiver")
            return Factory()
        def main() -> str:
            return make().run("value")
        ''',
        '''
        def helper(value: str) -> str:
            return value

        class Factory:

        def make() -> Factory:
            print('receiver')
            return Factory()

        def main() -> str:
            return $helper('value')
        ''',
        '''
        const $helper = helper;

        export function helper(value) {
            return value;
        }

        export class Factory {
        }

        export function make() {
            console.log('receiver');
            return new Factory();
        }

        export function main() {
            return (make(), $helper('value'));
        }
        ''',
    )


def test_static_inline_super_call_has_no_standalone_receiver():
    at(
        '''
        @js
        def helper(value: str) -> str:
            return value
        @js
        class Base:
            @staticmethod
            @js.inline(call=helper)
            def run(value: str) -> str: ...
        @js
        class Child(Base):
            def value(self) -> str:
                return super().run("value")
        def main() -> str:
            return Child().value()
        ''',
        '''
        def helper(value: str) -> str:
            return value

        class Base:

        class Child(Base):

            def value() -> str:
                return $helper('value')

        def main() -> str:
            return Child().[Child]value()
        ''',
        '''
        const $helper = helper;

        export function helper(value) {
            return value;
        }

        export class Base {
        }

        export class Child extends Base {

            value() {
                return $helper('value');
            }
        }

        export function main() {
            return new Child().value();
        }
        ''',
    )


def test_inline_call_preserves_compound_return_representations():
    at(
        """
        from pyjs import int8, js

        @js
        def runtime_values() -> list[int8]:
            return [int8(127)]

        @js.inline(call=runtime_values)
        def values() -> list[int8]: ...

        @js
        def main() -> None:
            print(values()[0] + 1)
        """,
        """
        def runtime_values() -> list[int]:
            return [int(127)]

        def main() -> None:
            print(normalize_int8($get_list_item($runtime_values(), 0).[int]__add__!(1)))
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';
        const $runtime_values = runtime_values;

        export function runtime_values() {
            return [((127 << 24) >> 24)];
        }

        export function main() {
            console.log((($get_list_item($runtime_values(), 0) + 1 << 24) >> 24));
        }
        """,
    )


def test_async_inline_call_wraps_its_result_representation():
    at(
        """
        from pyjs import int8, js

        @js
        async def runtime_value() -> int8:
            return int8(127)

        @js.inline(call=runtime_value)
        async def value() -> int8: ...

        @js
        async def main() -> None:
            print(await value() + 1)
        """,
        """
        async def runtime_value() -> int:
            return int(127)

        async def main() -> None:
            print(normalize_int8((await $runtime_value()).[int]__add__!(1)))
        """,
        """
        const $runtime_value = runtime_value;

        export async function runtime_value() {
            return ((127 << 24) >> 24);
        }

        export async function main() {
            console.log((((await $runtime_value()) + 1 << 24) >> 24));
        }
        """,
    )


def test_inline_call_target_may_add_trailing_optional_parameters():
    at(
        """
        from pyjs import js

        @js
        def render_runtime(
            value: str,
            active: list[str] | None = None,
        ) -> str:
            return value

        @js.inline(call=render_runtime)
        def render(value: str) -> str: ...

        def main():
            print(render("ready"))
        """,
        """
        def render_runtime(value: str, active: list[str] | None=None) -> str:
            return value

        def main() -> None:
            print($render_runtime('ready'))
        """,
        """
        const $render_runtime = render_runtime;

        export function render_runtime(value, { active=null} = {}) {
            return value;
        }

        export function main() {
            console.log($render_runtime('ready'));
        }
        """,
    )


def test_inline_call_reports_an_incompatible_runtime_signature():
    ad(
        """\
        from pyjs import js

        @js
        def render_runtime(value: str) -> str:
            return value

        @js.inline(call=render_runtime)
        def render(value: str, prefix: str) -> str: ...

        def main():
            print(render("ready", "!"))
        """,
        diagnostic_text(
            "inline_call.py",
            11,
            'print(render("ready", "!"))',
            "      ^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: @js.inline call target 'render_runtime' is "
            "incompatible with 'render' [PYJS2002]",
            "help: Use matching parameters, defaults, and async behavior, or "
            "use an inline source generator for a custom transformation.",
        ),
        filename="inline_call.py",
    )


def test_dispatch_requires_a_dunder_name():
    with pytest.raises(TypeError) as caught:
        js.dispatch("len")

    assert str(caught.value) == "@js.dispatch requires a dunder method name."


def test_analysis_hook_must_be_compiler_only():
    @js
    def target(value: int) -> int: ...

    with pytest.raises(TypeError) as caught:

        @target.analyze
        @js
        def analyze(call): ...

    assert str(caught.value) == (
        "A call-analysis hook cannot be marked @js because it runs only in the compiler."
    )


def test_analysis_hook_is_attached_to_its_interface():
    @js
    def target(value: int) -> int: ...

    def analyze(call):
        return call.standard()

    decorated = target.analyze(analyze)

    assert decorated is target
    assert own_js_metadata(target, "analysis") is analyze


def test_js_metadata_updates_replace_an_immutable_backend_record():
    @js
    def target(value: int) -> int:
        return value

    original = own_js_decoration(target)

    def analyze(call):
        return call.standard()

    target.analyze(analyze)
    updated = own_js_decoration(target)

    assert original is not updated
    assert original.enabled is True and original.analysis is None
    assert updated.enabled is True and updated.analysis is analyze
    assert {name for name in vars(target) if name.startswith("__js")} == {"__js__"}
    with pytest.raises(FrozenInstanceError):
        updated.enabled = False


def test_js_metadata_distinguishes_declarations_from_inherited_fields():
    @js.inline("new Base()")
    class Base:
        pass

    class Child(Base):
        pass

    def post_definition(included):
        return ""

    configure_js(Child, post_definition_source=post_definition)

    assert is_declaration(Base, "js")
    assert not is_declaration(Child, "js")
    assert is_js_enabled(Child) is True
    assert is_js_enabled(Child()) is True
    assert own_js_metadata(Child, "enabled") is None
    assert js_metadata(Child, "post_definition_source") is post_definition
    assert js_metadata(Base, "post_definition_source") is None


def test_js_runtime_attaches_metadata_without_enabling_the_interface():
    @js
    class Runtime:
        pass

    @js.runtime(Runtime)
    class Interface:
        pass

    assert is_js_enabled(Interface) is None
    assert own_js_metadata(Interface, "runtime_type") is Runtime


def test_js_implementations_cannot_replace_one_another():
    @js
    def target(value: int) -> int:
        return value

    @target.client
    def target_client(value: int) -> int:
        return value

    with pytest.raises(TypeError) as caught:
        target.source("return 1;")

    assert str(caught.value) == (
        "'test_js_implementations_cannot_replace_one_another.<locals>.target' "
        "already has a JavaScript client implementation."
    )


@pytest.mark.parametrize("item_of", [-1, True, "argument"])
def test_runtime_dunders_requires_an_item_source(item_of):
    with pytest.raises(TypeError) as caught:
        js.runtime_dunders("__eq__", item_of=item_of)

    assert str(caught.value) == (
        "@js.runtime_dunders item_of must be 'self' or an argument index."
    )


@pytest.mark.parametrize("method_names", [(), ("eq",), ("__eq__", "length")])
def test_runtime_dunders_requires_dunder_names(method_names):
    with pytest.raises(TypeError) as caught:
        js.runtime_dunders(*method_names, item_of=0)

    assert str(caught.value) == (
        "@js.runtime_dunders requires one or more dunder method names."
    )


def test_inline_function_uses_inline_call_and_runtime_value_implementations():
    at(
        """
        from pyjs import js

        @js.inline("({value} * {value})")
        def square(value: int) -> int:
            return value * value

        @square.value
        def square(value: int) -> int:
            return value * value

        @js
        def apply(callback: callable, value: int) -> object:
            return callback(value)

        def main():
            print(square(3))
            print(apply(square, 4))
        """,
        """
        def apply(callback: callable, value: int) -> object:
            return callback(value)

        def main() -> None:
            print(square(3))
            print(apply($square, 4))

        def square(value: int) -> int:
            return value.[int]__mul__!(value)
        """,
        """
        const $square = square;

        export function apply(callback, value) {
            return callback(value);
        }

        export function main() {
            console.log((3 * 3));
            console.log(apply($square, 4));
        }

        export function square(value) {
            return value * value;
        }
        """,
    )


def test_inline_class_replaces_construction_without_emitting_a_class():
    result = compile_source(
        """
from pyjs import js

@js.inline("Number({value})")
class Identifier:
    def __init__(self, value: str):
        self.value = value

@js
def main() -> Identifier:
    return Identifier("7")
""",
        filename="value_class.py",
    )

    assert (
        result.sources["value_class"]
        == """\
export function main() {
    return Number('7');
}"""
    )


def test_inline_class_retains_its_rewrite_dependencies():
    result = compile_source(
        """
from pyjs import js

@js
def normalize(value: str) -> int:
    return len(value)

@js.inline("{normalize}({value})", normalize=normalize)
class Identifier:
    def __init__(self, value: str): ...

@js
def main() -> Identifier:
    return Identifier("seven")
""",
        filename="value_class.py",
    )

    assert (
        result.sources["value_class"]
        == """\
const $normalize = normalize;

export function normalize(value) {
    return [...value].length;
}

export function main() {
    return $normalize('seven');
}"""
    )


def test_inline_class_cannot_be_used_as_a_runtime_value():
    source = """
from pyjs import js

@js.inline("Number({value})")
class Identifier:
    def __init__(self, value: str): ...

@js
def main() -> object:
    return Identifier
"""

    with pytest.raises(CompilationError) as caught:
        compile_source(source, filename="value_class.py")
    assert str(caught.value) == (
        "Inline class 'Identifier' cannot be used as a value [PYJS2003] "
        "(value_class.py, line 10)"
    )


def test_zero_argument_inline_class_needs_no_explicit_constructor():
    result = compile_source(
        """
from pyjs import js

@js.inline("0")
class Origin:
    pass

@js
def main() -> Origin:
    return Origin()
""",
        filename="value_class.py",
    )

    assert (
        result.sources["value_class"]
        == """\
export function main() {
    return 0;
}"""
    )


def test_zero_argument_inline_class_rejects_constructor_arguments():
    source = """
from pyjs import js

@js.inline("0")
class Origin:
    pass

@js
def main() -> Origin:
    return Origin(1)
"""

    with pytest.raises(CompilationError) as caught:
        compile_source(source, filename="value_class.py")
    assert str(caught.value) == (
        "__init__() received too many positional arguments [PYJS1104] "
        "(value_class.py, line 10)"
    )


def test_inline_class_cannot_be_a_runtime_base_class():
    ad(
        """
        from pyjs import js

        @js.inline("0")
        class Origin:
            pass

        @js
        class Derived(Origin):
            pass

        def main():
            Derived()
        """,
        """
          File "inline_base.py", line 9
            class Derived(Origin):
                  ^^^^^^^
        pyjs.CompilationError: Class 'Derived' cannot inherit from inline class 'Origin' [PYJS2001]
        help: Use composition, or make the base an ordinary class with runtime JavaScript identity.
        """,
        filename="inline_base.py",
        wrap=False,
    )


def test_inline_class_method_requires_a_runtime_implementation():
    ad(
        """
        from pyjs import js

        @js.inline("{value}")
        class Identifier:
            value: int

            def __init__(self, value: int):
                self.value = value

            def doubled(self) -> int:
                return self.value * 2

        def main() -> int:
            return Identifier(2).doubled()
        """,
        """
          File "inline_method.py", line 15
            return Identifier(2).doubled()
                   ^^^^^^^^^^^^^^^^^^^^^
        pyjs.CompilationError: Inline class method Identifier.doubled has no JavaScript implementation [PYJS2001]
        help: Mark the method @js.inline to lower each call, or @js.native when the inline JavaScript value provides it.
        """,
        filename="inline_method.py",
        wrap=False,
    )


def test_inline_method_as_value_binds_its_receiver_to_runtime_implementation():
    at(
        """
        from pyjs import js

        @js
        def runtime_double(instance: object, value: int) -> int:
            return value * 2

        @js
        class Doubler:
            @js.inline("({value} * 2)")
            def double(self, value: int) -> int:
                return value * 2

            double.value(runtime_double)

        @js
        def apply(callback: callable, value: int) -> object:
            return callback(value)

        def main():
            doubler = Doubler()
            print(doubler.double(3))
            print(apply(doubler.double, 4))
        """,
        """
        class Doubler:

        def apply(callback: callable, value: int) -> object:
            return callback(value)

        def main() -> None:
            doubler: Doubler = Doubler()
            print(doubler.[Doubler]double!(3))
            print(apply($double.bind(None, doubler), 4))

        def double(instance: object, value: int) -> int:
            return value.[int]__mul__!(2)
        """,
        """
        const $double = double;

        export class Doubler {
        }

        export function apply(callback, value) {
            return callback(value);
        }

        export function main() {
            var doubler = new Doubler();
            console.log((3 * 2));
            console.log(apply($double.bind(null, doubler), 4));
        }

        export function double(instance, value) {
            return value * 2;
        }
        """,
    )


def test_inline_function_without_value_implementation_has_structured_diagnostic():
    ad(
        """\
        from pyjs import js

        @js.inline("({value} * {value})")
        def square(value: int) -> int:
            return value * value

        def main():
            callback = square
        """,
        diagnostic_text(
            "inline_value.py",
            8,
            "callback = square",
            "           ^^^^^^",
            "pyjs.CompilationError: Inline function 'square' cannot be used as "
            "a value [PYJS2003]",
            "note: inline_value.py:4:5: inline function defined here",
            "help: Attach a value implementation with @square.value or "
            "square.value.source(...).",
        ),
        filename="inline_value.py",
    )


def test_inline_function_can_supply_raw_source_when_used_as_a_value():
    at(
        """
        from pyjs import js

        @js.inline("({value} * {value})")
        def square(value: int) -> int: ...

        square.value.source("return value * value;")

        @js
        def apply(callback: callable, value: int) -> object:
            return callback(value)

        def main():
            print(apply(square, 4))
        """,
        """
        def apply(callback: callable, value: int) -> object:
            return callback(value)

        def main() -> None:
            print(apply($square, 4))

        def square(value: int) -> int:
        """,
        """
        const $square = square;

        export function apply(callback, value) {
            return callback(value);
        }

        export function main() {
            console.log(apply($square, 4));
        }

        export function square(value) {
            return value * value;
        }
        """,
    )


def test_undecorated_inline_dependency_has_structured_diagnostic():
    ad(
        """\
        from pyjs import js

        def helper() -> int:
            return 1

        @js.inline("{helper}()", helper=helper)
        def wrapper() -> int: ...

        def main():
            print(wrapper())
        """,
        diagnostic_text(
            "inline_dependency.py",
            10,
            "print(wrapper())",
            "      ^^^^^^^^^",
            "pyjs.CompilationError: Inline dependency 'helper' of 'wrapper' is not "
            "available to client code [PYJS1002]",
            "note: inline_dependency.py:3:5: defined here without client "
            "compilation enabled",
            "help: Decorate 'helper' with @js.",
        ),
        filename="inline_dependency.py",
    )


def test_inline_dependency_must_emit_a_runtime_function():
    ad(
        """\
        from pyjs import js

        @js.inline("1")
        def helper() -> int: ...

        @js.inline("{helper}()", helper=helper)
        def wrapper() -> int: ...

        def main():
            print(wrapper())
        """,
        diagnostic_text(
            "inline_dependency.py",
            10,
            "print(wrapper())",
            "      ^^^^^^^^^",
            "pyjs.CompilationError: Inline dependency 'helper' of 'wrapper' does "
            "not emit a runtime function [PYJS2002]",
            "note: inline_dependency.py:4:5: inline dependency defined here",
            "help: Remove inline= from @js on 'helper', or reference a runtime function.",
        ),
        filename="inline_dependency.py",
    )


def test_unused_inline_dependencies_are_tree_shaken(monkeypatch):
    keep_for_test(monkeypatch, no_inline_dependency_entrypoint)
    package, entry_point, _ = prepare_bundle(
        no_inline_dependency_entrypoint,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_css=False,
    )

    release_compilation(entry_point)

    assert (
        package[__name__]
        == """\
function no_inline_dependency_entrypoint() {
    return 1;
}
__export_js__.no_inline_dependency_entrypoint = no_inline_dependency_entrypoint;"""
    )


def test_inline_dependency_aliases_are_local_deterministic_and_collision_free(
    monkeypatch,
):
    keep_for_test(monkeypatch, colliding_dependency_entrypoint)
    package, entry_point, _ = prepare_bundle(
        colliding_dependency_entrypoint,
        bundle_import,
        lambda name: f"__export_js__.{name} = {name};",
        include_css=False,
    )

    release_compilation(entry_point)

    assert (
        package[__name__]
        == """\
const {tag: $tag2} = __import_js__('pyjs.web.domx');
const $tag = tag;

function tag(value) {
    return value;
}
__export_js__.tag = tag;

function colliding_dependency_entrypoint(use_local) {
    if (use_local) {
        var result = ($tag('local'), $tag2('div'));
    } else {
        result = ($tag('remote'), $tag2('div'));
    }
    return result;
}
__export_js__.colliding_dependency_entrypoint = colliding_dependency_entrypoint;"""
    )


def test_bundle_can_skip_css_generation(monkeypatch):
    generate_css = Mock()
    monkeypatch.setattr("pyjs.javascript.transpiler.generate_css", generate_css)

    _, css = bundle(styled_entrypoint, include_css=False)

    assert css == ""
    generate_css.assert_not_called()
