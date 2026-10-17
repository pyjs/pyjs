from pyjs.testing.helpers import ad, at, diagnostic_text
from tests.backend_semantics import (
    DATACLASS_IDENTITY_CONTRACT,
    DATACLASS_NAN_IDENTITY_SOURCE,
    POSTPONED_DATACLASS_CONTRACT,
)

from .helpers import assert_semantics


def test_dataclass_self_equality_skips_non_reflexive_fields():
    assert_semantics(DATACLASS_IDENTITY_CONTRACT.print_source + "\nmain()\n")


def test_dataclass_self_equality_with_nan_fields():
    source = DATACLASS_NAN_IDENTITY_SOURCE.replace("def main()", "def check()")
    assert_semantics(source + '\ndef main():\n    print(check())\nmain()\n')
    assert_semantics(source.replace("left: Record,", "left: Record | int,")
                     + '\ndef main():\n    print(check())\nmain()\n')


def test_postponed_slots_dataclass_resolves_nested_module_types():
    source = POSTPONED_DATACLASS_CONTRACT.replace("def main()", "def check()")
    assert_semantics(source + '\ndef main() -> None:\n    print(check())\nmain()\n')


def test_dataclass_callable_fields_preserve_signatures():
    assert_semantics(
        """\
        from collections.abc import Callable
        from dataclasses import dataclass

        from pyjs import js

        @js
        def build() -> str:
            return "built"

        @js
        def label(value: int) -> str:
            return f"item-{value}"

        @js
        def notify(value: int) -> None:
            print(f"notified-{value}")

        @js
        @dataclass
        class Actions:
            build: Callable[[], str]
            label: Callable[[int], str]
            notify: Callable[[int], None]
            optional_notify: Callable[[int], None] | None = None

        actions = Actions(build, label, notify)
        print(actions.build())
        print(actions.label(3))
        actions.notify(4)
        print(actions.optional_notify is None)
        """
    )


def test_dataclass_mapping_and_any_fields_match_python():
    assert_semantics(
        """\
        from collections.abc import Mapping, MutableMapping
        from dataclasses import dataclass
        from typing import Any

        from pyjs import js

        @js
        @dataclass
        class Record:
            values: Mapping[str, Any]
            mutable: MutableMapping[str, int]
            payload: Any

        record = Record({"name": "demo"}, {"count": 1}, "ready")
        record.mutable["count"] = 2
        print(record.values["name"], record.mutable["count"], record.payload)
        """
    )


def test_dataclass_construction_defaults_and_equality_match_python():
    assert_semantics(
        """\
        from dataclasses import dataclass, field

        from pyjs import js

        @js
        @dataclass
        class Record:
            name: str
            count: int = 1
            labels: list[str] = field(default_factory=list)
            aliases: tuple[str, ...] = field(default_factory=tuple)
            cached: bool = field(default=False, init=False, compare=False)
            category: str = field(default="general", kw_only=True)

            def __post_init__(self):
                self.cached = self.count > 1

        first = Record("one")
        second = Record("one", category="special")
        first.labels.append("changed")
        print(first.name, first.count, first.cached, first.category, second.category)
        print(len(first.labels), len(second.labels), len(first.aliases))
        print(first == second, first != second)
        second.labels.append("changed")
        print(first == second, first != second)
        print(repr(first))
        """
    )


def test_named_factories_and_user_defined_dataclass_methods_match_python():
    assert_semantics(
        """\
        from dataclasses import dataclass, field

        from pyjs import js

        @dataclass
        @js
        class Coordinate:
            x: int

        @js
        def make_coordinate() -> Coordinate:
            return Coordinate(3)

        @js
        @dataclass
        class Marker:
            coordinate: Coordinate = field(default_factory=make_coordinate)

        @js
        @dataclass(init=False, eq=False)
        class Token:
            value: int

            def __init__(self, value: int):
                self.value = value * 2

            def __eq__(self, other: object) -> bool:
                return isinstance(other, Token) and self.value == other.value

        left = Marker()
        right = Marker()
        left.coordinate.x = 4
        print(left.coordinate.x, right.coordinate.x)
        print(repr(left))
        print(Token(2).value, Token(2) == Token(2), Token(2) != Token(3))
        """
    )


def test_inherited_dataclass_fields_and_exact_class_equality_match_python():
    assert_semantics(
        """\
        from dataclasses import dataclass

        from pyjs import js

        @js
        @dataclass
        class Coordinate:
            x: int

        @js
        @dataclass
        class Point(Coordinate):
            y: int = 2

        coordinate = Coordinate(1)
        point = Point(1)
        same = Point(1, 2)
        print(point.x, point.y)
        print(point == same, point != same)
        print(point == coordinate, coordinate == point)
        """
    )


def test_dataclass_analysis_and_javascript_are_explicit_value_class_code():
    at(
        """
        from dataclasses import dataclass, field

        @js
        @dataclass
        class Point:
            x: int
            y: int = 2
            labels: list[str] = field(default_factory=list)

        def main():
            point = Point(1)
            print(point.x, point.y, len(point.labels))
            print(point == Point(1))
            print(repr(point))
        """,
        """
        class Point:

            def __init__(x: int, y: int=2, labels: list__str=dataclass_missing()) -> None:
                self.x: int = x
                self.y: int = y
                if labels.[object]__is__!(dataclass_missing()):
                    self.labels: list[str] = []
                else:
                    self.labels: list[str] = labels

            def __repr__() -> str:
                return 'Point(x='.[str]__add__!(self.x.[int]__repr__!()).[str]__add__!(', y=').[str]__add__!(self.y.[int]__repr__!()).[str]__add__!(', labels=').[str]__add__!($repr_value(self.labels)).[str]__add__!(')')

            def __eq__(other: object) -> bool:
                if self.[object]__is__!(other):
                    return True
                if not isinstance(other, Point):
                    return False
                if not same_dataclass_type(self, other):
                    return False
                return self.x.[int]__eq__!(other.x) and self.y.[int]__eq__!(other.y) and self.labels.[list__str]__eq__!(other.labels)

        def main() -> None:
            point: Point = Point(1)
            print(point.x, point.y, point.labels.[list__str]__len__!())
            print(point.[Point]__eq__(Point(1)))
            print(point.[Point]__repr__())
        """,
        """
        import { equal_value as $equal_value, repr_value as $repr_value } from './pyjs.python.js';

        export class Point {

            constructor(x, { y=2, labels=undefined} = {}) {
                this.x = x;
                this.y = y;
                if (labels === undefined) {
                    this.labels = [];
                } else {
                    this.labels = labels;
                }
            }

            __repr__() {
                return 'Point(x=' + String(this.x) + ', y=' + String(this.y) + ', labels=' + $repr_value(this.labels) + ')';
            }

            __eq__(other) {
                if (this === other) {
                    return true;
                }
                if (!((other instanceof Point))) {
                    return false;
                }
                if (!(this.constructor === other.constructor)) {
                    return false;
                }
                return this.x == other.x && this.y == other.y && ($equal_value(this.labels,other.labels));
            }
        }

        export function main() {
            var point = new Point(1);
            console.log(point.x, point.y, point.labels.length);
            console.log((point.__eq__(new Point(1)) ? 'True' : 'False'));
            console.log(point.__repr__());
        }
        """,
    )


def test_dataclass_asdict_and_replace_have_typed_lowering():
    at(
        """
        from dataclasses import asdict, dataclass, replace

        @js
        @dataclass(repr=False, eq=False)
        class Point:
            x: int
            y: int = 2

        def main():
            point = Point(1)
            moved = replace(point, x=3)
            values = asdict(moved)
            print(moved.x)
            print(repr(values))
        """,
        """
        class Point:

            def __init__(x: int, y: int=2) -> None:
                self.x: int = x
                self.y: int = y

        def main() -> None:
            point: Point = Point(1)
            moved: Point = replace(point, x=3)
            values: dict[str, object] = asdict(moved)
            print(moved.x)
            print($repr_value(values))
        """,
        """
        import { repr_value as $repr_value } from './pyjs.python.js';

        export class Point {

            constructor(x, { y=2} = {}) {
                this.x = x;
                this.y = y;
            }
        }

        export function main() {
            var point = new Point(1);
            var moved = new (point.constructor)(3, {y: point.y});
            var values = new Map([['x', moved.x], ['y', moved.y]]);
            console.log(moved.x);
            console.log($repr_value(values));
        }
        """,
    )


def test_dataclass_asdict_and_replace_match_nested_python_values():
    assert_semantics(
        """\
        from dataclasses import asdict, dataclass, field, replace

        from pyjs import js

        @js
        @dataclass(frozen=True)
        class Point:
            x: int
            y: int = 2

        @js
        @dataclass(repr=False, eq=False)
        class Drawing:
            origin: Point
            points: list[Point] = field(default_factory=list)
            selected: Point | None = None

        @js
        @dataclass
        class Score:
            value: int
            doubled: int = field(default=0, init=False)

            def __post_init__(self):
                self.doubled = self.value * 2

        drawing = Drawing(Point(1), [Point(2), Point(3, 4)])
        moved = replace(drawing, selected=Point(5, 6))
        print(repr(asdict(moved)))
        print(repr(asdict(drawing)))
        print(replace(Score(2), value=4).doubled)
        """
    )


def test_type_aliases_resolve_in_functions_and_dataclass_fields():
    at(
        """
        from dataclasses import dataclass

        from pyjs import js

        Vector = tuple[float, float]
        Vectors = list[Vector]

        @js
        @dataclass
        class Segment:
            start: Vector
            points: Vectors

        @js
        def first_x(segment: Segment) -> float:
            return segment.points[0][0]

        def main():
            segment = Segment((1.0, 2.0), [(3.0, 4.0)])
            print(first_x(segment))
        """,
        """
        class Segment:

            def __init__(start: tuple__float_float, points: list__tuple__float_float) -> None:
                self.start: tuple[float, float] = start
                self.points: list[tuple[float, float]] = points

        def first_x(segment: Segment) -> float:
            return $get_tuple_item($get_list_item(segment.points, 0), 0)

        def main() -> None:
            segment: Segment = Segment((1.0, 2.0), [(3.0, 4.0)])
            print($float_string(first_x(segment)))
        """,
        """
        import { float_string as $float_string, get_tuple_item as $get_tuple_item, get_list_item as $get_list_item } from './pyjs.python.js';

        export class Segment {

            constructor(start, points) {
                this.start = start;
                this.points = points;
            }
        }

        export function first_x(segment) {
            return $get_tuple_item($get_list_item(segment.points, 0), 0);
        }

        export function main() {
            var segment = new Segment([1.0, 2.0], [[3.0, 4.0]]);
            console.log($float_string(first_x(segment)));
        }
        """,
    )


def test_explicit_and_python_314_type_aliases_match_python():
    assert_semantics(
        """\
        from typing import TypeAlias

        from pyjs import js

        type Vector = tuple[float, float]
        Path: TypeAlias = list[Vector]

        @js
        def first_x(path: Path) -> float:
            return path[0][0]

        print(first_x([(3.5, 4.0)]))
        """
    )


def test_asdict_supports_finite_values_of_recursive_dataclass_types():
    assert_semantics(
        """\
        from dataclasses import asdict, dataclass, field
        from typing import Optional

        from pyjs import js

        @js
        @dataclass(repr=False, eq=False)
        class Node:
            value: int
            child: Optional["Node"] = None
            children: list["Node"] = field(default_factory=list)

        root = Node(1, Node(2), [Node(3)])
        print(repr(asdict(root)))
        """
    )


def test_recursive_dataclass_equality_matches_python():
    assert_semantics(
        """\
        from dataclasses import dataclass

        from pyjs import js

        @js
        @dataclass
        class Node:
            value: int
            child: Node | None = None

        print(Node(1, Node(2)) == Node(1, Node(2)))
        print(Node(1, Node(2)) == Node(1, Node(3)))
        print(Node(1) == Node(1))
        print(Node(1, Node(2)) != Node(1, Node(3)))
        print(repr(Node(1, Node(2))))
        """
    )


def test_recursive_dataclass_equality_uses_runtime_union_dispatch():
    at(
        """
        from dataclasses import dataclass

        @js
        @dataclass
        class Node:
            value: int
            child: Node | None = None

        def main():
            print(Node(1, Node(2)) == Node(1, Node(2)))
        """,
        """
        class Node:

            def __init__(value: int, child: Node | None=None) -> None:
                self.value: int = value
                self.child: Node | None = child

            def __eq__(other: object) -> bool:
                if self.[object]__is__!(other):
                    return True
                if not isinstance(other, Node):
                    return False
                if not same_dataclass_type(self, other):
                    return False
                return self.value.[int]__eq__!(other.value) and $equal_value(self.child, other.child)

        def main() -> None:
            print(Node(1, Node(2)).[Node]__eq__(Node(1, Node(2))))
        """,
        """
        import { equal_value as $equal_value } from './pyjs.python.js';

        export class Node {

            constructor(value, { child=null} = {}) {
                this.value = value;
                this.child = child;
            }

            __eq__(other) {
                if (this === other) {
                    return true;
                }
                if (!((other instanceof Node))) {
                    return false;
                }
                if (!(this.constructor === other.constructor)) {
                    return false;
                }
                return this.value == other.value && $equal_value(this.child, other.child);
            }
        }

        export function main() {
            console.log((new Node(1, {child: new Node(2)}).__eq__(new Node(1, {child: new Node(2)})) ? 'True' : 'False'));
        }
        """,
    )


def test_replace_rejects_fields_that_are_not_constructor_inputs():
    ad(
        """\
        from dataclasses import dataclass, field, replace

        from pyjs import js

        @js
        @dataclass
        class Record:
            name: str
            cached: bool = field(default=False, init=False)

        def main():
            replace(Record("one"), cached=True)
        """,
        diagnostic_text(
            "replace.py",
            12,
            'replace(Record("one"), cached=True)',
            "^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: replace() cannot set 'cached' on Record "
            "[PYJS1104]",
            "help: Replace only fields declared with init=True.",
        ),
        filename="replace.py",
    )


def test_replace_rejects_incompatible_field_values():
    ad(
        """\
        from dataclasses import dataclass, replace

        from pyjs import js

        @js
        @dataclass
        class Record:
            count: int

        def main():
            replace(Record(1), count="many")
        """,
        diagnostic_text(
            "replace_type.py",
            11,
            'replace(Record(1), count="many")',
            "                         ^^^^^^",
            "pyjs.CompilationError: replace() field 'count' expects int, not str "
            "[PYJS1104]",
            "help: Pass a value compatible with int.",
        ),
        filename="replace_type.py",
    )


def test_frozen_dataclass_field_assignment_has_a_focused_diagnostic():
    ad(
        """
        from dataclasses import dataclass

        from pyjs import js

        @js
        @dataclass(frozen=True)
        class Point:
            x: int

        def main():
            point = Point(1)
            point.x = 2
        """,
        """
          File "frozen_dataclass.py", line 13
            point.x = 2
            ^^^^^^^
        pyjs.CompilationError: Cannot assign to field 'x' of frozen dataclass 'Point' [PYJS1103]
        help: Remove frozen=True or create a new value instead.
        """,
        filename="frozen_dataclass.py",
    )
