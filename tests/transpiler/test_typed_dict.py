from pyjs.testing.helpers import ad, at, diagnostic_text


def test_typed_dict_uses_plain_object_operations():
    at(
        """
        from typing import NotRequired
        from pyjs.javascript import JSON, JSONObject

        class Record(JSONObject):
            title: str
            count: int
            note: NotRequired[str]

        def main():
            record: Record = JSON.parse('{"title":"Hi","count":2}')
            title = record["title"].lower()
            count = record.get("count")
            note = record.get("note", "none")
            size = len(record)
            present = "title" in record
            keys = record.keys()
        """,
        """
        def main() -> None:
            record: Record = JSON.[JSON]parse('{"title":"Hi","count":2}')
            title: str = record['title'].[str]lower!()
            count: int = record.[typed_dict]get!('count')
            note: str = record.[typed_dict]get!('note', 'none')
            size: int = record.[typed_dict]__len__!()
            present: bool = record.[typed_dict]__contains__!('title')
            keys: Iterable[str] = record.[typed_dict]keys!()
        """,
        """
        export function main() {
            var record = JSON.parse('{"title":"Hi","count":2}');
            var title = record['title'].toLowerCase();
            var count = ((mapping,key,fallback)=>Object.hasOwn(mapping,key)?mapping[key]:fallback)(record,'count',null);
            var note = ((mapping,key,fallback)=>Object.hasOwn(mapping,key)?mapping[key]:fallback)(record,'note','none');
            var size = Object.keys(record).length;
            var present = Object.hasOwn(record, 'title');
            var keys = Object.keys(record);
        }
        """,
    )


def test_typed_dict_literals_and_constructors_are_plain_objects():
    at(
        """
        from typing import TypedDict

        class Inner(TypedDict):
            name: str

        class Outer(TypedDict):
            inner: Inner
            enabled: bool

        def main():
            one = Inner(name="one")
            copied = Inner(one)
            mapped = Inner({"name": "mapped"})
            two: Inner = {"name": "two"}
            outer: Outer = {"inner": {"name": "nested"}, "enabled": True}
            first = one["name"]
            second = two["name"]
            nested = outer["inner"]["name"]
        """,
        """
        def main() -> None:
            one: Inner = Inner(name='one')
            copied: Inner = Inner(one)
            mapped: Inner = Inner({'name': 'mapped'})
            two: Inner = {'name': 'two'}
            outer: Outer = {'inner': {'name': 'nested'}, 'enabled': True}
            first: str = one['name']
            second: str = two['name']
            nested: str = outer['inner']['name']
        """,
        """
        export function main() {
            var one = ({name: 'one'});
            var copied = ({...one});
            var mapped = ({...Object.fromEntries(new Map([['name', 'mapped']]))});
            var two = {'name': 'two'};
            var outer = {'inner': {'name': 'nested'}, 'enabled': true};
            var first = one['name'];
            var second = two['name'];
            var nested = outer['inner']['name'];
        }
        """,
    )


def test_generic_typed_dicts_ignore_the_runtime_generic_marker_base():
    at(
        """
        from typing import TypedDict

        class Envelope[T](TypedDict):
            value: T

        def main():
            print("ready")
        """,
        """
        def main() -> None:
            print('ready')
        """,
        """
        export function main() {
            console.log('ready');
        }
        """,
    )


def test_typed_dict_keys_require_string_literals():
    ad(
        """\
        from typing import TypedDict
        from pyjs import js

        class Record(TypedDict):
            name: str

        @js
        def read(record: Record, key: str) -> str:
            return record[key]
        """,
        diagnostic_text(
            "typed_dict.py",
            9,
            "return record[key]",
            "              ^^^",
            "pyjs.CompilationError: TypedDict keys must be string literals "
            "[PYJS2001]",
            "help: Use a literal key so its field type can be determined statically.",
        ),
        filename="typed_dict.py",
    )

    ad(
        """\
        from typing import TypedDict
        from pyjs import js

        class Record(TypedDict):
            name: str

        @js
        def make(key: str) -> Record:
            value: Record = {key: "test"}
            return value
        """,
        diagnostic_text(
            "typed_dict.py",
            9,
            "value: Record = {key: 'test'}",
            "                 ^^^",
            "pyjs.CompilationError: TypedDict literal keys must be string literals "
            "[PYJS2001]",
            "help: Use a literal key so its field type can be determined statically.",
        ),
        filename="typed_dict.py",
    )


def test_typed_dict_reports_unknown_keys():
    source = """\
        from typing import TypedDict
        from pyjs import js

        class Record(TypedDict):
            name: str
            age: int

        @js
        def read(record: Record) -> str:
            return record["missing"]
        """
    ad(
        source,
        diagnostic_text(
            "typed_dict.py",
            10,
            "return record['missing']",
            "              ^^^^^^^^^",
            "pyjs.CompilationError: Record has no key 'missing' [PYJS1005]",
            "help: Use one of: 'name', 'age'.",
        ),
        filename="typed_dict.py",
    )

    ad(
        source.replace('record["missing"]', 'record.get("missing")'),
        diagnostic_text(
            "typed_dict.py",
            10,
            "return record.get('missing')",
            "                  ^^^^^^^^^",
            "pyjs.CompilationError: Record has no key 'missing' [PYJS1005]",
            "help: Use one of: 'name', 'age'.",
        ),
        filename="typed_dict.py",
    )


def test_json_parse_requires_a_json_object_schema():
    ad(
        """\
        from pyjs.javascript import JSON

        def main():
            value = JSON.parse("{}")
        """,
        diagnostic_text(
            "json_parse.py",
            4,
            'value = JSON.parse("{}")',
            "        ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Cannot infer type parameter 'T' for parse "
            "[PYJS1104]",
            "help: Add a contextual annotation or pass an argument that "
            "determines the type.",
        ),
        filename="json_parse.py",
    )

    ad(
        """\
        from typing import TypedDict
        from pyjs.javascript import JSON

        class Record(TypedDict):
            name: str

        def main():
            value: Record = JSON.parse("{}")
        """,
        diagnostic_text(
            "json_parse.py",
            8,
            'value: Record = JSON.parse("{}")',
            "                ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Type argument Record for T does not satisfy "
            "bound JSONObject | list[JSONObject] [PYJS1104]",
            "help: Pass a JSONObject | list[JSONObject] subtype for T.",
        ),
        filename="json_parse.py",
    )

    ad(
        """\
        from pyjs.javascript import JSON

        def main():
            values: list[int] = JSON.parse("[]")
        """,
        diagnostic_text(
            "json_parse.py",
            4,
            'values: list[int] = JSON.parse("[]")',
            "                    ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Type argument list[int] for T does not "
            "satisfy bound JSONObject | list[JSONObject] [PYJS1104]",
            "help: Pass a JSONObject | list[JSONObject] subtype for T.",
        ),
        filename="json_parse.py",
    )


def test_json_parse_preserves_nested_schema_types():
    at(
        """
        from pyjs.javascript import JSON, JSONObject

        class Details(JSONObject):
            active: bool

        class Record(JSONObject):
            details: Details
            labels: list[str]

        @js
        def decode(source: str) -> Record:
            return JSON.parse(source)

        @js
        def decode_many(source: str) -> list[Record]:
            return JSON.parse(source)

        @js
        def is_active(record: Record) -> bool:
            return record["details"]["active"]

        def main():
            record = decode('{"details":{"active":true},"labels":["new"]}')
            active = record["details"]["active"]
            label = record["labels"][0]
            source = '{"details":{"active":true},"labels":[]}'
            parsed_active = is_active(JSON.parse(source))
            records_source = "[" + source + "]"
            records = decode_many(records_source)
            first_active = records[0]["details"]["active"]
        """,
        """
        def decode(source: str) -> Record:
            return JSON.[JSON]parse(source)

        def decode_many(source: str) -> list[Record]:
            return JSON.[JSON]parse(source)

        def is_active(record: Record) -> bool:
            return record['details']['active']

        def main() -> None:
            record: Record = decode('{"details":{"active":true},"labels":["new"]}')
            active: bool = record['details']['active']
            label: str = $get_list_item(record['labels'], 0)
            source: str = '{"details":{"active":true},"labels":[]}'
            parsed_active: bool = is_active(JSON.[JSON]parse(source))
            records_source: str = '['.[str]__add__!(source).[str]__add__!(']')
            records: list[Record] = decode_many(records_source)
            first_active: bool = $get_list_item(records, 0)['details']['active']
        """,
        """
        import { get_list_item as $get_list_item } from './pyjs.python.js';

        export function decode(source) {
            return JSON.parse(source);
        }

        export function decode_many(source) {
            return JSON.parse(source);
        }

        export function is_active(record) {
            return record['details']['active'];
        }

        export function main() {
            var record = decode('{"details":{"active":true},"labels":["new"]}');
            var active = record['details']['active'];
            var label = $get_list_item(record['labels'], 0);
            var source = '{"details":{"active":true},"labels":[]}';
            var parsed_active = is_active(JSON.parse(source));
            var records_source = '[' + source + ']';
            var records = decode_many(records_source);
            var first_active = $get_list_item(records, 0)['details']['active'];
        }
        """,
    )


def test_json_parse_rejects_incompatible_nested_fields():
    ad(
        """\
        from pyjs.javascript import JSON, JSONObject

        class Record(JSONObject):
            metadata: dict[str, str]

        def main():
            value: Record = JSON.parse("{}")
        """,
        diagnostic_text(
            "json_schema.py",
            7,
            'value: Record = JSON.parse("{}")',
            "                ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: JSON schema field 'Record.metadata' uses dict, "
            "whose JavaScript representation is Map [PYJS1104]",
            "help: Use JSON primitives, lists, and JSONObject fields in the schema.",
        ),
        filename="json_schema.py",
    )


def test_json_stringify_rejects_map_backed_dicts():
    ad(
        """\
        from pyjs.javascript import JSON

        def main():
            JSON.stringify({"name": "PyJS"})
        """,
        diagnostic_text(
            "json_stringify.py",
            4,
            'JSON.stringify({"name": "PyJS"})',
            "               ^^^^^^^^^^^^^^^^",
            "pyjs.CompilationError: Argument 'value' to JSON.stringify expects "
            "JSONObject|list[JSONObject]|str|bool|int|float|NoneType|"
            "list[str | bool | int | float | NoneType], got dict[str, str] [PYJS1104]",
            "help: Pass a value compatible with JSONObject|list[JSONObject]|str|"
            "bool|int|float|NoneType|list[str | bool | int | float | NoneType].",
        ),
        filename="json_stringify.py",
    )
