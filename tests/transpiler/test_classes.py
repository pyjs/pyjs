import textwrap

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.testing.helpers import (
    ad,
    assert_transpile,
    at,
    diagnostic_text,
    transpile_line,
)

REPOSITORY_OVERRIDE_SOURCE = """
@js
class Repository:
    def save(self): ...

@js
class BrowserRepository(Repository):
    def save(self):
        print("browser save")
        self.helper()

    def helper(self):
        print("browser helper")

@js
class UnusedRepository(Repository):
    def save(self):
        print("unused save")

@js
def create_repository() -> Repository:
    return BrowserRepository()

@js
def save(repository: Repository):
    repository.save()
"""


def assert_reachable_repository_override(main_body: str):
    source = (
        REPOSITORY_OVERRIDE_SOURCE
        + "\ndef main():\n"
        + textwrap.indent(textwrap.dedent(main_body).strip(), "    ")
    )
    javascript = transpile_line(source)
    assert "class BrowserRepository extends Repository" in javascript
    assert "console.log('browser save');" in javascript
    assert "console.log('browser helper');" in javascript
    assert "UnusedRepository" not in javascript


def test_application_constructor_is_not_hidden_by_inherited_builtin_marker():
    assert_transpile(
        """
        from pyjs.web.domx import CustomElement
        class Base(CustomElement):
            def __init__(self, values: list[str]):
                super().__init__()
                self.values = values
        class Child(Base):
            pass
        def main() -> int:
            return len(Child([]).values)
        """,
        """
        import { CustomElement } from './pyjs.web.domx.js';

        export class Base extends CustomElement {

            _create(values) {
                super._create();
                this.values = values;
                return this;
            }

            _hydrate() {
                super._hydrate();
            }
        }
        customElements.define('pyjs-base', Base)

        export class Child extends Base {
        }
        customElements.define('pyjs-child', Child)

        export function main() {
            return new Child()._create([]).values.length;
        }
        """,
    )


def test_native_instance_fields_wait_for_their_value_types():
    at(
        """
        @js.native
        class Content:
            def text(self) -> str: ...

        @js.native
        class Response:
            def __init__(self):
                self.content = Content()

        @js.native
        def request() -> Response: ...

        def main():
            return request().content.text()
        """,
        """
        def main() -> str:
            return request().content.[Content]text()
        """,
        """
        export function main() {
            return request().content.text();
        }
        """,
    )


def test_draw_image_source_emits_nine_argument_draw_image():
    at(
        """
        from pyjs.web.html import (
            OffscreenCanvas,
            OffscreenCanvasRenderingContext2D,
            draw_image_source,
        )

        def main(
            context: OffscreenCanvasRenderingContext2D,
            image: OffscreenCanvas,
        ) -> None:
            draw_image_source(context, image, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 3.0, 4.0)
        """,
        """
        def main(context: OffscreenCanvasRenderingContext2D, image: OffscreenCanvas) -> None:
            draw_image_source(context, image, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 3.0, 4.0)
        """,
        """
        export function main(context, image) {
            context.drawImage(image, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 3.0, 4.0);
        }
        """,
    )


def test_typed_array_bytes_per_element_uses_the_javascript_size():
    at(
        """
        from pyjs.javascript import Float32Array, Uint8Array

        def main():
            width = Float32Array.BYTES_PER_ELEMENT
            values = Uint8Array(4)
            return width + values.BYTES_PER_ELEMENT
        """,
        """
        def main() -> int:
            width: int = Float32Array.BYTES_PER_ELEMENT
            values: Uint8Array = Uint8Array(4)
            return width.[int]__add__!(values.BYTES_PER_ELEMENT)
        """,
        """
        export function main() {
            var width = Float32Array.BYTES_PER_ELEMENT;
            var values = new Uint8Array(4);
            return width + (($instance) => $instance.BYTES_PER_ELEMENT === undefined ? $instance.constructor.BYTES_PER_ELEMENT : $instance.BYTES_PER_ELEMENT)(values);
        }
        """,
    )


def test_read_only_properties_emit_getters_and_retain_reachable_overrides():
    at(
        """
        @js
        class Base:
            @property
            def label(self) -> str:
                return "base"

            @property
            def unused(self) -> str:
                return "unused"

        @js
        class Child(Base):
            @property
            def label(self) -> str:
                return "child"

        def main():
            item: Base = Child()
            label = item.label
        """,
        """
        class Base:

            @property
            def label() -> str:
                return 'base'

        class Child(Base):

            @property
            def label() -> str:
                return 'child'

        def main() -> None:
            item: Base = Child()
            label: str = item.label
        """,
        """
        export class Base {

            get label() {
                return 'base';
            }
        }

        export class Child extends Base {

            get label() {
                return 'child';
            }
        }

        export function main() {
            var item = new Child();
            var label = item.label;
        }
        """,
    )


def test_read_only_property_assignment_has_a_focused_diagnostic():
    ad(
        """
        from pyjs import js

        @js
        class Person:
            @property
            def name(self) -> str:
                return "Ada"

        def main(person: Person):
            person.name = "Grace"
        """,
        """
          File "property_assignment.py", line 11
            person.name = "Grace"
            ^^^^^^^^^^^
        pyjs.CompilationError: Property 'name' is read-only [PYJS1103]
        help: Define a client-side setter on Person.
        """,
        filename="property_assignment.py",
    )


def test_property_setters_validate_values_and_emit_javascript_accessors():
    at(
        """
        @js
        class Meter:
            def __init__(self):
                self._value = 0

            @property
            def value(self) -> int:
                return self._value

            @value.setter
            def value(self, new_value: int):
                self._value = new_value

        def main(meter: Meter):
            meter.value = 3
            result = meter.value
        """,
        """
        class Meter:

            def __init__() -> None:
                self._value = 0

            @property
            def value() -> int:
                return self._value

            @value.setter
            def value(new_value: int) -> None:
                self._value = new_value

        def main(meter: Meter) -> None:
            meter.value = 3
            result: int = meter.value
        """,
        """
        export class Meter {

            constructor() {
                this._value = 0;
            }

            get value() {
                return this._value;
            }

            set value(new_value) {
                this._value = new_value;
            }
        }

        export function main(meter) {
            meter.value = 3;
            var result = meter.value;
        }
        """,
    )


def test_property_setter_rejects_incompatible_values():
    ad(
        """
        from pyjs import js

        @js
        class Meter:
            @property
            def value(self) -> int:
                return 0

            @value.setter
            def value(self, new_value: int):
                pass

        def main(meter: Meter):
            meter.value = "high"
        """,
        """
          File "property_setter.py", line 15
            meter.value = "high"
            ^^^^^^^^^^^
        pyjs.CompilationError: Cannot assign str to property 'value' [PYJS1103]
        help: Meter.value expects int.
        """,
        filename="property_setter.py",
    )


def test_property_setters_retain_reachable_overrides():
    at(
        """
        @js
        class Base:
            def __init__(self):
                self._value = 0

            @property
            def value(self) -> int:
                return self._value

            @value.setter
            def value(self, new_value: int):
                self._value = new_value

        @js
        class Child(Base):
            @property
            def value(self) -> int:
                return self._value * 2

            @value.setter
            def value(self, new_value: int):
                self._value = new_value + 1

        def main():
            item: Base = Child()
            item.value = 4
            result = item.value
        """,
        """
        class Base:

            def __init__() -> None:
                self._value = 0

            @property
            def value() -> int:
                return self._value

            @value.setter
            def value(new_value: int) -> None:
                self._value = new_value

        class Child(Base):

            @property
            def value() -> int:
                return self._value.[int]__mul__!(2)

            @value.setter
            def value(new_value: int) -> None:
                self._value = new_value.[int]__add__!(1)

        def main() -> None:
            item: Base = Child()
            item.value = 4
            result: int = item.value
        """,
        """
        export class Base {

            constructor() {
                this._value = 0;
            }

            get value() {
                return this._value;
            }

            set value(new_value) {
                this._value = new_value;
            }
        }

        export class Child extends Base {

            get value() {
                return this._value * 2;
            }

            set value(new_value) {
                this._value = new_value + 1;
            }
        }

        export function main() {
            var item = new Child();
            item.value = 4;
            var result = item.value;
        }
        """,
    )


def test_union_property_assignment_requires_every_setter_to_accept_the_value():
    ad(
        """
        from pyjs import js

        @js
        class Text:
            @property
            def value(self) -> str:
                return ""

            @value.setter
            def value(self, new_value: str):
                pass

        @js
        class Count:
            @property
            def value(self) -> int:
                return 0

            @value.setter
            def value(self, new_value: int):
                pass

        def main(item: Text | Count):
            item.value = "ready"
        """,
        """
          File "union_property_setter.py", line 25
            item.value = "ready"
            ^^^^^^^^^^
        pyjs.CompilationError: Cannot assign str to property 'value' [PYJS1103]
        help: Count.value expects int.
        """,
        filename="union_property_setter.py",
    )


def test_union_property_assignment_requires_a_setter_on_every_member():
    ad(
        """
        from pyjs import js

        @js
        class Writable:
            @property
            def value(self) -> str:
                return ""

            @value.setter
            def value(self, new_value: str):
                pass

        @js
        class ReadOnly:
            @property
            def value(self) -> str:
                return ""

        def main(item: Writable | ReadOnly):
            item.value = "ready"
        """,
        """
          File "union_read_only_property.py", line 21
            item.value = "ready"
            ^^^^^^^^^^
        pyjs.CompilationError: Property 'value' is read-only [PYJS1103]
        help: Define a client-side setter on ReadOnly.
        """,
        filename="union_read_only_property.py",
    )


def test_property_setter_requires_one_synchronous_value_parameter():
    ad(
        """
        from pyjs import js

        @js
        class Broken:
            @property
            def value(self) -> int:
                return 0

            @value.setter
            def value(self):
                pass

        def main(item: Broken):
            item.value = 1
        """,
        """
          File "property_setter_signature.py", line 15
            item.value = 1
            ^^^^^^^^^^
        pyjs.CompilationError: Property setter 'value' has an unsupported signature [PYJS2001]
        help: Define a synchronous setter as def name(self, value): ...
        """,
        filename="property_setter_signature.py",
    )


def test_union_property_reads_merge_getter_return_types():
    at(
        """
        @js
        class Text:
            @property
            def value(self) -> str:
                return "text"

        @js
        class Number:
            @property
            def value(self) -> int:
                return 3

        def main(item: Text | Number):
            value = item.value
        """,
        """
        class Text:

            @property
            def value() -> str:
                return 'text'

        class Number:

            @property
            def value() -> int:
                return 3

        def main(item: Text | Number) -> None:
            value: str | int = item.value
        """,
        """
        export class Text {

            get value() {
                return 'text';
            }
        }

        export class Number {

            get value() {
                return 3;
            }
        }

        export function main(item) {
            var value = item.value;
        }
        """,
    )


def test_property_deletion_has_a_focused_diagnostic():
    ad(
        """
        from pyjs import js

        @js
        class Person:
            @property
            def name(self) -> str:
                return "Ada"

        def main(person: Person):
            del person.name
        """,
        """
          File "property_deletion.py", line 11
            del person.name
                ^^^^^^^^^^^
        pyjs.CompilationError: property deletion is not supported [PYJS2001]
        help: Use an explicit method for client-side deletion.
        """,
        filename="property_deletion.py",
    )


def test_multiple_inheritance_has_a_focused_diagnostic():
    ad(
        """
        from pyjs import js

        @js
        class Left:
            pass

        @js
        class Right:
            pass

        @js
        class Both(Left, Right):
            pass

        def main():
            Both()
        """,
        """
          File "multiple_inheritance.py", line 13
            class Both(Left, Right):
                  ^^^^
        pyjs.CompilationError: Multiple inheritance is not supported for 'Both' [PYJS2001]
        help: Use one base class and compose the remaining behavior.
        """,
        filename="multiple_inheritance.py",
        wrap=False,
    )


def test_reachable_override_is_retained_when_subclass_is_reached_first():
    assert_reachable_repository_override(
        """
        repository = create_repository()
        save(repository)
        """
    )


def test_reachable_override_is_retained_when_base_method_is_reached_first():
    assert_reachable_repository_override("save(create_repository())")


def test_virtual_override_survives_an_unvisited_intermediate_base():
    assert_transpile(
        """
        @js
        class Base:
            def run(self):
                print("base")

        @js
        class Intermediate(Base):
            pass

        @js
        class Leaf(Intermediate):
            def run(self):
                print("leaf")

        @js
        def run(item: Base):
            item.run()

        def main():
            run(Leaf())
        """,
        """
        export class Base {

            run() {
                console.log('base');
            }
        }

        export class Intermediate extends Base {
        }

        export class Leaf extends Intermediate {

            run() {
                console.log('leaf');
            }
        }

        export function run(item) {
            item.run();
        }

        export function main() {
            run(new Leaf());
        }
        """,
    )


def test_constructor_and_super_calls_do_not_retain_grandchild_override():
    javascript = transpile_line(
        """
        @js
        class Base:
            def run(self):
                print("base")

        @js
        class Child(Base):
            def run(self):
                super().run()

        @js
        class Grandchild(Child):
            def run(self):
                print("grandchild")

        def main():
            Child().run()
            Grandchild()
        """
    )
    assert "console.log('base');" in javascript
    assert "console.log('grandchild');" not in javascript


def test_inherited_builtin_reference_retains_only_compatible_overrides():
    assert_transpile(
        """
        @js
        class Base:
            pass
        @js
        class Child(Base):
            def __str__(self) -> str:
                return 'child'
        @js
        class Other:
            def __str__(self) -> str:
                return 'unused'
        @js
        def invoke(value: Base) -> str:
            return value.__str__()
        def main() -> str:
            Other()
            invoke(Base())
            return invoke(Child())
        """,
        """
        export class Base {
        }

        export class Child extends Base {

            __str__() {
                return 'child';
            }
        }

        export class Other {
        }

        export function invoke(value) {
            return String(value);
        }

        export function main() {
            new Other();
            invoke(new Base());
            return invoke(new Child());
        }
        """,
    )


def test_generic_builtin_reference_keeps_the_authored_override():
    assert_transpile('''
        @js
        class Base:
            pass
        @js
        class Child(Base):
            def __repr__(self) -> str:
                return 'child'
        @js
        def render[T: Base](value: T) -> str:
            return value.__repr__()
        def main() -> str:
            return render(Child())
    ''', '''
        import { repr_value as $repr_value } from './pyjs.python.js';

        export class Base {
        }

        export class Child extends Base {

            __repr__() {
                return 'child';
            }
        }

        export function render(value) {
            return $repr_value(value);
        }

        export function main() {
            return render(new Child());
        }
    ''')


def test_structural_callback_argument_retains_its_interface_methods():
    assert_transpile(
        """
        from pyjs.web.events import Event, EventTarget

        @js
        class Listener:
            def handleEvent(self, event: Event):
                self.called()

            def called(self):
                print("called")

            def unused(self):
                print("unused")

        @js
        class UnusedListener:
            def handleEvent(self, event: Event):
                print("not registered")

        def main(target: EventTarget):
            listener = Listener()
            UnusedListener()
            target.addEventListener("click", listener)
        """,
        """
        export class Listener {

            handleEvent(event) {
                this.called();
            }

            called() {
                console.log('called');
            }
        }

        export class UnusedListener {
        }

        export function main(target) {
            var listener = new Listener();
            new UnusedListener();
            target.addEventListener('click', listener);
        }
        """,
    )


def test_javascript_dictionary_construction_emits_only_supplied_properties():
    assert_transpile(
        """
        @js.dictionary
        class Options:
            def __init__(
                self,
                label: str = "default",
                *,
                not_: bool | None = None,
            ):
                self.nativeLabel = label
                if not_ is not None:
                    self.not_ = not_

        def main():
            first = Options("saved", not_=True)
            empty = Options()
            print(first.nativeLabel, empty.nativeLabel)
        """,
        """
        export function main() {
            var first = {nativeLabel: 'saved', not: true};
            var empty = {nativeLabel: 'default'};
            console.log(first.nativeLabel, empty.nativeLabel);
        }
        """,
    )


def test_reachable_custom_element_retains_browser_lifecycle_methods():
    assert_transpile(
        """
        from pyjs.web.domx import CustomElement

        @js
        class Panel(CustomElement):
            def __init__(self):
                super().__init__()

            def disconnectedCallback(self):
                self.cleanup()

            def cleanup(self):
                print("cleanup")

            def unused(self):
                print("unused")

        def main():
            Panel()
        """,
        """
        import { CustomElement } from './pyjs.web.domx.js';

        export class Panel extends CustomElement {

            _create() {
                super._create();
                return this;
            }

            _hydrate() {
                super._hydrate();
            }

            disconnectedCallback() {
                this.cleanup();
            }

            cleanup() {
                console.log('cleanup');
            }
        }
        customElements.define('pyjs-panel', Panel)

        export function main() {
            new Panel()._create();
        }
        """,
    )


def test_custom_element_inline_methods_normalize_represented_results():
    assert_transpile(
        """
        from pyjs import float32, int8, int64, js
        from pyjs.web.domx import CustomElement

        @js
        class Counter(CustomElement):
            @js.inline("({value} * 2)")
            def double_int8(self, value: int8) -> int8: ...

            @js.inline("({value} / 3)")
            def divide_float32(self, value: float32) -> float32: ...

            @js.inline("({value} + 1n)")
            def increment_int64(self, value: int64) -> int64: ...

        def main():
            counter = Counter()
            first = counter.double_int8(int8(100))
            second = counter.divide_float32(float32(1.0))
            third = counter.increment_int64(int64(9223372036854775807))
            return first
        """,
        """
        import { CustomElement } from './pyjs.web.domx.js';

        export class Counter extends CustomElement {
        }
        customElements.define('pyjs-counter', Counter)

        export function main() {
            var counter = new Counter()._create();
            var first = ((((((100 << 24) >> 24) * 2))<<24)>>24);
            var second = Math.fround(((Math.fround(1.0) / 3)));
            var third = BigInt.asIntN(64,BigInt(((BigInt.asIntN(64,BigInt('9223372036854775807')) + 1n))));
            return first;
        }
        """,
    )


def test_generated_creation_and_hydration_calls_retain_their_methods():
    assert_transpile(
        """
        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, ProxyElement, ref, svg_tag

        @js
        class Field(ProxyElement):
            def _hydrate(self, element: Element):
                super()._hydrate(element)
                self.ready = True
                return self

        @js
        class Panel(CustomElement):
            def __init__(self):
                super().__init__()
                self.field = ref(Field())
                self.graph = ref(svg_tag("svg"))

        def main():
            Panel()
        """,
        """
        import { CustomElement, ProxyElement, svg_tag } from './pyjs.web.domx.js';

        export class Field extends ProxyElement {

            _hydrate(element) {
                super._hydrate(element);
                this.ready = true;
                return this;
            }
        }

        export class Panel extends CustomElement {

            _create() {
                super._create();
                this.field = new Field()._create();
                this.graph = svg_tag('svg');
                return this;
            }

            _hydrate() {
                super._hydrate();
                const self_id = this.get_data('self-id');
                this.field = new Field()._hydrate(document.getElementById(self_id+'-field'));
                this.graph = document.getElementById(self_id+'-graph');
            }
        }
        customElements.define('pyjs-panel', Panel)

        export function main() {
            new Panel()._create();
        }
        """,
    )


def test_hydration_retains_refs_wrapped_in_static_casts():
    assert_transpile(
        """
        from typing import cast

        from pyjs.web.dom import Element
        from pyjs.web.domx import CustomElement, ref, tag

        @js
        class Panel(CustomElement):
            field: Element

            def __init__(self):
                super().__init__()
                self.field = cast(Element, ref(tag("div")))

        def main():
            Panel()
        """,
        """
        import { CustomElement, tag } from './pyjs.web.domx.js';

        export class Panel extends CustomElement {

            _create() {
                super._create();
                this.field = tag('div');
                return this;
            }

            _hydrate() {
                super._hydrate();
                const self_id = this.get_data('self-id');
                this.field = document.getElementById(self_id+'-field');
            }
        }
        customElements.define('pyjs-panel', Panel)

        export function main() {
            new Panel()._create();
        }
        """,
    )


def test_generic_classmethod_uses_the_inferred_concrete_class():
    assert_transpile(
        '''
        @js
        class Box[T]:
            def __init__(self, value: T):
                self.value = value
            @classmethod
            def create(cls, value: T) -> 'Box[T]':
                return cls(value)
        def main() -> str:
            return Box.create('ok').value
        ''',
        '''
        export class Box__str {

            constructor(value) {
                this.value = value;
            }

            static create(value) {
                return new this(value);
            }
        }

        export function main() {
            return Box__str.create('ok').value;
        }
        ''',
    )


def test_self_return_annotations_follow_the_concrete_receiver_type():
    at(
        """
        from typing import Self

        @js
        class Builder:
            @classmethod
            def create(cls) -> Self:
                return cls()

            def rename(self) -> Self:
                return self

        @js
        class Child(Builder):
            pass

        def main():
            child = Child.create()
            renamed = child.rename()
        """,
        """
        class Builder:

            def create() -> Builder:
                return this()

            def rename() -> Builder:
                return self

        class Child(Builder):

        def main() -> None:
            child: Child = Child.[Builder]create()
            renamed: Child = child.[Builder]rename()
        """,
        """
        export class Builder {

            static create() {
                return new this();
            }

            rename() {
                return this;
            }
        }

        export class Child extends Builder {
        }

        export function main() {
            var child = Child.create();
            var renamed = child.rename();
        }
        """,
    )


def test_self_parameter_annotations_require_the_concrete_receiver_type():
    at(
        """
        from typing import Self

        @js
        class Token:
            def same(self, other: Self) -> bool:
                return self is other

        def main() -> bool:
            token = Token()
            return token.same(token)
        """,
        """
        class Token:

            def same(other: Token) -> bool:
                return self.[object]__is__!(other)

        def main() -> bool:
            token: Token = Token()
            return token.[Token]same(token)
        """,
        """
        export class Token {

            same(other) {
                return this === other;
            }
        }

        export function main() {
            var token = new Token();
            return token.same(token);
        }
        """,
    )


def test_self_return_keeps_concrete_typed_array_views():
    at(
        """
        from pyjs.javascript import Uint8Array
        from pyjs.web.encoding import TextDecoder

        def main(values: Uint8Array) -> str:
            selected = values.subarray(1)
            copied = values.slice(0, 1)
            return (
                TextDecoder().decode(selected)
                + TextDecoder().decode(copied)
            )
        """,
        """
        def main(values: Uint8Array) -> str:
            selected: Uint8Array = values.[TypedArray]subarray(1)
            copied: Uint8Array = values.[TypedArray]slice(0, 1)
            return TextDecoder().[TextDecoder]decode(selected).[str]__add__!(TextDecoder().[TextDecoder]decode(copied))
        """,
        """
        export function main(values) {
            var selected = values.subarray(1);
            var copied = values.slice(0, 1);
            return new TextDecoder().decode(selected) + new TextDecoder().decode(copied);
        }
        """,
    )


def test_self_return_annotation_requires_a_method():
    ad(
        """\
        from typing import Self
        from pyjs import js

        @js
        def make() -> Self:
            return make()
        """,
        diagnostic_text(
            "self_return.py",
            5,
            "def make() -> Self:",
            "              ^^^^",
            "pyjs.CompilationError: Self return annotations are only valid on "
            "methods [PYJS2001]",
            "help: Return a concrete type or move this function onto a class.",
        ),
        filename="self_return.py",
    )


def test_instance_method_calls_overridden_static_method_through_runtime_class():
    assert_transpile(
        """
        @js
        class Base:
            @staticmethod
            def value() -> str:
                return "base"

            def current(self) -> str:
                return self.value()

        @js
        class Child(Base):
            @staticmethod
            def value() -> str:
                return "child"

        def main():
            print(Child().current())
        """,
        """
        export class Base {

            static value() {
                return 'base';
            }

            current() {
                return this.constructor.value();
            }
        }

        export class Child extends Base {

            static value() {
                return 'child';
            }
        }

        export function main() {
            console.log(new Child().current());
        }
        """,
    )


def test_instance_method_reads_overridden_class_field_through_runtime_class():
    assert_transpile(
        """
        @js
        class Base:
            label = "base"

            def current(self) -> str:
                return self.label

            def override(self, label: str) -> None:
                self.label = label

        @js
        class Middle(Base):
            label: str

        @js
        class Child(Middle):
            label = "child"

        @js
        class Unused(Base):
            label = "unused"

        def main():
            print(Base().current())
            print(Child().current())
            item: Base = Child()
            print(item.label)
            item.override("instance")
            print(item.label)
        """,
        """
        export class Base {
            static label = 'base';

            current() {
                return (($instance) => $instance.label === undefined ? $instance.constructor.label : $instance.label)(this);
            }

            override(label) {
                this.label = label;
            }
        }

        export class Middle extends Base {
        }

        export class Child extends Middle {
            static label = 'child';
        }

        export function main() {
            console.log(new Base().current());
            console.log(new Child().current());
            var item = new Child();
            console.log((($instance) => $instance.label === undefined ? $instance.constructor.label : $instance.label)(item));
            item.override('instance');
            console.log((($instance) => $instance.label === undefined ? $instance.constructor.label : $instance.label)(item));
        }
        """,
    )


def test_annotation_only_base_field_uses_a_reachable_subclass_default():
    assert_transpile(
        """
        @js
        class Base:
            label: str

            def current(self) -> str:
                return self.label

        @js
        class Child(Base):
            label = "child"

        @js
        class Unused(Base):
            label = "unused"

        def main():
            print(Child().current())
        """,
        """
        export class Base {

            current() {
                return (($instance) => $instance.label === undefined ? $instance.constructor.label : $instance.label)(this);
            }
        }

        export class Child extends Base {
            static label = 'child';
        }

        export function main() {
            console.log(new Child().current());
        }
        """,
    )


def test_direct_inherited_field_read_retains_a_compatible_subclass_default():
    assert_transpile(
        """
        @js
        class Base:
            value: object

        @js
        class Child(Base):
            value = "ready"

        def main():
            print(Child().value)
        """,
        """
        export class Base {
        }

        export class Child extends Base {
            static value = 'ready';
        }

        export function main() {
            console.log((($instance) => $instance.value === undefined ? $instance.constructor.value : $instance.value)(new Child()));
        }
        """,
    )


def test_bounded_generic_field_preserves_a_compatible_subclass_type():
    assert_transpile(
        """
        @js
        class Animal:
            def __init__(self, name: str):
                self.name = name

        @js
        class Dog(Animal):
            def bark(self) -> str:
                return "woof"

        @js
        class Holder[T: Animal]:
            animal: T

        @js
        class DogHolder(Holder[Dog]):
            animal = Dog("Spot")

        def main():
            print(DogHolder().animal.bark())
        """,
        """
        export class Animal {

            constructor(name) {
                this.name = name;
            }
        }

        export class Dog extends Animal {

            bark() {
                return 'woof';
            }
        }

        export class Holder__Dog {
        }

        export class DogHolder extends Holder__Dog {
            static animal = new Dog('Spot');
        }

        export function main() {
            console.log((($instance) => $instance.animal === undefined ? $instance.constructor.animal : $instance.animal)(new DogHolder()).bark());
        }
        """,
    )


def test_inherited_field_rejects_an_incompatible_subclass_default():
    ad(
        """\
        from pyjs import js

        @js
        class Parent:
            label: str

        @js
        class Middle(Parent):
            pass

        @js
        class Child(Middle):
            label = 42

        def main():
            print(Child().label)
        """,
        diagnostic_text(
            "inherited_field.py",
            13,
            "label = 42",
            "        ^^",
            "pyjs.CompilationError: Cannot assign int to inherited field "
            "'Child.label' of type str [PYJS1103]",
            "note: inherited_field.py:5:12: Parent.label is declared as str here",
            "help: Assign a value compatible with str or change the declaration "
            "of Parent.label.",
        ),
        filename="inherited_field.py",
    )


def test_specialized_generic_field_rejects_a_base_class_default():
    ad(
        """\
        from pyjs import js

        @js
        class Animal:
            def __init__(self, name: str):
                self.name = name

        @js
        class Dog(Animal):
            pass

        @js
        class Holder[T: Animal]:
            animal: T

        @js
        class DogHolder(Holder[Dog]):
            animal = Animal("not a dog")

        def main():
            print(DogHolder().animal.name)
        """,
        diagnostic_text(
            "generic_field.py",
            18,
            'animal = Animal("not a dog")',
            "         ^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Cannot assign Animal to inherited field "
            "'DogHolder.animal' of type Dog [PYJS1103]",
            "note: generic_field.py:14:13: Holder[Dog].animal is declared as Dog here",
            "help: Assign a value compatible with Dog or change the declaration "
            "of Holder[Dog].animal.",
        ),
        filename="generic_field.py",
    )


def test_inherited_classvar_rejects_an_incompatible_subclass_default():
    ad(
        """\
        from typing import ClassVar

        from pyjs import js

        @js
        class Parent:
            label: ClassVar[str] = "parent"

        @js
        class Child(Parent):
            label = 42

        def main():
            print(Child().label)
        """,
        diagnostic_text(
            "inherited_classvar.py",
            11,
            "label = 42",
            "        ^^",
            "pyjs.CompilationError: Cannot assign int to inherited field "
            "'Child.label' of type str [PYJS1103]",
            "note: inherited_classvar.py:7:12: Parent.label is declared as str here",
            "help: Assign a value compatible with str or change the declaration "
            "of Parent.label.",
        ),
        filename="inherited_classvar.py",
    )


def test_subclass_field_annotation_must_preserve_the_inherited_contract():
    ad(
        """\
        from pyjs import js

        @js
        class Parent:
            label: str

        @js
        class Child(Parent):
            label: int = 1

        def main():
            print(Child().label)
        """,
        diagnostic_text(
            "inherited_annotation.py",
            9,
            "label: int = 1",
            "       ^^^",
            "pyjs.CompilationError: Cannot override inherited field "
            "'Child.label' of type str with int [PYJS1103]",
            "note: inherited_annotation.py:5:12: Parent.label is declared as str here",
            "help: Use a type compatible with str or change the declaration "
            "of Parent.label.",
        ),
        filename="inherited_annotation.py",
    )


def test_annotated_class_field_checks_its_own_default():
    ad(
        """\
        from pyjs import js

        @js
        class Parent:
            label: str = 42

        def main():
            print(Parent().label)
        """,
        diagnostic_text(
            "class_field.py",
            5,
            "label: str = 42",
            "             ^^",
            "pyjs.CompilationError: Cannot assign int to class field "
            "'Parent.label' of type str [PYJS1103]",
            "help: Assign a value compatible with str or change the declaration "
            "of Parent.label.",
        ),
        filename="class_field.py",
    )


def test_initialize_declares_client_only_instance_fields_before_other_methods():
    at(
        """
        @js
        class Widget:
            def initialize(self):
                self.listener = Listener()

            def open(self) -> str:
                return self.listener.label

        @js
        class Listener:
            def __init__(self):
                self.label = "ready"

        def main():
            widget = Widget()
            widget.initialize()
            print(widget.open())
        """,
        """
        class Widget:

            def initialize() -> None:
                self.listener = Listener()

            def open() -> str:
                return self.listener.label

        class Listener:

            def __init__() -> None:
                self.label = 'ready'

        def main() -> None:
            widget: Widget = Widget()
            widget.[Widget]initialize()
            print(widget.[Widget]open())
        """,
        """
        export class Widget {

            initialize() {
                this.listener = new Listener();
            }

            open() {
                return this.listener.label;
            }
        }

        export class Listener {

            constructor() {
                this.label = 'ready';
            }
        }

        export function main() {
            var widget = new Widget();
            widget.initialize();
            console.log(widget.open());
        }
        """,
    )


def test_subclass_is_compatible_with_base_class_annotation():
    at(
        """
        @js
        class View:
            pass

        @js
        class StackLayout(View):
            pass

        @js
        class Page:
            def __init__(self):
                self.content = View()

        @js
        def create_view() -> View:
            return StackLayout()

        def main():
            page = Page()
            page.content = StackLayout()
            view = create_view()
        """,
        """
        class View:

        class StackLayout(View):

        class Page:

            def __init__() -> None:
                self.content = View()

        def create_view() -> View:
            return StackLayout()

        def main() -> None:
            page: Page = Page()
            page.content = StackLayout()
            view: View = create_view()
        """,
        """
        export class View {
        }

        export class StackLayout extends View {
        }

        export class Page {

            constructor() {
                this.content = new View();
            }
        }

        export function create_view() {
            return new StackLayout();
        }

        export function main() {
            var page = new Page();
            page.content = new StackLayout();
            var view = create_view();
        }
        """,
    )


def test_subclass_field_specializes_inherited_field():
    at(
        """
        @js
        class Element:
            pass

        @js
        class InputElement(Element):
            def __init__(self):
                self.value = ""

        @js
        class Proxy:
            def __init__(self):
                self.element = Element()

        @js
        class Input(Proxy):
            def __init__(self):
                self.element = InputElement()

            def get_value(self) -> str:
                return self.element.value

        def main():
            return Input().get_value()
        """,
        """
        class Element:

        class InputElement(Element):

            def __init__() -> None:
                self.value = ''

        class Proxy:

        class Input(Proxy):

            def __init__() -> None:
                self.element = InputElement()

            def get_value() -> str:
                return self.element.value

        def main() -> str:
            return Input().[Input]get_value()
        """,
        """
        export class Element {
        }

        export class InputElement extends Element {

            constructor() {
                this.value = '';
            }
        }

        export class Proxy {
        }

        export class Input extends Proxy {

            constructor() {
                this.element = new InputElement();
            }

            get_value() {
                return this.element.value;
            }
        }

        export function main() {
            return new Input().get_value();
        }
        """,
    )


def test_annotated_optional_instance_field_accepts_concrete_assignment():
    at(
        """
        from pyjs.web.html import HTMLElement

        @js
        class Viewer:
            def __init__(self):
                self.currentFrame: HTMLElement | None = None
                self.currentFrame = HTMLElement()
                self.currentFrame = None

        def main():
            Viewer()
        """,
        """
        class Viewer:

            def __init__() -> None:
                self.currentFrame: HTMLElement | None = None
                self.currentFrame = HTMLElement()
                self.currentFrame = None

        def main() -> None:
            Viewer()
        """,
        """
        export class Viewer {

            constructor() {
                this.currentFrame = null;
                this.currentFrame = new HTMLElement();
                this.currentFrame = null;
            }
        }

        export function main() {
            new Viewer();
        }
        """,
    )


def test_optional_instance_field_narrows_after_none_check():
    at(
        """
        from pyjs.web.html import HTMLElement

        @js
        class Viewer:
            def __init__(self):
                self.currentFrame: HTMLElement | None = None

            @js.keep
            def clear(self):
                current_frame = self.currentFrame
                if current_frame is not None:
                    current_frame.classList.remove("active")
                if self.currentFrame is not None:
                    self.currentFrame.classList.remove("compact")

        def main():
            viewer = Viewer()
            viewer.clear()
        """,
        """
        class Viewer:

            def __init__() -> None:
                self.currentFrame: HTMLElement | None = None

            def clear() -> None:
                current_frame: HTMLElement | None = self.currentFrame
                if current_frame.[object]__is_not__!(None):
                    current_frame.classList.[DOMTokenList]remove('active')
                if self.currentFrame.[object]__is_not__!(None):
                    self.currentFrame.classList.[DOMTokenList]remove('compact')

        def main() -> None:
            viewer: Viewer = Viewer()
            viewer.[Viewer]clear()
        """,
        """
        export class Viewer {

            constructor() {
                this.currentFrame = null;
            }

            clear() {
                var current_frame = this.currentFrame;
                if (current_frame != null) {
                    current_frame.classList.remove('active');
                }
                if (this.currentFrame != null) {
                    this.currentFrame.classList.remove('compact');
                }
            }
        }

        export function main() {
            var viewer = new Viewer();
            viewer.clear();
        }
        """,
    )


def test_instance_attribute_on_function_call_result():
    at(
        """
        @js
        class Base:
            def __init__(self):
                self.things = ['a']
        @js
        def make_base():
            return Base()
        def main():
            direct = Base().things[0]
            indirect = make_base().things[0]
        """,
        """
        class Base:

            def __init__() -> None:
                self.things = ['a']

        def make_base() -> Base:
            return Base()

        def main() -> None:
            direct: str = $get_list_item(Base().things, 0)
            indirect: str = $get_list_item(make_base().things, 0)
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Base {

            constructor() {
                this.things = ['a'];
            }
        }

        export function make_base() {
            return new Base();
        }

        export function main() {
            var direct = $get_list_item(new Base().things, 0);
            var indirect = $get_list_item(make_base().things, 0);
        }
        """,
    )


def test_super_init_transpiles_after_transient_call_fix():
    at(
        """
        @js
        class Base:
            def __init__(self):
                pass
        @js
        class Child(Base):
            def __init__(self):
                super().__init__()
        def main():
            Child()
        """,
        """
        class Base:

            def __init__() -> None:
                pass

        class Child(Base):

            def __init__() -> None:
                super().[Base]__init__()

        def main() -> None:
            Child()
        """,
        """
        export class Base {

            constructor() {
            }
        }

        export class Child extends Base {

            constructor() {
                super();
            }
        }

        export function main() {
            new Child();
        }
        """,
    )


def test_instance_attribute_on_subscript_result():
    at(
        """
        @js
        class Entry:
            def __init__(self, nodeid: str):
                self.nodeid = nodeid
        def main():
            entries = [Entry("a")]
            nodeid = entries[0].nodeid
        """,
        """
        class Entry:

            def __init__(nodeid: str) -> None:
                self.nodeid = nodeid

        def main() -> None:
            entries: list[Entry] = [Entry('a')]
            nodeid: str = $get_list_item(entries, 0).nodeid
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Entry {

            constructor(nodeid) {
                this.nodeid = nodeid;
            }
        }

        export function main() {
            var entries = [new Entry('a')];
            var nodeid = $get_list_item(entries, 0).nodeid;
        }
        """,
    )


def test_union_typed_receivers_expose_common_fields():
    at(
        """
        from pyjs import js

        @js
        class TextValue:
            def __init__(self):
                self.value = "ready"
                self.shared = "text"

        @js
        class CountValue:
            def __init__(self):
                self.value = 3
                self.shared = "count"

        @js
        class TextBox:
            def __init__(self):
                self.item = TextValue()

        @js
        class CountBox:
            def __init__(self):
                self.item = CountValue()

        @js
        def read(item: TextValue | CountValue):
            return item.value

        @js
        def read_shared(item: TextValue | CountValue):
            return item.shared

        @js
        def read_nested(box: TextBox | CountBox):
            return box.item.value

        @js
        def read_optional(item: TextValue | None) -> str:
            if item is None:
                return "missing"
            return item.value

        @js
        def update_text(item: TextValue | CountValue):
            if not isinstance(item, TextValue):
                return
            item.value = "updated"

        def main():
            direct = read(TextValue())
            shared = read_shared(CountValue())
            nested_text = read_nested(TextBox())
            nested_count = read_nested(CountBox())
            optional = read_optional(TextValue())
            update_text(TextValue())
        """,
        """
        class TextValue:

            def __init__() -> None:
                self.value = 'ready'
                self.shared = 'text'

        class CountValue:

            def __init__() -> None:
                self.value = 3
                self.shared = 'count'

        class TextBox:

            def __init__() -> None:
                self.item = TextValue()

        class CountBox:

            def __init__() -> None:
                self.item = CountValue()

        def read(item: TextValue | CountValue) -> str | int:
            return item.value

        def read_shared(item: TextValue | CountValue) -> str:
            return item.shared

        def read_nested(box: TextBox | CountBox) -> str | int:
            return box.item.value

        def read_optional(item: TextValue | None) -> str:
            if item.[object]__is__!(None):
                return 'missing'
            return item.value

        def update_text(item: TextValue | CountValue) -> None:
            if not isinstance(item, TextValue):
                return
            item.value = 'updated'

        def main() -> None:
            direct: str | int = read(TextValue())
            shared: str = read_shared(CountValue())
            nested_text: str | int = read_nested(TextBox())
            nested_count: str | int = read_nested(CountBox())
            optional: str = read_optional(TextValue())
            update_text(TextValue())
        """,
        """
        export class TextValue {

            constructor() {
                this.value = 'ready';
                this.shared = 'text';
            }
        }

        export class CountValue {

            constructor() {
                this.value = 3;
                this.shared = 'count';
            }
        }

        export class TextBox {

            constructor() {
                this.item = new TextValue();
            }
        }

        export class CountBox {

            constructor() {
                this.item = new CountValue();
            }
        }

        export function read(item) {
            return item.value;
        }

        export function read_shared(item) {
            return item.shared;
        }

        export function read_nested(box) {
            return box.item.value;
        }

        export function read_optional(item) {
            if (item == null) {
                return 'missing';
            }
            return item.value;
        }

        export function update_text(item) {
            if (!((item instanceof TextValue))) {
                return;
            }
            item.value = 'updated';
        }

        export function main() {
            var direct = read(new TextValue());
            var shared = read_shared(new CountValue());
            var nested_text = read_nested(new TextBox());
            var nested_count = read_nested(new CountBox());
            var optional = read_optional(new TextValue());
            update_text(new TextValue());
        }
        """,
    )


def test_union_field_reads_work_on_call_and_subscript_results():
    at(
        """
        from pyjs import js

        @js
        class TextValue:
            def __init__(self):
                self.value = "ready"

        @js
        class CountValue:
            def __init__(self):
                self.value = 3

        @js
        def choose(text: bool) -> TextValue | CountValue:
            if text:
                return TextValue()
            return CountValue()

        @js
        def read_call(text: bool):
            return choose(text).value

        @js
        def read_first(values: list[TextValue | CountValue]):
            return values[0].value

        def main():
            called = read_call(True)
            first = read_first([CountValue(), TextValue()])
        """,
        """
        class TextValue:

            def __init__() -> None:
                self.value = 'ready'

        class CountValue:

            def __init__() -> None:
                self.value = 3

        def choose(text: bool) -> TextValue | CountValue:
            if text:
                return TextValue()
            return CountValue()

        def read_call(text: bool) -> str | int:
            return choose(text).value

        def read_first(values: list__TextValueUCountValue) -> str | int:
            return $get_list_item(values, 0).value

        def main() -> None:
            called: str | int = read_call(True)
            first: str | int = read_first([CountValue(), TextValue()])
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class TextValue {

            constructor() {
                this.value = 'ready';
            }
        }

        export class CountValue {

            constructor() {
                this.value = 3;
            }
        }

        export function choose(text) {
            if (text) {
                return new TextValue();
            }
            return new CountValue();
        }

        export function read_call(text) {
            return choose(text).value;
        }

        export function read_first(values) {
            return $get_list_item(values, 0).value;
        }

        export function main() {
            var called = read_call(true);
            var first = read_first([new CountValue(), new TextValue()]);
        }
        """,
    )


def test_union_typed_receivers_call_compatible_methods():
    at(
        """
        from pyjs import js

        @js
        class TextValue:
            def render(self, prefix: str) -> str:
                return prefix + "text"

        @js
        class CountValue:
            def render(self, prefix: object) -> int:
                print(prefix)
                return 3

        @js
        def render(item: TextValue | CountValue):
            return item.render("value: ")

        def main():
            text = render(TextValue())
            count = render(CountValue())
        """,
        """
        class TextValue:

            def render(prefix: str) -> str:
                return prefix.[str]__add__!('text')

        class CountValue:

            def render(prefix: object) -> int:
                print(prefix)
                return 3

        def render(item: TextValue | CountValue) -> str | int:
            return item.[TextValue]render('value: ')

        def main() -> None:
            text: str | int = render(TextValue())
            count: str | int = render(CountValue())
        """,
        """
        export class TextValue {

            render(prefix) {
                return prefix + 'text';
            }
        }

        export class CountValue {

            render(prefix) {
                console.log(prefix);
                return 3;
            }
        }

        export function render(item) {
            return item.render('value: ');
        }

        export function main() {
            var text = render(new TextValue());
            var count = render(new CountValue());
        }
        """,
    )


def test_dunder_builtins_dispatch_across_union_typed_receivers():
    at(
        """
        from pyjs import js

        @js
        class Left:
            def __str__(self) -> str:
                return "left"

        @js
        class Right:
            def __str__(self) -> str:
                return "right"

        @js
        def render(value: Left | Right) -> str:
            return str(value)

        def main():
            print(render(Left()))
            print(render(Right()))
        """,
        """
        class Left:

            def __str__() -> str:
                return 'left'

        class Right:

            def __str__() -> str:
                return 'right'

        def render(value: Left | Right) -> str:
            return value.[Left]__str__()

        def main() -> None:
            print(render(Left()))
            print(render(Right()))
        """,
        """
        export class Left {

            __str__() {
                return 'left';
            }
        }

        export class Right {

            __str__() {
                return 'right';
            }
        }

        export function render(value) {
            return value.__str__();
        }

        export function main() {
            console.log(render(new Left()));
            console.log(render(new Right()));
        }
        """,
    )


def test_union_typed_receivers_update_common_fields():
    at(
        """
        from pyjs import js

        @js
        class Left:
            def __init__(self):
                self.value = 1

        @js
        class Right:
            def __init__(self):
                self.value: int | None = 2

        @js
        class LeftBox:
            def __init__(self):
                self.item = Left()

        @js
        class RightBox:
            def __init__(self):
                self.item = Right()

        @js
        def update(item: Left | Right):
            item.value = 3

        @js
        def update_nested(box: LeftBox | RightBox):
            box.item.value = 4

        @js
        def choose(left: bool) -> Left | Right:
            if left:
                return Left()
            return Right()

        @js
        def update_call(left: bool):
            choose(left).value = 5

        @js
        def update_first(items: list[Left | Right]):
            items[0].value = 6

        @js
        def increment(item: Left | Right):
            if item.value is None:
                return
            item.value += 1

        def main():
            left = Left()
            right = Right()
            update(left)
            update(right)
            update_nested(LeftBox())
            update_nested(RightBox())
            update_call(True)
            update_first([Left(), Right()])
            increment(left)
            increment(right)
        """,
        """
        class Left:

            def __init__() -> None:
                self.value = 1

        class Right:

            def __init__() -> None:
                self.value: int | None = 2

        class LeftBox:

            def __init__() -> None:
                self.item = Left()

        class RightBox:

            def __init__() -> None:
                self.item = Right()

        def update(item: Left | Right) -> None:
            item.value = 3

        def update_nested(box: LeftBox | RightBox) -> None:
            box.item.value = 4

        def choose(left: bool) -> Left | Right:
            if left:
                return Left()
            return Right()

        def update_call(left: bool) -> None:
            choose(left).value = 5

        def update_first(items: list__LeftURight) -> None:
            $get_list_item(items, 0).value = 6

        def increment(item: Left | Right) -> None:
            if item.value.[object]__is__!(None):
                return
            $assignment1: Left | Right = item
            $assignment1.value = $assignment1.value.[int]__add__!(1)

        def main() -> None:
            left: Left = Left()
            right: Right = Right()
            update(left)
            update(right)
            update_nested(LeftBox())
            update_nested(RightBox())
            update_call(True)
            update_first([Left(), Right()])
            increment(left)
            increment(right)
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Left {

            constructor() {
                this.value = 1;
            }
        }

        export class Right {

            constructor() {
                this.value = 2;
            }
        }

        export class LeftBox {

            constructor() {
                this.item = new Left();
            }
        }

        export class RightBox {

            constructor() {
                this.item = new Right();
            }
        }

        export function update(item) {
            item.value = 3;
        }

        export function update_nested(box) {
            box.item.value = 4;
        }

        export function choose(left) {
            if (left) {
                return new Left();
            }
            return new Right();
        }

        export function update_call(left) {
            choose(left).value = 5;
        }

        export function update_first(items) {
            $get_list_item(items, 0).value = 6;
        }

        export function increment(item) {
            if (item.value == null) {
                return;
            }
            var $assignment1 = item;
            $assignment1.value = $assignment1.value + 1;
        }

        export function main() {
            var left = new Left();
            var right = new Right();
            update(left);
            update(right);
            update_nested(new LeftBox());
            update_nested(new RightBox());
            update_call(true);
            update_first([new Left(), new Right()]);
            increment(left);
            increment(right);
        }
        """,
    )


def test_render_pipeline_omits_absent_depth_stencil():
    assert_transpile(
        """
        from pyjs.web.webgpu import (
            GPUColorTargetState,
            GPUFragmentState,
            GPUPrimitiveState,
            GPURenderPipelineDescriptor,
            GPUShaderModule,
            GPUVertexState,
        )

        def main(shader: GPUShaderModule) -> GPURenderPipelineDescriptor:
            return GPURenderPipelineDescriptor(
                GPUVertexState(shader, "vs", []),
                GPUFragmentState(shader, "fs", [GPUColorTargetState("rgba8unorm")]),
                GPUPrimitiveState(cull_mode="none"),
                None,
            )
        """,
        """
        export function main(shader) {
            return {vertex: {module: shader, entryPoint: 'vs', buffers: []}, fragment: {module: shader, entryPoint: 'fs', targets: [{format: 'rgba8unorm', writeMask: 15}]}, primitive: {cullMode: 'none', topology: 'triangle-list', frontFace: 'ccw', unclippedDepth: false}, layout: 'auto', label: ''};
        }
        """,
    )


def test_optional_dictionary_members_are_absent_when_none():
    assert_transpile(
        """
        from pyjs.web.webgpu import GPUBlendState, GPUColorTargetState

        @js
        def target(
            fmt: str,
            blend: GPUBlendState | None,
        ) -> GPUColorTargetState:
            return GPUColorTargetState(fmt, blend=blend)

        def main() -> None:
            target('rgba8unorm', None)
        """,
        """
        export function target(fmt, blend) {
            return {format: fmt, ...(blend != null ? {blend: blend} : {}), writeMask: 15};
        }

        export function main() {
            target('rgba8unorm', null);
        }
        """,
    )


def test_optional_dictionary_expression_is_evaluated_once():
    assert_transpile(
        """
        from pyjs.web.webgpu import GPUBlendState, GPUColorTargetState

        @js
        def choose_blend() -> GPUBlendState | None:
            return None

        def main() -> GPUColorTargetState:
            return GPUColorTargetState(
                'rgba8unorm',
                blend=choose_blend(),
            )
        """,
        """
        export function choose_blend() {
            return null;
        }

        export function main() {
            return {format: 'rgba8unorm', ...((value)=>value != null ? {blend: value} : {})(choose_blend()), writeMask: 15};
        }
        """,
    )


def test_explicit_none_dictionary_member_does_not_leave_a_separator():
    assert_transpile(
        """
        @js.dictionary
        class Options:
            def __init__(
                self,
                first: int,
                optional: int | None = None,
                last: int = 3,
            ):
                self.first = first
                if optional is not None:
                    self.optional = optional
                self.last = last

        def main():
            Options(1, optional=None, last=4)
        """,
        """
        export function main() {
            {first: 1, last: 4};
        }
        """,
    )


def test_a_property_implementing_a_base_annotation_is_emitted():
    assert_transpile(
        """
        @js
        class Base:
            aperture: float

            def f(self) -> float:
                return self.aperture

        @js
        class Impl(Base):
            def __init__(self, k: float) -> None:
                super().__init__()
                self.k = k

            @property
            def aperture(self) -> float:
                return self.k * 2

        def main() -> float:
            return Impl(2.0).f()
        """,
        """
        export class Base {

            f() {
                return this.aperture;
            }
        }

        export class Impl extends Base {

            constructor(k) {
                super();
                this.k = k;
            }

            get aperture() {
                return this.k * 2;
            }
        }

        export function main() {
            return new Impl(2.0).f();
        }
        """,
    )


def test_constructor_can_call_initialize_to_declare_fields():
    assert_transpile(
        """
        @js
        class Widget:
            def __init__(self):
                self.initialize()

            def initialize(self) -> None:
                self.value = 42

            def read(self) -> int:
                return self.value

        def main():
            print(Widget().read())
        """,
        """
        export class Widget {

            constructor() {
                this.initialize();
            }

            initialize() {
                this.value = 42;
            }

            read() {
                return this.value;
            }
        }

        export function main() {
            console.log(new Widget().read());
        }
        """,
    )


def test_constructor_and_initialize_can_declare_separate_fields():
    assert_transpile(
        """
        @js
        class Widget:
            def __init__(self):
                self.label = "ready"
                self.initialize()

            def initialize(self) -> None:
                self.values: list[int] = []
                self.enabled = True

            def read(self) -> str:
                self.values.append(42)
                return self.label if self.enabled else "disabled"

        def main():
            print(Widget().read())
        """,
        """
        export class Widget {

            constructor() {
                this.label = 'ready';
                this.initialize();
            }

            initialize() {
                this.values = [];
                this.enabled = true;
            }

            read() {
                (this.values.push(42), null);
                return this.enabled ? this.label : 'disabled';
            }
        }

        export function main() {
            console.log(new Widget().read());
        }
        """,
    )


def test_initialize_writes_still_check_constructor_field_types():
    with pytest.raises(CompilationError, match="Cannot assign str.*int"):
        transpile_line(
            """
            @js
            class Widget:
                def __init__(self):
                    self.count: int = 0
                    self.initialize()

                def initialize(self) -> None:
                    self.count = "wrong"

            def main():
                print(Widget().count)
            """
        )


def test_initialize_reads_do_not_hide_a_real_dependency_cycle():
    with pytest.raises(CompilationError, match="dependency cycle"):
        transpile_line(
            """
            @js
            class Widget:
                def __init__(self):
                    self.first = self.second
                    self.initialize()

                def initialize(self) -> None:
                    self.second = self.first

            def main():
                print(Widget().first)
            """
        )


def test_initialize_empty_container_waits_for_constructor_element_type():
    assert_transpile(
        """
        @js
        class Widget:
            def initialize(self) -> None:
                self.items = []

            def __init__(self):
                self.items: list[int] = [1]

        def main():
            widget = Widget()
            widget.initialize()
            widget.items.append(42)
            print(widget.items[0])
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export class Widget {

            initialize() {
                this.items = [];
            }

            constructor() {
                this.items = [1];
            }
        }

        export function main() {
            var widget = new Widget();
            widget.initialize();
            (widget.items.push(42), null);
            console.log($get_list_item(widget.items, 0));
        }
        """,
    )


def test_initialize_reset_preserves_constructor_optional_field_type():
    assert_transpile(
        """
        @js
        class Controller:
            def abort(self) -> int:
                return 42

        @js
        class Widget:
            def initialize(self) -> None:
                self.controller = None

            def __init__(self):
                self.controller: Controller | None = None

            def stop(self) -> int:
                if self.controller is not None:
                    return self.controller.abort()
                return 0

        def main():
            widget = Widget()
            widget.initialize()
            widget.controller = Controller()
            print(widget.stop())
        """,
        """
        export class Controller {

            abort() {
                return 42;
            }
        }

        export class Widget {

            initialize() {
                this.controller = null;
            }

            constructor() {
                this.controller = null;
            }

            stop() {
                if (this.controller != null) {
                    return this.controller.abort();
                }
                return 0;
            }
        }

        export function main() {
            var widget = new Widget();
            widget.initialize();
            widget.controller = new Controller();
            console.log(widget.stop());
        }
        """,
    )


def test_initialize_reset_preserves_constructor_union_field_type():
    assert_transpile(
        """
        @js
        class Widget:
            def initialize(self) -> None:
                self.value = 0

            def __init__(self):
                self.value: int | str = "ready"

            def read(self) -> str:
                if isinstance(self.value, str):
                    return self.value
                return str(self.value)

        def main():
            widget = Widget()
            widget.initialize()
            widget.value = "changed"
            print(widget.read())
        """,
        """
        export class Widget {

            initialize() {
                this.value = 0;
            }

            constructor() {
                this.value = 'ready';
            }

            read() {
                if ((typeof this.value === 'string')) {
                    return this.value;
                }
                return String(this.value);
            }
        }

        export function main() {
            var widget = new Widget();
            widget.initialize();
            widget.value = 'changed';
            console.log(widget.read());
        }
        """,
    )


def test_custom_element_initializer_preserves_annotated_constructor_field():
    assert_transpile(
        """
        from pyjs.web.domx import CustomElement, tag
        from pyjs.web.dom import AbortController
        from pyjs.web.events import Event

        @js
        class Layout(CustomElement):
            def __init__(self):
                super().__init__()
                self.controller: AbortController | None = None

            def initialize(self):
                self.controller = None
                self.addEventListener("click", self.stop)

            def stop(self, event: Event):
                if self.controller is not None:
                    self.controller.abort()

        @js
        class Page(Layout):
            def __init__(self):
                super().__init__()
                tag(self, 'Page')

        def main():
            return Page()
        """,
        """
        import { CustomElement, tag } from './pyjs.web.domx.js';

        export class Layout extends CustomElement {

            _create() {
                super._create();
                this.controller = null;
                return this;
            }

            _hydrate() {
                super._hydrate();
            }

            initialize() {
                this.controller = null;
                this.addEventListener('click', this.stop.bind(this));
            }

            stop(event) {
                if (this.controller != null) {
                    this.controller.abort();
                }
            }
        }
        customElements.define('pyjs-layout', Layout)

        export class Page extends Layout {

            _create() {
                super._create();
                tag(this, 'Page');
                return this;
            }

            _hydrate() {
                super._hydrate();
            }
        }
        customElements.define('pyjs-page', Page)

        export function main() {
            return new Page()._create();
        }
        """,
    )


def test_subclass_initializer_preserves_base_constructor_field():
    assert_transpile(
        """
        from pyjs.web.domx import CustomElement
        from pyjs.web.dom import AbortController
        from pyjs.web.events import Event

        @js
        class Base(CustomElement):
            def __init__(self):
                super().__init__()
                self.controller: AbortController | None = None

        @js
        class Layout(Base):
            def __init__(self):
                super().__init__()

            def initialize(self):
                self.controller = None
                self.addEventListener("click", self.stop)

            def stop(self, event: Event):
                if self.controller is not None:
                    self.controller.abort()

        def main():
            return Layout()
        """,
        """
        import { CustomElement } from './pyjs.web.domx.js';

        export class Base extends CustomElement {

            _create() {
                super._create();
                this.controller = null;
                return this;
            }

            _hydrate() {
                super._hydrate();
            }
        }
        customElements.define('pyjs-base', Base)

        export class Layout extends Base {

            _create() {
                super._create();
                return this;
            }

            _hydrate() {
                super._hydrate();
            }

            initialize() {
                this.controller = null;
                this.addEventListener('click', this.stop.bind(this));
            }

            stop(event) {
                if (this.controller != null) {
                    this.controller.abort();
                }
            }
        }
        customElements.define('pyjs-layout', Layout)

        export function main() {
            return new Layout()._create();
        }
        """,
    )
