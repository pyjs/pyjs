import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source

from .helpers import assert_semantics


@pytest.mark.parametrize("value", [
    '""', '"quotes \\\" and newline \\n"', "True", "False", "None",
    "0", "-42", "2.5", '["", "first", "second"]',
    '[True, False, None, 0, 2.5, "text"]',
])
def test_json_stringify_scalars_and_arrays(value):
    assert_semantics(f'''
        from pyjs.javascript import JSON

        def main():
            print(JSON.stringify({value}))

        main()
    ''')


def test_json_stringify_unicode_round_trip():
    # JSON escape spellings need not match between runtimes; decoded text must.
    assert_semantics('''
        from pyjs.javascript import JSON, JSONObject

        class Record(JSONObject):
            value: list[str]

        def main():
            values = ["é", "🛳", "", "quotes \\\" and newline \\n"]
            source = '{"value":' + JSON.stringify(values) + '}'
            decoded: Record = JSON.parse(source)
            print(decoded["value"] == values)

        main()
    ''')


@pytest.mark.parametrize("ending", ["", "return", "return None"])
@pytest.mark.parametrize("argument", ["produce(calls, False)", "value=produce(calls, False)"])
def test_json_stringify_missing_return_is_null(ending, argument):
    assert_semantics(f'''
        from pyjs import js
        from pyjs.javascript import JSON, JSONObject

        class Record(JSONObject):
            value: str | None

        @js
        def produce(calls: list[int], hit: bool) -> str | None:
            calls.append(1)
            if hit:
                return "found"
            {ending}

        @js
        def nothing() -> None:
            pass

        def main():
            calls: list[int] = []
            serialized = JSON.stringify({argument})
            print(serialized == "null", len(serialized), len(calls))
            decoded: Record = JSON.parse('{{"value":' + serialized + '}}')
            print(decoded["value"] is None)
            print(JSON.stringify(produce(calls, True)), len(calls))
            mapped = list(map(JSON.stringify, [produce(calls, False)]))
            print(mapped[0], len(mapped[0]), len(calls))
            print(JSON.stringify(nothing()))

        main()
    ''')


@pytest.mark.parametrize("annotation", ["dict[str, str]", "list[dict[str, str]]", "set[str]"])
def test_json_stringify_rejects_non_json_containers(annotation):
    with pytest.raises(CompilationError, match="JSON.stringify expects"):
        analyze_source(f'''
from pyjs.javascript import JSON
def main(value: {annotation}) -> str:
    return JSON.stringify(value)
''')


@pytest.mark.parametrize("annotation", [
    "int64", "list[int64]", "int64 | None", "list[int64 | str]",
    "list[int64] | str", "Record", "list[Record]",
])
@pytest.mark.parametrize("argument", ["value", "value=value"])
def test_json_stringify_rejects_bigint_representations(annotation, argument):
    with pytest.raises(CompilationError, match="JSON.stringify cannot serialize int64") as caught:
        analyze_source(f'''
from pyjs.javascript import JSON, JSONObject
from pyjs.numeric import int64
class Record(JSONObject):
    values: list[int64]
def main(value: {annotation}) -> str:
    return JSON.stringify({argument})
''', filename="bigint_json.py")
    assert caught.value.filename == "bigint_json.py"
    assert caught.value.lineno == 7
    assert "PYJS1104" in str(caught.value)


def test_json_stringify_keyword_and_number_representations():
    assert_semantics('''
        from pyjs import js
        from pyjs.javascript import JSON, JSONObject
        from pyjs.numeric import int32, int64, float32

        class Record(JSONObject):
            value: str

        @js
        def produce(calls: list[int]) -> Record:
            calls.append(1)
            return Record(value="text")

        def main():
            calls: list[int] = []
            print(JSON.stringify(value=produce(calls)))
            print(len(calls))
            print(JSON.stringify(value="text"))
            print(JSON.stringify(value=[False, None, 2]))
            print(JSON.stringify(int32(5)))
            print(JSON.stringify(float32(0.5)))
            print(JSON.stringify([int32(2), int32(3)]))
            print(JSON.stringify(str(int64(9223372036854775807))))
            print(JSON.stringify(int(int64(5))))

        main()
    ''')


@pytest.mark.parametrize("arguments", ["", "1, 2", "1, value=2", "other=1", "*[1]"])
def test_json_stringify_requires_one_value(arguments):
    with pytest.raises(CompilationError, match="PYJS1104"):
        analyze_source(f'''
from pyjs.javascript import JSON
def main() -> str:
    return JSON.stringify({arguments})
''')
